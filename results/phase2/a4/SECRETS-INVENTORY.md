# `.secrets/` after A-4 — what remains and why

**State at 2026-08-06, after the migration.** Every credential the
platform reads at runtime now lives in vault. What is left on disk is
listed below with the reason it cannot move, because a platform claiming
zero credential files is lying about where it kept one.

## The bootstrap remainder — irreducible

| File | Why it cannot live in vault |
|---|---|
| `.secrets/vault-core.env` | the `cl-core` AppRole `role_id`/`secret_id`. This is the credential that **opens** vault; vault cannot hold it |
| `.secrets/vault-runner.env` | the same for `cl-runner`, under a different policy. Two files, not one, because a shared file would hand the runner the core's read of the KB git token |

That is the whole of it: `VAULT_ADDR` (in the committed
`deploy/vault-dev.env`) plus one AppRole pair per identity.

## No longer a secrets file

| File | State |
|---|---|
| `.secrets/sync.env` | **config, not secrets.** `SYNC_GIT_TOKEN` is now `vault://secret/contextlayer/core#git_token`; what remains is `SYNC_ENABLED`, the KB remote, provider and branch. Could move into git as-is |
| `.secrets/runner.env` | **deleted.** Every reference it served is `vault://` |

## Remaining files that are not runtime credentials

| File | What it is | Disposition |
|---|---|---|
| `.secrets/idp-users.json` | real people's dev-IdP accounts (the pilot's stand-in for a customer IdP) | stays until the pilot points at a real IdP; a customer deployment has no such file |
| `.secrets/env.sh` | operator shell helper; still holds `CL_EXEC_DSN` | **owed:** now redundant — vault holds this value. Clear it |
| `.secrets/alter-exec-password.sql` | the rotation statement, applied 2026-08-06; contains the new password | **owed:** delete, its own header says to |
| `.secrets/gsc-sa-key.json` | service-account key file | **owed:** check — vault holds this value at `connections/google#sa_key_json` |
| `.secrets/powerbi.env` | Power BI settings | **owed:** check for a live `POWERBI_CLIENT_SECRET`; vault holds it |
| `.secrets/*-live.json` | connector config shapes (property ids, site urls) | not credentials; keep |
| `.secrets/wire-*.sh`, `reset-exec-password.sh`, `connections.md` | operator provisioning helpers and notes | keep; **check each for an embedded value** |
| `.secrets/core-live/` | live job specs mounted into the core | not credentials; keep |

**The four "owed" rows are honest debt, not a finished inventory.** Each
holds a copy of a value vault now owns, and each should be emptied. They
are listed rather than quietly omitted because the gate asks what remains
and why — and "a helper script still has a password in it" is a true
answer that a clean-looking checklist would have hidden.

## Verified end state

With `.secrets/runner.env` deleted and `resolver.allow_env: false`:

- the runner holds **no** plaintext credential in its environment
  (`CL_INTROSPECT_DSN`, `CL_EXEC_DSN`, `GOOGLE_SA_KEY_JSON`,
  `POWERBI_CLIENT_SECRET` all absent)
- the G3 execution preflight passes, resolving its DSN from vault (A4-F6)
- all five connections probe `succeeded`
- a governed execute (`validate_sql` → `execute_sql`) returns rows
- `env://` resolutions since restart: **0**

## Still owed by the operator

1. **Unseal key + root token rotation.** Both passed through a chat
   transcript during this run. `vault operator rekey` and revoking the
   initial root token are standard hygiene regardless, and must be run
   by the operator so the new key never enters a transcript. A rekey was
   started during the run and **cancelled** rather than completed for
   exactly that reason — vault is in a clean, un-rekeyed state.
2. **The four "owed" rows above.**
