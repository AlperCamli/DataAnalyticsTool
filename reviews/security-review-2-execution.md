# Security Review #2 — Governed Execution (CP-6 task 6.6)

Status: **review of landed M2 code**, plus two proposals. One finding was fixed during the review
(F1, audit completeness — it was a defect in code this review covers, not a design question); the
rest are tagged **accept**, **amend** (needs a ruling / register motion), or **defer**.

Scope per plan task 6.6: the execution path, identity propagation, guardrail bypass surface, audit
completeness. Method: adversarial read of `core/src/execute.ts`, `core/src/mcp.ts`,
`connectors/postgres/executor.py`, `connectors/sdk/providers.py`, `connectors/sdk/service.py`
against the MCP, capability, and job specs; plus live probing against the pilot Supabase and
fuzzing of the identity-tagging path.

Severity: **High** (fix before the surface goes live), **Medium** (before it is load-bearing),
**Low/Info** (hardening; trigger-watched).

---

## What is sound (verified, not asserted)

- **Token enforcement (G4/MCP-R5).** Every §5 binding is checked in one place (`vtoken.ts`), which
  is the same module that issues — enforcement cannot drift from issuance. Missing, tampered,
  forged-signature, re-signed-payload, expired, foreign-subject, and stale-snapshot tokens all
  return `revalidate_required`, and each case is asserted to enqueue **no job**
  (`core/test/mcp-execute.test.ts`). Verification precedes every side effect in `executeRequest`.
- **Guardrail flooring (G2/CC-3).** `Guardrails.parse` was probed with forged, negative, string,
  boolean, null, list, and scalar envelopes; every one yields the conservative default or the
  ceiling, never a widened limit. `statement_class` is never read from the payload at all, so a
  forged value cannot unlock DML. Confirmed by direct probe, not by reading the code.
- **Comment-tag injection (QE-2).** Fuzzed 200,000 random identities over the full printable ASCII
  range plus NUL, newline and backslash: **zero** escapes. `*/`, `/*`, `%`, newline and NUL cannot
  appear in the emitted tag, so the comment cannot be closed early and no psycopg placeholder can be
  smuggled through a subject or session id. The tag remains exactly one well-formed comment.
- **The role wall (G3).** Verified live: the pilot execution role holds zero write grants reachable
  through role membership, `public` is its only schema with USAGE, and it has none of
  SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS. Writes driven straight at the driver — past every parser
  we own — are refused. The check runs at startup *and* before every query, so a grant change under
  a long-lived runner cannot go unnoticed.
- **Credential scoping.** Execute jobs receive only credentials marked `required_for: ["query"]` and
  fail closed otherwise, keeping the introspection DSN off the execution path.
- **Rate limiting.** `execute_sql` maps to the `execute` category (6/min per identity, §7).
- **Audit on failure.** A tool that throws is caught, converted to an error outcome, and still
  audited with its true decision — the audit does not have a hole where crashes happen.

---

## F1 — Audit lost parameter values (Medium) — **fixed in this review**

**Finding.** `execute_sql` accepts `request.params`, and parameterized statements validate and
execute normally. The audit stored `request.statement` alone, so a call that ran
`... WHERE tenant_id = %s` with `["acme"]` was recorded as the template with no record of which
tenant was read. The validation token binds `statement_sha256` only, so one token legitimately
authorizes many executions with different values across its 300 s life — meaning the audit was not
merely incomplete, it could not distinguish those executions from each other at all.

This is squarely in this review's scope ("audit completeness") and is a defect against MCP §8, which
requires full statement text for execute. An audit that records the shape of a query but not the
data it selected looks complete while answering none of the questions an audit exists to answer.

**Fixed.** `auditText()` in `core/src/execute.ts` appends canonical-JSON parameters to the audited
text when present. Regression test in `core/test/execute-e2e.test.ts` asserts the executed value
appears in `audit_records.statement_text`. Parameters may contain customer values — consistent with
the statement text already carrying literals for unparameterized queries, and the audit table is
already the restricted deep store (L-8).

**Not changed:** the token still binds the statement only, per §5. Values cannot change which
objects a statement touches, and the driver binds rather than interpolates them, so the token's
authority is intact. Widening the hash to cover params would redefine `statement_sha256` and is an
amendment, not a fix.

---

## F2 — The visibility map does not reach the execution path (High, **amend**)

**Finding.** M-4 visibility is applied to every content tool (`get_entity`, `get_table`,
`get_metric`, `get_lineage`, `search_context`, `report_freshness`) and to the ledger reads. It is
applied to **neither `validate_sql` nor `execute_sql`**: `valsql.ts` resolves against all snapshot
objects, and `execute.ts` performs no visibility check. A caller whose role hides `reporting.**` in
the KB can therefore validate and execute SQL that reads those tables directly, provided their
profile grants execute for that system.

**This is arguably per spec**, which is why it is tagged *amend* rather than *accept*: MCP §3 defines
the per-call decision as `tool ∈ allow ∧ qualifiers match ∧ visibility(roles, object) **for content
tools**`. Execution access is governed by the profile grant and the database role, and the KB
visibility map is described as a documentation-surface control. Under that reading the current
behavior is correct and the gap is in what the spec chose to guard.

**Why it needs a ruling now rather than later.** It is not exploitable in the pilot today: only the
Steward profile grants `execute_sql`, and Steward's visibility is `["**"]`. It becomes live at
**M3**, whose stated demo is "a real non-analyst pilot user, **Reporter profile**, takes one seed
request through resolution → validation → execution" (plan §6.3). The moment a Reporter-class
profile gains execute, the KB visibility map and the executable surface diverge — and a user who
cannot *read about* a table can *read from* it. That divergence is the kind of thing that is cheap
to decide now and expensive to discover in a pilot review.

**Proposal (register motion, not built here).** Either:

  (a) extend §3 so `validate_sql`/`execute_sql` resolve object references against the caller's
      visibility scopes, refusing hidden objects the way MT-8 refuses undocumented ones — the KB
      map becomes the single access surface; or
  (b) state explicitly that visibility is a documentation control only, that the database role is
      the data-access control, and require that any profile granting execute be paired with a
      database role scoped to the same objects — making the pairing a documented deployment
      obligation rather than an accident.

(a) is the smaller surprise for an operator reading `roles.yaml`. (b) is more honest about where
enforcement actually lives and avoids implying the KB can contain a determined caller. **Recommend
(a)**, with (b)'s pairing obligation documented regardless. Either way it is a spec amendment and
belongs in the register before CP-7 builds the Reporter journey.

---

## F3 — Introspection runs as a superuser-class role (Medium, **accept**)

**Finding.** G3 scoped the *execution* role because that is the path an agent drives. The
*introspection* connection on the example estate authenticates as `postgres`, which holds CREATEDB,
CREATEROLE and **BYPASSRLS**. Introspection reads catalogs; it needs none of these. BYPASSRLS in
particular means that connection sees through row level security, so any future capability reading
row data over that connection (usage mining, `pg_stat_statements`, sampling) would silently
bypass RLS.

No current code path reads customer row data over the introspection connection — the postgres
connector reads catalogs only, and UP-1 keeps usage mining source-side — so this is latent, not
active.

**Proposal.** A dedicated least-privilege introspection role (`CONNECT`, `USAGE` on the introspected
schemas, `SELECT` on catalogs; none of the role attributes), provisioned by a
`deploy/introspection-role.sql` given the same treatment as the execution role — including a test
that runs the file (D-70). Outside the M2 fence; recommended before CP-7.

---

## F4 — Over-cap single rows are bounded late (Low, **defer**)

The row cap bounds row *count*, not bytes. A result of `row_cap` very wide rows is bounded in the
executor only by count; the 64 MB delivery cap (JP-3) catches it at the core boundary, where the
runner's `complete` gets a 413 and the job then dead-letters via lease expiry rather than promptly.
The waiting caller therefore sees a slow `upstream_error` instead of a crisp guardrail.

Not a data-exposure issue and not reachable accidentally at pilot shapes. **Defer**, with the
trigger being the first legitimate wide-result complaint; the fix would be a byte budget accumulated
during streaming alongside the row count, surfacing as `row_cap`.

---

## F5 — Token replay within its TTL (Info, **accept**)

A validation token is not single-use: within its 300 s life the same token may execute the same
statement repeatedly (with differing params, per F1). This is intended — §5 describes expiry and
re-validation as cheap, not tokens as nonces — and is bounded by the 6/min execute rate limit. Each
execution is independently audited. No change recommended; recorded so it is a decision rather than
an assumption.

---

## F6 — `$1` placeholders validate but fail at execute (Info, **accept**)

`sqlglot` parses both `%s` and `$1` placeholder styles, so a statement using Postgres-native `$1`
passes validation and is issued a token, then fails at execute with psycopg's
`the query has 0 placeholders but 1 parameters were passed`. A confusing but safe failure: it is a
terminal error surfaced to the caller, not a bypass. Worth a line in the skill guidance when the
`report` skill starts emitting parameterized SQL (CP-5).

---

## Register motions this review raises

| # | Motion | Home spec | Recommendation |
|---|---|---|---|
| F2 | Does visibility govern validate/execute, or only content tools? | MCP §3 | Amend — decide before CP-7 builds the Reporter execution journey |
| F3 | Least-privilege introspection role | onboarding playbook / deploy | Accept — build before CP-7 |
| F4 | Byte budget alongside the row cap | capability §6 (CI-A neighbourhood) | Defer — trigger-watched |
