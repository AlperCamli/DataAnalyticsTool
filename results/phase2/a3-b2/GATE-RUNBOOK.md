# A-3 + B-2 — the gate demo (operator runbook)

One machine: this Mac. Everything below happens in **a browser**, as
your own IdP identity, against the live pilot stack. No `psql`, no
`docker exec`, no admin CLI — that is the point of the checkpoint, so
using one would invalidate the demo rather than shortcut it.

Read the page once before starting. Roughly 20 minutes.

---

## 1. What this run proves

| # | Gate clause | How this run shows it |
|---|---|---|
| 1 | Connection CRUD + test over the governed API with server-side role checks | Acts 3–5, in the browser, as an ops identity; act 6 as a non-ops one |
| 2 | Per-source health | Act 3 — five pilot connections, each with a health state and the reason for it |
| 3 | A source is wired, tested and health-checked **without a DBA shell or a direct-DB write** | Acts 3–5, plus the absence of any terminal in the screenshots |
| 4 | An `auth_error` produces a re-auth prompt | Act 5b — deliberately point a scratch connection at a reference with no value |
| 5 | The admin CLI is a thin client of the same API; no direct-DB path remains | Machine-checked (`connections.test.ts`); act 7 shows the CLI answering from the API |
| 6 | Registration returns what the store now holds | Machine-checked (`connections.test.ts`, with the write suppressed by a trigger); act 4 shows the read-back in the UI |
| 7 | Playbook step-3's exit is satisfiable as written by a customer operator | The whole run is playbook §6 followed literally |

Clauses 5 and 6 have machine-checked halves that ran before this page
was written: `core/test/connections.test.ts` (15 tests) and
`core/test/connections-e2e.test.ts` (2 tests, a live Postgres and a live
runner — a good credential probes green, a wrong password produces
`auth_error` and the re-auth prompt). **The live run is the operator
half**: that the shipped screens are usable by a person following the
playbook, on the real estate, with the real five connections.

## 2. Words used below

- **Connection** — a registered source: a system name, a connector, a
  config block, and **credential references**. Never a credential.
- **Reference** — `env://NAME` today (`vault://PATH` after A-4). The
  product stores the name; the value lives where the runner's resolver
  reads it.
- **Health** — green / amber / red / unknown, each with a stated reason.
  Amber and unknown are answers, not formatting problems: read them.
- **Unprobed** — a capability the test could not exercise. It is not a
  pass and the screen says so.

## 3. Before you start

| Prerequisite | How to check | Note |
|---|---|---|
| Suites green at this commit | `cd core && npx vitest run` and `.venv/bin/python -m pytest -q` | the Python `test_no_contamination_in_current_kb` failure is estate state (34 docs awaiting triage), not this code |
| The stack is running the build that contains the dashboard | act 0 | an older image has no `/app/` |
| You have an identity with the `ops` role | the pilot steward account carries `["steward","ops"]` | a steward-only identity is act 6's read-only case |
| Loopback binding | `CORE_PUBLIC_URL` on `127.0.0.1` | **this demo needs no non-loopback binding**, so the A-2 runbook's dev-IdP exposure step (act 3.0 there) does *not* apply. If you bind to the LAN for any reason, do that step first |

### Act 0 — rebuild and restart

```bash
cd ~/Desktop/DataProject
docker compose -f docker-compose.yml -f deploy/compose.live.yml build core
docker compose -f docker-compose.yml -f deploy/compose.live.yml up -d core runner
docker compose -f docker-compose.yml -f deploy/compose.live.yml exec core node dist/cli.js migrate
```

The migrate step applies `0011_audit_setup_stamp.sql` (PA-3). The build
step is what puts the browser bundle in the image — a core without it
serves a page that says so rather than a blank one, which is itself
worth one screenshot if you see it.

### Act 1 — open the window

```bash
date -u +%Y-%m-%dT%H:%M:%SZ | tee results/phase2/a3-b2/window-start.txt
```

Everything after this instant is the demo's evidence window.

---

## 4. The run

### Act 2 — sign in

Open **<http://127.0.0.1:8100/app/>**. You should be sent to the IdP,
sign in as yourself, and land back in the dashboard with your own
subject in the top bar.

> 📸 **Screenshot 1** — the dashboard after sign-in, showing your
> identity in the top bar and the module list in the sidebar.

*What to notice:* the sidebar lists every module in the registry, with
the unbuilt ones marked. That is deliberate (UI-10) — a menu that
silently omits B-1's screens would tell a customer nothing about what is
coming. If any of that reads as broken rather than honest, that is a
note worth writing down.

### Act 3 — the five pilot connections, with health

Open **Connections**. You should see `supabase`, `ga4`, `gsc`,
`looker_studio`, `powerbi` — the rows that have been in the registry
since the pilot was wired, readable through the new API unchanged.

> 📸 **Screenshot 2** — the connections list with all five and their
> health states.

*What to notice, and to write down if it surprises you:*

- Each row states a health **reason**, not just a colour.
- A row's credential **references** are visible; no value is.
- If freshness reads `unknown` for everything, `sync-policy.yaml` could
  not be read — the banner at the top says so. That is a real condition,
  not a rendering bug.

### Act 4 — add a scratch connection

Scroll to **Register a connection** and add one that touches nothing
real:

- System: `scratch-demo`
- Connector: `postgres`
- Version constraint: `*`
- Config:
  ```json
  { "system": "scratch-demo", "mode": "live", "dsn_env": "CL_SCRATCH_DSN" }
  ```
- Credential references:
  ```json
  [ { "key": "dsn", "ref": "env://CL_SCRATCH_DSN", "required_for": ["live"] } ]
  ```

Press **Register**. The confirmation says the row came back from the
store on re-read — that sentence is gate clause 6 in the UI.

> 📸 **Screenshot 3** — the confirmation and the new row in the list.

**Then try to break the rule on purpose.** Register again, same system,
but put a real-looking DSN in the config instead of the reference:

```json
{ "system": "scratch-demo", "mode": "live", "dsn": "postgres://u:p@h:5432/db" }
```

It must be refused with `raw_secret_rejected`, naming `config.dsn` and
telling you to use `dsn_env`. Check the message: it must not contain the
password you typed.

> 📸 **Screenshot 4** — the refusal.

### Act 5 — test each connection

Press **Test connection** on each of the five pilot rows, then on
`scratch-demo`. Take your time and read each verdict.

Expected shapes — none of these is a failure of the demo:

| Connection | Likely verdict | Why |
|---|---|---|
| `supabase` | pass, with role facts for metadata and query | the probe connects as the introspection role and checks the execution role's wall |
| `ga4` / `gsc` | pass with property/site facts, **or** `auth_error` | one real API call each; if the service-account key has rotated, this is the re-auth path firing on a real source |
| `looker_studio` | pass with `unprobed: [publish]` | the template-link path holds no credential and CI-5's tenant probe is unbuilt |
| `powerbi` | pass with `unprobed: [publish]` | same — `powerbi preflight` remains the provisioning check |
| `scratch-demo` | `auth_error` (5b below) | `CL_SCRATCH_DSN` is set nowhere |

> 📸 **Screenshot 5** — a passing test with its checks expanded.

**5b — the re-auth prompt.** `scratch-demo`'s reference resolves to
nothing, so the runner refuses it before the probe runs and the verdict
is `auth_error`. The screen must show a **re-auth prompt** naming
`env://CL_SCRATCH_DSN` and saying to refresh the value where the
resolver reads it.

> 📸 **Screenshot 6** — the re-auth prompt.

*If any pilot connection produces `auth_error` in act 5, that is a real
finding about the estate.* Record it and fix the credential's value;
do not edit the connection.

### Act 6 — the role gate, from the other side

Sign out. Sign in as an identity that has a steward profile but **no
`ops` role**. Open Connections.

You should see the list, read-only, and any write — register, remove,
test — must come back as the server's own 403 rendered on the page.

> 📸 **Screenshot 7** — the 403 as the module renders it.

*What to notice:* the buttons are still there. That is deliberate
(UI-1): the server decides, the client shows what it decided. A hidden
button would teach nobody why it is hidden — and would mean the client
had made the decision.

### Act 7 — remove the scratch connection

Sign back in as yourself. On `scratch-demo`, press **Remove…**, then
confirm. The row disappears and the removal is verified against the
store.

> 📸 **Screenshot 8** — the list back to five rows.

Optionally, show the CLI answering from the same API rather than the
database:

```bash
export CORE_TOKEN=$(curl -sS -X POST "http://127.0.0.1:8180/token" \
  -d grant_type=password -d username=<your-ops-user> -d password=<pw> |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
docker compose exec core node dist/cli.js sync systems list
```

It prints the same five rows with the same health. Note what it does
*not* need: a database URL.

---

## 5. Evidence

### Act 8 — extract it

```bash
cd ~/Desktop/DataProject
CL_TOKEN=$CORE_TOKEN CL_OUT=results/phase2/a3-b2 \
  results/phase2/a3-b2/extract-connections.sh "$(cat results/phase2/a3-b2/window-start.txt)"
```

Writes three files beside this page:

- `connections.txt` — every registered connection with its health, as
  the API served it to your identity.
- `test-jobs.txt` — every `test_connection` job in the window: which
  system, which outcome, and **which identity asked for it** (the job's
  trigger records the actor).
- `connections.json` — the same, machine-readable.

Then the audit chain for the window, which now carries PA-3's stamp
column:

```bash
CL_TOKEN=$CORE_TOKEN CL_OUT=results/phase2/a3-b2 \
  results/cp7-gate/extract-audit.sh "$(cat results/phase2/a3-b2/window-start.txt)"
```

Its closing summary prints **Setup stamps presented in the window** —
the D-108.4 column doing its job. For a browser-only demo this window
may hold no MCP rows at all; an empty chain here is a correct result,
not a missing artifact, and the stamp column is demonstrated instead by
any session you happen to run.

### Act 9 — write it up

Put the screenshots in `results/phase2/a3-b2/screens/` and write
`results/phase2/a3-b2/README.md`: what you did, what each screenshot
shows, and **every place the product failed to explain itself**. Use the
CP-8 field-note format:

```
N. [severity] What you expected → what happened → where
```

The friction notes are the half of this run no test can produce. If a
verdict was ambiguous, if a health reason was jargon, if you had to
guess what "unprobed" meant — that is the deliverable.

---

## 6. What would fail this gate

Say so plainly in the write-up if any of these happen:

- A connection you registered does not appear on re-read.
- A test reports **pass** for a capability the checks list as unprobed.
- Health reads green for a source with no accepted snapshot.
- A non-ops identity can write, test, or remove anything.
- A credential value appears anywhere on screen, in a URL, or in an
  error message.
- You needed a database shell to complete any act above.

Any one of them is a stop, not a note.
