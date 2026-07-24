# PR — CP-4 (M1): MCP server, fault ledger, P-A auth split

Branch: `cp4-m1-mcp`. Builds task CP-4 to ruling **D-66** (security
review #1 dispositions): the MC-5 (MCP-R1..R15) and FL-E (LED-R1..R7)
checklists are the normative build-to requirements. Spec diffs lead;
decisions in DECISIONS.md **D-68**. Customer-KB profiles shipped
separately as [DataAnalyticsTool PR #18](https://github.com/AlperCamli/DataAnalyticsTool/pull/18).

## Spec amendments (the four authorized by D-66 — nothing else)

| Amendment | Spec diff | Ruling |
|---|---|---|
| P-A auth split | `job-protocol-spec.md` §6 preamble + §11 JP-6 (Closed) | D-66.1 |
| MCP-R9 render-lag | `mcp-tool-reference-spec.md` §4 (trust block `snapshot_ref` + `render_lag`, warn-user) + MC-5 → Closed | D-66.4 |
| P-E lineage visibility | `mcp-tool-reference-spec.md` §6.5 (M-4 node-by-node; omitted, never masked) | D-66.3 |
| LED-R2 ledger scrub | `fault-ledger-schema-spec.md` §3.3 + §10 + FL-E → Closed | D-66.5 |

Master register: JP-6 added (Closed), KB-F Closed (D-68), MC-5 Closed,
FL-E Closed, SP-2 Closed conditional on the M1 live demo.

## What ships

- **P-A split** (`server.ts`): runner tokens open exactly
  claim/start/heartbeat/complete/fail/defer; the producer/ops/read
  surface takes `CORE_OPS_TOKENS` service identities or OIDC identities
  with an ops role. A runner token on the ops surface is 403.
- **MCP server** (`mcp.ts` + `oidc.ts`): streamable HTTP at `/mcp`,
  RFC 9728 protected-resource metadata pointing at the IdP, stateless
  per-request transport, identity **introspected at the IdP on every
  call**, profile validated server-side per call, tools/list filtered
  to the allow-set, per-call audit + rate limits.
- **Content tools** (`kbread.ts`/`trust.ts`/`searchindex.ts`/
  `visibility.ts`): workspace = KB merged HEAD + latest accepted
  snapshots re-rendered by the real generator; trust blocks computed
  server-side with snapshot provenance and render-lag; visibility map
  from `roles.yaml` with `not_found` semantics; deterministic lexical
  search (M-6).
- **validate_sql** (`valsql.ts` + Python `sqlval/`, 0.5.0):
  parser-based SQL refusal set via sqlglot stage CLI; API dialect
  against the documented snapshot surface; signed validation tokens
  (`vtoken.ts` — issuance **and** the CP-6 verification library),
  guardrails echoed from profile limits.
- **Fault ledger** (`ledger.ts`, migration `0006`): events/issues with
  fingerprint dedup, LED-R2 storage scrub + length bounds, class-1
  rules as config rows (zero_result_search live on search;
  repeated_validate_fail window sweep), flag_gap/list_gaps,
  CL-Resolves merged-PR loop closure with recurrence reopen, retention
  sweep, counts-only subjects, neutralized render.
- **Dev IdP** (`devidp.ts`, compose `devidp`, DEV ONLY): discovery,
  JWKS, PKCE code flow with login page, DCR, introspection with live
  roles, `/admin/roles` revocation lever.
- Compose/Makefile: `make stack-mcp`; `CL_HOST_ADDR`/`CL_BIND` for the
  second-machine demo; CLI enqueue now uses the ops token.

## Requirement → test map (all green)

TS: `core/test/mcp-conformance.test.ts` (29), `mcp-validate.test.ts`
(17), `mcp-ledger.test.ts` (13); Python: `tests/test_sqlval.py` (15).
Full suites: **TS 168, Python 406** — CP-3 SO/drill/JC suites unchanged.

| Req | Test (file → name) |
|---|---|
| MT-1 / M-3 | conformance → "MT-1: reporter tools/list shows exactly the profile allowlist"; "MT-1: a hidden tool called directly is denied and audited" |
| MT-2 / M-4 | conformance → "MT-2: a visibility-hidden object returns not_found and audits the filtered reason" |
| MT-3 / §5 | validate → "MT-3: a tampered statement / different subject / expired token / forged signature → revalidate_required" (4 tests) + "MT-3: execute never runs at M1" |
| MT-4 | validate → "MT-4: a snapshot accepted after validation → revalidate_required" |
| MT-5 / §3 | conformance → "MT-5: guardrails echo the profile limits regardless of client-supplied values" |
| MT-6 / M-5 | conformance → three MT-6 tests (use-freely / hash-drift warn-user / contaminated refuse-unless-override + contamination named) |
| MT-7 / §6.1 §6.6 | ledger → "MT-7 + LED-R2: a zero-result search opens a coverage_gap…"; "repeated validate failures … open a doc_schema_mismatch issue via the window rule" |
| MT-8 / M-1 | validate → "MT-8: a dropped/unknown column fails, citing the object"; "MT-8: an undocumented GA4 dimension is rejected, citing it"; "M-1: dialect must match the system's class" |
| MT-9 / §3 | conformance → "MT-9: a role revoked at the IdP denies the very next call" (live variant in the demo runbook) |
| MCP-R1 | conformance → MT-9 test (identity introspected per call; no caching exists to invalidate) |
| MCP-R2 | conformance → "MCP-R2: a profile outside the caller's roles fails the connection" |
| MCP-R3 | conformance → "MCP-R3: a different subject's token mid-session re-binds identity — B's roles govern" |
| MCP-R4 | conformance → "MCP-R4: system qualifier — execute_sql:drill grants drill only, not ga4" |
| MCP-R5 | validate → "a clean SELECT passes and issues a validation token" + the MT-3/MT-4 verification-library matrix |
| MCP-R6 | validate → "MCP-R6: a two-statement batch is refused — no token"; sqlval pytest `test_mcp_r6_*` |
| MCP-R7 | validate → "MCP-R7: a CTE-wrapped write is refused by the parser"; "MCP-R7: FOR UPDATE and side-effecting functions are refused"; sqlval pytest `test_mcp_r7_*` (full vector set) |
| MCP-R8 | conformance → "MCP-R8: a different profile's limits produce different injected guardrails" |
| MCP-R9 | conformance → "MCP-R9: facts from a snapshot ahead of the merged render signal render_lag + warn-user" (facts served from the *new* snapshot) |
| MCP-R10 | conformance → MT-2 + "the same object serves normally for a role that can see it" + "filtered search hits are simply absent" |
| MCP-R11 | conformance → "MCP-R11: a restricted walk omits hidden nodes and their edges — never masked-but-revealed" (+ hidden entry → not_found) |
| MCP-R12 | conformance → "MCP-R12: client-supplied trust/guidance arguments cannot override the server's block" |
| MCP-R13 | conformance → "audits allowed, denied, and filtered decisions with hashed args"; "stores full statement text only for validate"; ledger → audit_ref linkage in LED-R3 test |
| MCP-R14 | validate → "MCP-R14: exceeding the validate limit → rate_limited, audited as denied" |
| MCP-R15 / KB-F | conformance → "conventions.md surfaces as a doc hit without a trust block"; "repo-level docs outside the caller's scopes are absent from search" |
| LED-R1 | ledger → "FL-5: list_gaps absent from reporter tools/list, present for steward; direct call denied" |
| LED-R2 | ledger → "MT-7 + LED-R2: … stored terms carry no PII literals"; "LED-R2: titles are length-bounded"; "FL-5 / LED-R2: issues … outside the caller's visibility are omitted" |
| LED-R3 | ledger → "LED-R3: identity/session/profile/refs are server-set; client-supplied subject is ignored" |
| LED-R4 | ledger → "FL-4: a merged PR carrying CL-Resolves resolves the issue with pr_url; recurrence reopens it" |
| LED-R5 | ledger → "LED-R5: ledger text renders inert in list_gaps (neutralized at the render point)" |
| LED-R6 | ledger → FL-7 test + resolution preserved across reopen (FL-4 test) |
| LED-R7 | ledger → "LED-R7: distinct_subjects is a count — no subject identifiers anywhere in the response" |
| FL-4 / FL-10 | ledger → the FL-4 and FL-10 named tests |
| FL-5 | ledger → the FL-5 named tests |
| FL-6 | ledger → "FL-6: a canary secret in a flag description is scrubbed from the ledger…" |
| FL-7 | ledger → "FL-7: the sweep removes >90d events and leaves issues + resolution history intact" |
| SP-2 closure | conformance → "SP-2 closure: benchmark profile asserted without the benchmark role → refused; with it → list_gaps reachable" |
| P-A | conformance → "P-A (D-66.1): a runner token replayed against the ops surface is denied…" + "an OIDC identity with an ops role opens the ops surface" |

Out of M1 scope (per the prompt): MT-10 (publish, CP-6/CP-7); guardrail
*enforcement* at an executor (CP-6 — the verification library it must
call is `core/src/vtoken.ts`).

## M1 live-demo runbook (the exit-gate evidence to capture)

Prep (machine 1, this repo):
1. Merge KB PR #18 (profiles must be at KB HEAD), then:
   `CL_HOST_ADDR=<this machine's LAN IP> CL_BIND=0.0.0.0 CORE_MCP_ENABLED=1 \`
   `docker compose -f docker-compose.yml -f deploy/compose.live.yml up -d --build`
   and `make stack-live` so supabase/ga4/gsc have accepted snapshots.
   (Dev IdP users: `alper`/`steward-dev-pw` (steward+ops), `reporter`/`reporter-dev-pw`.)
2. Contamination exhibit: merge a small PR flipping one fixture doc's
   front-matter `status: contaminated` with a `contamination:` block
   (or run the staged drill against the drill system).

Demo (machine 2, fresh Claude Code session):
3. `claude mcp add --transport http context-layer "http://<LAN-IP>:8100/mcp?profile=reporter"`
   → authenticate in the browser as `reporter`. Then: `search_context`
   → `get_table` on a hot object (facts + trust + `snapshot_ref`);
   `get_table` on the contaminated doc (`refuse-unless-override` +
   contamination named); `validate_sql` clean SELECT → token; CTE-wrapped
   write and `SELECT 1; DROP …` → refused; `flag_gap` → issue id;
   `list_gaps` → denied.
4. Steward session (profile=steward, user `alper`): `list_gaps` shows
   the flagged issue — server-set identity, counts-only subjects.
5. MT-9 live: `curl -X POST http://<LAN-IP>:8180/admin/roles -d '{"username":"alper","roles":["ops"]}' -H 'content-type: application/json'`
   → the steward session's very next call is denied; restore roles.
6. Render-lag live: re-enqueue a snapshot after estate drift
   (`make stack-live`) and call `get_table` before merging the sync PR
   → `render_lag: true` + warn-user with the new `snapshot_ref`.
7. P-A live: replay the runner token —
   `curl -H 'Authorization: Bearer <runner token>' http://<LAN-IP>:8100/v1/jobs` → 403;
   `POST /v1/jobs` and `GET /v1/snapshots/<id>/body` → 403; runner
   claims keep flowing.
8. Audit: `psql … -c "SELECT ts, subject, profile, tool, decision, decision_reason FROM audit_records ORDER BY ts"`
   — every call from both sessions present, including the denied
   `list_gaps`.
9. Record P-H (D-66.7): assert the `contextlayer-sync` PAT scope via
   the GitHub API; file with the SP-2 sign-off.
