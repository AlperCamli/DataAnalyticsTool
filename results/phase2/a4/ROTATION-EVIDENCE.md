# A-4 act 7 — rotation through the vault path, verified live

**2026-08-06, pilot estate.** The gate's fourth clause: *rotation of one
credential through the vault path verified live.*

## What was rotated

The Supabase **execution-role password** (`example_exec`) — chosen
because a governed execute is the thing that proves it end to end, and
because `reset-exec-password.sh` already existed to generate it.

## The sequence, and why each step is evidence

| # | Act | Result |
|---|---|---|
| 1 | `reset-exec-password.sh` generates a new password locally | writes `.secrets/env.sh` + the ALTER statement; prints neither |
| 2 | **Operator** applies the `ALTER ROLE` in Supabase as DBA | the old password dies at the source |
| 3 | Probe `supabase` **before** touching vault | `auth_error` on the `query` capability — health `red`, reason names the failed probe |
| 4 | `vault kv patch … exec_dsn=<new>` — **vault only** | round-trip byte-identical; `introspect_dsn` confirmed untouched |
| 5 | Probe `supabase` again | **green**, 3 checks, 0 unprobed |
| 6 | Governed execute over MCP (`validate_sql` → `execute_sql`) | **pass** / **OK**, 1 row |

**Step 3 is the load-bearing one.** It is not a formality: it proves the
runner was reading the execution DSN *out of vault*, because the value in
vault is precisely the one that had just been killed at the source. Had
the runner been resolving from a file, or caching, step 3 would have
succeeded and the whole rotation would have proved nothing.

## What did not happen

- **Nothing was restarted.** `core` started `08:10:42Z`, `runner`
  `08:05:16Z`, both `restarts 0` — before the rotation and unchanged
  after it. The new value was picked up on the next resolution, which is
  the contract the absent version pin buys (D-111.1).
- **No file was edited.** `git status` clean across the rotation.
- **No connection row was changed.** The `vault://` reference is the same
  string before and after; only the value behind it moved.

## Audit trail

The execute is recorded under the acting identity, not a service account:

```
2026-08-06T09:14:34  execute_sql   alper  steward  allowed
2026-08-06T09:14:33  validate_sql  alper  steward  allowed
```

Full rows in `rotation-audit.json`; connection state in
`connections.json` / `connections.txt`; window start in
`rotation-window.txt`.

## One incident during the run, recorded rather than tidied away

Between steps 1 and 2 the assisting session printed a **regex-masked**
copy of the ALTER statement so the operator could see it. The mask
matched across a comment boundary and left the password's tail visible in
the transcript. The password had not yet been applied to the estate, so
it was regenerated at zero cost and the leaked one was never valid
anywhere.

The rule it violated is the one this checkpoint exists to enforce, and it
is now explicit in the runbook: **do not mask a secret — do not print it
at all.** `pbcopy < .secrets/alter-exec-password.sql` was already the
right answer and the masked echo added nothing. Ten minutes later the
same mistake would have meant a second rotation under time pressure.
