# CP-6 / M2 — two-machine execution demo runbook

The M2 exit gate is evidence, not a green suite: a real person on a
*different* machine, authenticating as themselves, running a query
against the customer's production database and being stopped by each
guardrail in turn.

Everything else in M2 is already evidenced (D-69: JP-2 measured, live
Supabase/GA4/GSC execution, live startup refusal, security review #2).
This is the last item.

---

## What machine 2 needs

**Almost nothing — that is the architectural claim being tested.**

| Needed | Not needed |
|---|---|
| Claude Code (or any MCP client speaking streamable HTTP + OAuth) | Docker |
| A web browser (for the login screen) | This repo / any source code |
| Network reach to machine 1 on ports **8100** and **8180** | Python, Node, psql |
| — | Any database credential |

Machine 2 never touches the database. It holds no secret. It gets a
short-lived OAuth token for a *person*, and every decision is made
server-side on machine 1. A phone on the same Wi-Fi could do the read
half.

"Same network" = same LAN/Wi-Fi. If the two machines cannot reach each
other, nothing below works; test with `ping <LAN-IP>` from machine 2
before anything else.

---

## Machine 1 — prep

### 1. Find the LAN IP and keep it

```bash
ipconfig getifaddr en0        # e.g. 192.168.1.42
```

Everything below uses it. `localhost` will **not** work from machine 2.

### 2. Prerequisites that are not code

- **KB PR #18 merged** (M1's open item): the profiles and the
  `roles.yaml` OIDC wiring must be at KB HEAD, or the server cannot
  resolve any profile.
- **A second KB PR granting the Reporter execution**, since M2's demo is
  a *reporter* executing. In `.contextlayer/profiles/reporter.yaml`:

  ```yaml
  tools:
    allow: [search_context, get_entity, get_table, get_metric, get_lineage,
            validate_sql, execute_sql:supabase, report_freshness, flag_gap]
  limits: { row_cap: 50000, timeout_s: 60 }
  ```

  Note the qualifier: `execute_sql:supabase` grants supabase **only** —
  the same profile cannot execute against ga4 or gsc.

  > **Read security review #2 F2 before merging this.** Granting a
  > Reporter-class profile execute is exactly the change that makes F2
  > live: the KB visibility map governs content tools but not execution.
  > For *this* pilot it is not exploitable — R1's visibility is
  > `systems/**`, so the reporter can already see every system doc, and
  > the execution role reaches only `public`. But the general question
  > should be ruled on before CP-7 generalizes this profile.

- **Execution role applied** (done — `example_exec` verified live).

### 3. Start the stack, bound to the LAN

```bash
cd ~/Desktop/DataProject
CL_HOST_ADDR=<LAN-IP> CL_BIND=0.0.0.0 CORE_MCP_ENABLED=1 \
  docker compose -f docker-compose.yml -f deploy/compose.live.yml up -d --build
```

`CL_BIND=0.0.0.0` is what makes the ports reachable from machine 2;
`CL_HOST_ADDR` is what makes the OAuth redirect point back at a host
machine 2 can actually resolve. Getting either wrong shows up as a login
that hangs or redirects to `localhost`.

### 4. Register the connection and pull snapshots

```bash
docker compose exec core sh -c \
  'node dist/cli.js systems set jobs/live/supabase-connection.json'
make stack-live
```

The connection registration is what the execution gateway resolves. It
carries two credentials for two distinct roles; only the one marked
`required_for: ["query"]` is forwarded to an execute job (G3).

### 5. Confirm the runner will actually serve execution

```bash
docker compose logs runner | grep -i "execution preflight"
```

Expected:

```
INFO execution preflight passed for postgres: {'role': 'example_exec', ...}
```

If it says **FAILED**, the runner is refusing to serve execution and
says why — that is the G3 gate doing its job. Execute jobs will hang
until their deadline because nobody claims them. Fix the role before
demoing.

---

## Machine 2 — the demo

### 6. Connect as the reporter

```bash
claude mcp add --transport http context-layer \
  "http://<LAN-IP>:8100/mcp?profile=reporter"
```

A browser opens. Log in as **`reporter` / `reporter-dev-pw`**.

> The dev IdP is dev-only. A real deployment points `CORE_OIDC_ISSUER`
> at the customer's own identity provider and this step becomes the
> company SSO screen.

### 7. Resolve → validate → execute (the happy path)

In the Claude Code session, in plain language:

1. *"What tables do we have about jobs?"* → `search_context`, then
   `get_table`. Point out the **trust block**: status, last verified,
   and `snapshot_ref`.
2. *"Validate this: `SELECT count(*) FROM public.jobs`"* → `validate_sql`
   returns `verdict: pass` **and a validation token**.
3. *"Now run it."* → `execute_sql` returns real rows from the customer
   database.

**What to point at:** the caller never supplied a row cap or a timeout.
The server attached the Reporter profile's own limits, and the query ran
under `example_exec`, not under any credential machine 2 holds.

### 8. The refusals — the actual point of the demo

Run these in order; each one fails differently, and the difference is
the evidence:

| # | Ask for | Expected | What it proves |
|---|---|---|---|
| a | `SELECT ... FROM public.jobs LIMIT 100000` (over cap) | rows capped at 50 000, `truncated: true` | The cap is the server's, applied while streaming (CI-7) |
| b | `WITH w AS (DELETE FROM public.jobs RETURNING id) SELECT * FROM w` | **refused at validate** — no token issued | A CTE-wrapped write reads like a SELECT and is not one |
| c | Wait 5+ minutes, then re-run the token from step 7 | `revalidate_required` | Tokens expire; validation is not a one-time permission slip |
| d | `SELECT * FROM auth.users` | refused | The execution role cannot reach `auth` at all |
| e | `execute_sql` against `ga4` | `permission_denied` | The grant is `execute_sql:supabase`, qualifier-enforced |

For **(b)**, the strong version of the claim: the parser refused it, and
*even if the parser had been defeated*, the database role would have.
Show that on machine 1:

```bash
psql "$CL_EXEC_DSN" -c "DELETE FROM public.jobs"
# ERROR: permission denied for table jobs
```

### 9. Show the audit — on machine 1

```bash
docker compose exec postgres psql -U postgres -d contextlayer -c \
  "SELECT ts, subject, profile, tool, decision, decision_reason,
          left(statement_text, 60) AS statement
     FROM audit_records WHERE tool IN ('validate_sql','execute_sql')
    ORDER BY ts DESC LIMIT 20"
```

Every call from machine 2 is there under the **reporter's** identity —
allowed and denied alike, each with its reason and the full statement
text. Nothing was attributed to a service account.

### 10. Startup refusal (the G3 exhibit)

Worth showing because it is the guardrail people find hardest to
believe:

```bash
# point execution at a role that CAN write
docker compose exec runner sh -c \
  'CL_EXEC_DSN="$SUPABASE_DSN" python -m connectors.sdk.service \
     --config /etc/contextlayer/runner.yaml --once -v' 2>&1 | head -20
```

```
ERROR execution preflight FAILED for postgres: execution role 'postgres'
holds CREATEDB, CREATEROLE, BYPASSRLS; execution requires a role with
none of these (G3). Refusing to serve execution.
```

The runner then declares `types: ['snapshot']` — it withholds execution
entirely while metadata sync keeps running.

---

## Evidence to capture for the gate

- [ ] Reporter session validates then executes a real SELECT; rows return
- [ ] Expired token → `revalidate_required`
- [ ] CTE-wrapped write refused at validate **and** (staged) at the DB role
- [ ] Over-cap query → `truncated: true` at the profile's cap
- [ ] `execute_sql` on a non-granted system → `permission_denied`
- [ ] GA4 `runReport` + GSC query for documented fields; undocumented
      dimension refused *(already captured in `tests/test_live_execute.py`;
      re-run live if you want it inside the same session)*
- [ ] Startup role check refuses a write-capable role, and says why
- [ ] Audit shows every execute with full statement; denials present with
      reasons

---

## If it does not work

| Symptom | Cause |
|---|---|
| Browser redirects to `localhost` and hangs | `CL_HOST_ADDR` not set to the LAN IP |
| Machine 2 cannot reach the URL at all | `CL_BIND=0.0.0.0` missing, or a firewall — check `ping` first |
| `execute_sql` hangs then `upstream_error` | No runner is claiming — check step 5; preflight probably failed |
| `config_error: no credential marked for the query capability` | Step 4 not run, or the connection JSON lacks `required_for: ["query"]` |
| `not_found: no accepted snapshot for system supabase` | `make stack-live` not run |
| Every tool call `permission_denied` | Profile PR not merged to KB HEAD |
