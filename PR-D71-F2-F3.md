# D-71 points 1 & 2 — visibility governs execution (F2); dedicated introspection role (F3)

Closes security review #2 findings **F2** and **F3** per ruling D-71.
Nothing else from that review is touched: F4 stays deferred, F5/F6 stay
accepted, F7's register motion is unchanged, and points 3–8 are recorded
in the ruling rather than here.

> **Numbering.** The ruling arrived labelled *D-67*, which was already
> the security-review-**#1** landing record (also its F2/F3/F4). Both
> would have been "security review, findings F2/F3", so `D-67.1` would
> have resolved two ways. Renumbered to **D-71** on the owner's call —
> review #1 keeps D-67, since landed commits and code point at it.

## The spec diff leads

One additive amendment to `specs/mcp-tool-reference-spec.md`, which is
exactly what D-71.1 authorised:

- **§3** — strikes "for content tools" from the per-call decision.
  `visibility(roles, object)` now applies to every tool that names an
  object. Stated with the reason it is not merely tidiness: the pilot's
  only execute-granted profile is Steward at `visibility: ["**"]`, so the
  two surfaces coincide *today* and diverge the moment M3 gives a
  Reporter-class profile execute. It also keeps (b)'s obligation from the
  review — the database role must still be scoped no wider. The KB map is
  the gate; the database role is the wall; a wall is not replaced by a
  gate.
- **§6.6** — resolution runs against the caller's visible surface, with
  the consequences spelled out (including that callers are told an object
  "does not exist" when it does — that wording is the point).
- **§5** — the token carries an `objects` allow-set, re-checked at
  execute.
- **§9** — MT-11, MT-12, MT-13.

## F2 — how the non-disclosure property is actually held

The visible surface is the **input** to resolution, not a filter over its
output. `valsql.ts` builds the object list handed to `sqlval` from what
the caller can see, so a hidden table comes back through the same code
path with the same `unknown_object` finding as a table that never
existed. No second message to keep in sync; no branch that could leak
which case it was. Column resolution inherits it — a hidden object's
columns are hidden with it, so no column check can confirm its shape.

The true reason is recovered afterwards, server-side only, and goes to
the audit record (`decision: filtered`, `hidden_objects`) and nowhere
else.

**Which check catches a mid-token visibility change.** The allow-set
recheck, and only it. `snapshot_ref` pins the *facts* surface; visibility
lives in the KB at `kb_ref`, so a revocation moves no snapshot and a
token minted a moment earlier passes every other §5 binding cleanly.
MT-13 asserts the snapshot rows are unchanged across the case, so the
test cannot be satisfied by the pin instead. Refusal is `not_found` in
validation's words — holding a token must not become a way to learn an
object exists — and is deliberately built *without* `execute.ts`'s
`fail()` helper, which copies extras into the caller-visible `detail` as
well as the audit meta.

A token with no `objects` claim is refused rather than trusted; the 300 s
TTL bounds that to one re-validation.

**Tests** — `core/test/mcp-visibility.test.ts` (12). The load-bearing one
compares the hidden and absent responses field-by-field after normalising
the object name, rather than asserting a proxy for indistinguishability.
Mutation-checked: disabling the surface filter fails 6 of 12; disabling
the allow-set recheck fails MT-13 alone.

## F3 — `contextlayer_introspect`

`deploy/introspection-role.sql`: LOGIN + CONNECT + USAGE on the
introspected schemas, **no SELECT on anything**, none of the four role
attributes. Narrow-looking until the reason lands — the connector reads
`pg_catalog` only, which is world-readable and *not* privilege-filtered,
so the role reads the estate's full shape and none of its contents. That
same asymmetry is why the swap is snapshot-neutral.

`check_introspection_role` refuses SUPERUSER or BYPASSRLS at the start of
every **live** snapshot job — not ddl-file mode, whose container is ours
and needs the superuser the check would refuse.

**Measured, not assumed:** the pilot's `postgres` reports
`rolsuper = false`. Supabase's `postgres` is not a superuser; it holds
CREATEDB, CREATEROLE and **BYPASSRLS**. A check written to look only for
SUPERUSER — the obvious way to write it — would have passed the exact
connection F3 was filed about.

**Tests.** `tests/test_introspection_role_sql.py` (15) applies the real
file through `psql` (D-70) and holds it to both claims: introspection
through the role is byte-identical to introspection as the container
superuser on the same database; all four read paths raise
`InsufficientPrivilege`; the file's own VERIFY queries are parsed back
out of it and asserted empty. Separately, the connector's live-mode
fixtures now run through this role, which upgrades **C-3 mode
invariance** into direct evidence for the swap — ddl-file as superuser vs
live as a role with no table privileges, canonical bodies byte-identical.

**Config swap.** `env://SUPABASE_DSN` → `env://CL_INTROSPECT_DSN`. The
rename is the point: the old name said which *database* it reached while
the value behind it was the estate's BYPASSRLS role, so renaming forces a
new variable set to a new credential instead of the old one surviving
under a name that no longer describes it.

## Register motion — playbook deploy checklist (D-71.2)

**Not applied here.** The amendment fence authorised one MCP-spec change;
the playbook is a different spec, so this is proposed text for the owner
to rule on, per D-71 point 2's "playbook register motion".

Proposed: add to `customer-onboarding-playbook.md` §13 (Step 9 — readiness
gate), as gate items beside the existing P-H PAT item:

> 9. **Database role assertions, both connections.** For every SQL system
>    in the estate, both provisioning files have been applied by the
>    customer and both checks pass against the example estate:
>    - *Execution* — `deploy/execution-role.sql` applied; the executor's
>      startup check passes (no SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS,
>      no write grant reachable through role membership, no schema
>      CREATE). Evidence: a `preflight` against the configured
>      `execute_dsn` (G3).
>    - *Introspection* — `deploy/introspection-role.sql` applied; the
>      connector's live-job check passes (no SUPERUSER, no BYPASSRLS).
>      Evidence: one accepted live snapshot under the dedicated role,
>      byte-identical to the previous role's on unchanged source state.
>    - The two roles are **distinct identities with distinct passwords**,
>      and neither DSN is the estate's default `postgres`.
>    Verify by attribute, not by role name: a managed-Postgres `postgres`
>    role may report `rolsuper = false` and still hold BYPASSRLS (observed
>    on Supabase, D-71.2).

Sibling motion, same section, for the reviewer to consider: the gate
currently has no item asserting that a profile granting `execute_sql` is
paired with a database role scoped no wider than that profile's
visibility. F2 makes the KB map a gate over execution, but the pairing is
still what makes the wall match the gate. Filing it rather than drafting
it, since it needs a ruling on how mechanically it can be checked.

## Not done — the live swap is an operator step

Applying `introspection-role.sql` is DDL against the customer estate and
is theirs to run, never ours. The pilot is wired and **fails closed**
today, verified end-to-end through the real CLI:

```
job local-…: FAILED config_error (non-retryable) — introspection role
'postgres' holds BYPASSRLS; introspection reads pg_catalog and requires
neither (D-71.2). Provision the dedicated role with
deploy/introspection-role.sql and point config.dsn/dsn_env at it.
Refusing to introspect.
```

To finish (D-71 point 8(c), already an M2 sign-off condition):

1. Customer runs `deploy/introspection-role.sql` in the Supabase SQL
   editor.
2. Repoint `CL_INTROSPECT_DSN` at `contextlayer_introspect`.
3. Re-pull and confirm `canonical_body_sha256` is unchanged against the
   recorded baseline `6fcfc976ce104e33ca56a16670d78e57ab44950bdf6ee4b106dad8c20ce3463c`
   (29 objects, last pull under `postgres`, 2026-07-20T21:24:54Z). A
   *different* hash means the swap changed what we can see — investigate,
   do not accept.

Steps and baseline are recorded in `.secrets/connections.md`.

## Suites

Python 486 passed / 13 skipped · core 140 passed across 14 files (MT, FL,
SO, drill, JP-2) · `tsc --noEmit` clean.
