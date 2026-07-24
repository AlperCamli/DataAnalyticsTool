---
name: onboard
description: Step-by-step customer onboarding — wire real Supabase/GA4/GSC connections, pull live snapshots, verify conformance, and render the KB. Use when the user wants to connect a new customer estate, add a system to an existing one, or re-run the live pipeline.
---

# Onboarding a customer estate (technical wiring)

This skill covers the *technical* slice of onboarding: credentials →
live snapshots → verified KB. The full customer process (agreements,
seed reports, steward roles) is `specs/customer-onboarding-playbook.md`;
this skill is its steps "wire connections" through "KB renders".

Work **one system at a time**, and show the user each result before
moving on. A completed example of this whole flow exists:
`.secrets/connections.md` (example-estate.com — git-ignored, local only).

## Step 0 — Preconditions

- Repo venv: `.venv/bin/python` (never bare `python`).
- `.secrets/` exists, is in `.gitignore`, and `git check-ignore .secrets/x`
  confirms it. If missing: `mkdir .secrets && chmod 700 .secrets`, add
  `.secrets/` to `.gitignore`, commit **only** the `.gitignore` line.
- Hard rules while onboarding: never commit, echo, or paste credentials
  into output, configs under version control, fixtures, or error text
  (JC-8). Configs carry *references* (`dsn_env`, `credentials_file`,
  `credentials_env`) — never inline key material outside `.secrets/`.

## Step 1 — Collect what each system needs (ask the user)

| System | Ask for | Notes |
|---|---|---|
| supabase / postgres | Connection string (Supabase: Dashboard → Connect → Session pooler URI) | Password may need percent-encoding (`@` → `%40`). Session pooler (port 5432) works for catalog introspection. Read-only role preferred; `postgres` works. |
| ga4 | Numeric property id + a Google service-account JSON key | The SA email must be granted **Viewer** in GA4 Admin → Property Access Management. One SA can serve GA4 + GSC. |
| gsc | `siteUrl` (usually `sc-domain:<domain>`) + the same/another SA key | The SA email must be added as a user on the Search Console property. `siteRestrictedUser` suffices for metadata. |

## Step 2 — Stage `.secrets/`

Create (or extend) these files, `chmod 600` each:

- `sa-key.json` — the service-account key, verbatim.
- `env.sh` — `export CL_INTROSPECT_DSN='postgresql://…'`
- `supabase-live.json` —
  `{"system":"supabase","mode":"live","dsn_env":"CL_INTROSPECT_DSN","schemas":["public"]}`
  — **always scope `schemas`**: without it, Supabase-internal
  `auth`/`storage`/`realtime` schemas flood the KB. Ask which schemas
  hold the customer's estate; `["public"]` is the usual answer.
  — the DSN must be the **`contextlayer_introspect` role**, not the
  estate's `postgres` (D-71.2). Have the customer run
  `deploy/introspection-role.sql` first; the connector refuses to
  introspect over a SUPERUSER or BYPASSRLS connection and the snapshot
  job will fail closed if you point this at `postgres`. Note Supabase's
  `postgres` is *not* SUPERUSER but *does* hold BYPASSRLS — it is the
  second half of the check that catches it.
- `ga4-live.json` —
  `{"system":"ga4","mode":"api","property_id":"<id>","credentials_file":"<abs path to sa-key.json>"}`
- `gsc-live.json` —
  `{"system":"gsc","mode":"api","site_url":"sc-domain:<domain>","credentials_file":"<abs path>"}`
- `connections.md` — status table (system → what's connected → where),
  the runbook (steps 3–5 below as commands), and security notes
  (rotation expectation, JC-8). Keep it current as systems land: it is
  the file future sessions read first.

## Step 3 — Pull, one system at a time

```bash
source .secrets/env.sh   # only needed for supabase
.venv/bin/python -m connectors.sdk.local connectors.postgres.connector \
    --config .secrets/supabase-live.json --out ~/Desktop/kb-snapshots/supabase.json
.venv/bin/python -m connectors.sdk.local connectors.ga4.connector \
    --config .secrets/ga4-live.json --out ~/Desktop/kb-snapshots/ga4.json
.venv/bin/python -m connectors.sdk.local connectors.gsc.connector \
    --config .secrets/gsc-live.json --out ~/Desktop/kb-snapshots/gsc.json
```

Exit codes: `0` ok · `1` failed (no file written — S-6) · `2` usage ·
`3` deferred (quota; retry after the printed `retry_after_s`).

Failure triage (messages are credential-free by design):

| Symptom | Meaning | Fix |
|---|---|---|
| `auth_error` (401/403) | Key invalid, or SA not granted on the property | Re-check grant; GA4 Viewer / GSC user addition can take a minute to propagate |
| `config_error` (400/404) | Wrong property id / site_url / malformed DSN | Verify identifiers; GSC domain properties need the `sc-domain:` prefix |
| `source_unavailable` | Network/5xx, unverified GSC property, or GA4 torn read | Retryable; if GSC, confirm the property is verified |
| psycopg connect error | DSN host/password wrong | Rebuild DSN from the dashboard; mind percent-encoding |

## Step 4 — Conformance before rendering

For each new system, pull **twice** and check C-2 (idempotency at the
source), then validate:

```bash
.venv/bin/python -m snapshot.validate ~/Desktop/kb-snapshots/<sys>.json
.venv/bin/python - <<'EOF'
import json
from snapshot.canonical import canonical_body_bytes
a = json.load(open("run1.json")); b = json.load(open("run2.json"))
assert canonical_body_bytes(a) == canonical_body_bytes(b), "C-2 FAILED"
EOF
```

Delete the second run file afterwards. If C-2 fails, the source changed
mid-onboarding (rerun) or a connector bug exists (stop, investigate —
that is a release blocker, snapshot spec §9).

## Step 5 — Render and verify the KB

```bash
.venv/bin/python -m generator.render ~/Desktop/kb-snapshots/*.json --out ~/Desktop/kb
.venv/bin/python -m generator.validate ~/Desktop/kb \
    --snapshot ~/Desktop/kb-snapshots/<each>.json      # expect: 0 findings
```

- Convention in this deployment: the user reviews the KB at
  `~/Desktop/kb`; snapshots live at `~/Desktop/kb-snapshots/`.
- Re-running render must print `written 0` (KB-8). If it doesn't with
  unchanged snapshots, stop — generator bug.
- **Adding a system later:** the root `index.md` is bootstrapped once
  and then human-owned (K-7), so a new system won't appear on it. If —
  and only if — the user has not edited it, delete `kb/index.md` before
  rendering to re-arm the bootstrap; otherwise ask them to add the link.

## Step 6 — Close out

- Update `.secrets/connections.md`: mark the system connected, record
  estate shape (object counts, property facts) and any flags.
- Tell the user what to expect in the KB, including the known
  non-surprises: descriptions render `—` wherever the source carries no
  comments/metadata (semantics arrive with the enrich pass, task 1.7);
  GA4's standard surface is huge (hundreds of dimensions — rendered as
  one group file per kind, KB-E ruling: no split in v1); GSC is a fixed
  10-object schema with null descriptions by design (D-30/D-35).
- Remind the user: credentials shared over chat count as exposed —
  rotate DB password and SA keys when the pilot phase ends.
- Pushing the KB into a customer git repo with KB CI is task 1.6, not
  this skill.
