# A-5 task 3 — the floor check: attempted, blocked, and why

**Verdict: NOT RUN.** Two blockers, both named, one of them a live defect on
the pilot deployment that stops far more than this check. Nothing below is
presented as gate evidence, because none of it is.

## What was attempted

A reporter journey on **RB-01** ("how many new users are signing up? I want
to watch new users over time") — chosen because it is the one seed request
whose report path is *already* through a `verified` doc
(`v_user_signups_by_day.md`) and whose metric
([`metrics/new-users.md`](https://github.com/AlperCamli/Sample-Knowladge-Base/pull/48))
is drafted. A reporter bundle was compiled into `~/cl-reporter` — the
customer-shaped environment, never the dev workspace (D-118.1) — and a
headless session was started against it.

The session reported, correctly and without inventing anything, that the
`contextlayer` server never finished connecting and that it therefore had
no tool to call.

## Blocker 1 — A5-F1: the deployment's public address is a DHCP lease that moved

The core is running with:

```
CORE_PUBLIC_URL=http://192.168.1.104:8100
CORE_OIDC_ISSUER=http://192.168.1.104:8180
```

This machine is now at **192.168.1.102** (`ipconfig getifaddr en0`), and
nothing answers on `.104`. Both values come from `CL_HOST_ADDR` at
`docker compose up` time (`docker-compose.yml:96`) and were burned in at the
last stack start.

**This is not only a session problem, and localhost does not route around
it.** The MCP endpoint answers a connection attempt with

```
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer resource_metadata="http://192.168.1.104:8100/.well-known/oauth-protected-resource"
```

and that document names `http://192.168.1.104:8180` as the authorization
server. A client connecting over `127.0.0.1` is therefore sent to an
unreachable host to authenticate, and cannot complete. The browser path is
the same: `/v1/auth/login` 302s to
`http://192.168.1.104:8180/authorize?…&redirect_uri=http%3A%2F%2F192.168.1.104%3A8100%2F…`.

**As of now, no session and no browser on this LAN can sign in to the pilot
deployment.** The dashboard, the MCP surface, and the setup-bundle download
are all behind that redirect.

**Fix (operator, one command, before anything else in A-5's STOP list):**

```bash
CL_HOST_ADDR=$(ipconfig getifaddr en0) make stack-pilot   # re-reads the current address
curl -s http://127.0.0.1:8100/healthz | grep public_url    # must show .102, not .104
```

Compiled bundles carry the URL they were compiled against, so **every bundle
compiled before the move is stale too** and must be re-downloaded (or
recompiled) after the restart.

*Why the session did not do this:* restarting the stack unattended is an act
on the operator's running deployment, with vault and the runner behind it. A
failed restart with nobody present is a worse outcome than a wrong address
with a known fix. It is one command and it is first on the STOP-1 list.

*Related, not the same:* **A4-F5** already recorded that a same-machine sign-in
fails when the issuer defaults to `host.docker.internal`, and A-2 closed
bundle *staleness* for **profile** changes. Neither covers this: the profile
did not change, the bundle did not go stale by the mechanism A-2 built, and
the value that moved was the deployment's own address. The bundle's stamp
detects a profile drifting; nothing detects the host drifting.

## Blocker 2 — the journey needs a human's sign-in, and the gate needs STOP-2

Even with the address corrected, this check is **the operator's to run**, for
two reasons that are both by design:

1. **A bundle carries no credential (PA-1).** MCP access is an OIDC
   authorization-code flow in a browser under the reporter's own identity.
   No session can perform it, and minting a token by another route would be
   demonstrating a path no real user takes — the exact failure D-118.1 exists
   to prevent. (There is a fixture deployment with bearer tokens; running the
   journey there would measure the fixture's KB, not this estate's floor, so
   it was not done.)
2. **The gate's own text is not satisfiable yet anyway.** It asks for trust
   notes "citing verified docs **and a certified metric**". The metrics
   catalogue is a **draft** in an unmerged PR (#48) and the report path's base
   docs are still `contaminated` pending the triage batches. Both are STOP
   items belonging to the operator. A run today would honestly report
   *draft* — which is the machinery behaving correctly, and is not the gate.

## What the path looks like today, statically — **not** gate evidence

Read directly from KB `main` (`6bea39d`) front-matter, so it says what the
trust blocks would say, without an artifact to prove it:

| RB-01's path | Status today | After STOP-1 / STOP-2 |
|---|---|---|
| `systems/supabase/reporting/v_user_signups_by_day.md` | **`verified`** (2026-08-05) | unchanged |
| `systems/supabase/public/users.md` | `contaminated` | `draft` → `verified` (triage batch 3) |
| `metrics/new-users.md` | **absent from `main`** — PR #48 open | `draft` → `verified` (STOP-2) |

So the honest reading of the floor as it stands: **one of the three legs is
already there.** The verified view is the one a reporter would be routed to
under RLS anyway, which is why RB-01 was the right journey to pick; the other
two legs are exactly the work A-5 has prepared and the operator has to land.

## The re-run, prepared

After the address fix, the triage batches and the metrics merge:

1. Sign in at `http://<current-ip>:8100/` as the reporter identity and
   download the bundle (Setup), or recompile:
   `node core/dist/cli.js compile reporter --kb ~/cl-steward/kb --url http://<current-ip>:8100 --out ~/cl-reporter`
2. `cd ~/cl-reporter`, start Claude Code, and paste:

```
Use the `report` skill for this request, end to end:

  "How many new users are signing up? I want to watch new users over time."

Window: June 2026 (2026-06-01 to 2026-06-30, UTC), daily buckets. Resolve it
through the knowledge base, validate the SQL, execute it, and produce the
report artifact.

When you are done, print the artifact's `trust_notes` block verbatim, and
say plainly whether any doc or metric on the path is draft, stale or
contaminated.
```

3. Save the artifact and its trust notes to `results/phase2/a5/floor-check/`.

**What closes the gate clause:** trust notes citing `v_user_signups_by_day`
and `users.md` as verified, citing `metrics/new-users` as a **certified**
metric, and **no draft-doc warning on the report path**. Anything less is
reported as what it is.
