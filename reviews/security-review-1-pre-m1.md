# Security Review #1 — Pre-M1 (CP-4 task 4.6)

Status: **review only** — findings and proposals. No code or spec changed (HLR §11 amendment
fence in force). Every recommendation is tagged **accept** (build/fix as stated), **amend** (needs a
ruling / register motion before build), or **defer** (accept the current state, watch a trigger).
Register closures this feeds: **SP-2, MC-5, FL-E** (plan §5, register calendar §10).

Method: read the landed CP-3a/3b core (`core/src/*.ts`, `core/migrations/*`) and the runner SDK
(`connectors/sdk/*.py`) against the job, sync, capability, MCP and ledger specs; the MCP server and
ledger are **not built yet** (CP-4), so Parts 2 and 3 are design reviews against spec producing
testable requirements the CP-4 prompt must build to.

Severity scale: **High** (fix/decide before or during CP-4), **Medium** (before the surface it
guards is load-bearing — pilot), **Low/Info** (hardening; trigger-watched).

---

## Part 1 — SP-2: review of landed CP-3a/3b code

### What is already sound (cited, not re-litigated)

- **Webhook secret lifecycle** — `randomBytes(32)` (256-bit) generated in the admin CLI, only its
  `sha256` stored (`sync_hooks.secret_hash`), printed exactly once, compared constant-time
  (`timingSafeEqual`), rotation is a row update read per-request (no restart). Clean; matches SY-2 /
  ruling E2. `cli.ts:194`, `triggers.ts:132`, `server.ts:385`.
- **PAT handling** — the `contextlayer-sync` token is injected per git invocation via
  `GIT_CONFIG_*` → `http.extraheader`, never in argv, `.git/config`, the remote URL, or reflog;
  provider REST uses it as a Bearer header only. Git error strings echo argv (URL, no token) and run
  records store no token. Matches ruling D2. `gitkb.ts:27`.
- **Credential references (J-4)** — job payloads carry `env://NAME` / `vault://` references only;
  resolution is runner-side under the runner's vault identity; `sync_systems.payload` and the queue
  store references, never secrets. `vault.py`, `queue.ts` (payload stored verbatim as references).
- **Runner-token compare** — `sha256` + `timingSafeEqual` over the full token set with **no early
  break**, so match-position timing does not leak. `server.ts:100-127`.
- **Snapshot system-binding on delivery** — a delivered snapshot whose `system` ≠ the job's system
  is rejected before storage, blocking cross-system substitution. `server.ts:308`.
- **J-6 delivery gate** — validation/canonicalization is delegated to the Python library over the
  raw bytes; invalid → `422` dead-letter, runner must not retry (JC-6). `validator.ts`, `server.ts:287`.
- Bearer tokens are not logged (Fastify default serializers omit headers).

### Findings (severity order)

**F1 — High — Leaked/rogue runner token: blast radius exceeds "job claims," and a crafted valid
snapshot reaches the live facts surface with no human in the loop.**
The bearer token set authorizes the **whole** producer/ops surface, not just claim/lease (server
docstring: "the enqueue surface shares the same token set until SSO lands at CP-4"). One token can:
(1) claim a snapshot job and **deliver a schema-valid but false snapshot** — J-6 checks structure +
system-binding, never truthfulness; (2) `POST /v1/jobs` enqueue arbitrary jobs; (3) cancel any job
(starve sync acquisition); (4) `GET /v1/snapshots/:id/body` read **every** stored snapshot body =
full estate schema/metadata exfiltration; (5) read `health_events`/`runs`. J-4 bounds raw-secret
exposure (references only) and D-47 human PR review bounds *merged-KB* integrity — **but neither
bounds** metadata confidentiality (4) nor the accepted snapshot being served as `get_table` facts
authority **pre-merge** (M-5/MC-5). So "J-6 + PR review" is necessary but insufficient; the token is
the trust boundary for the facts surface.
*Rec (amend → CP-4 requirement):* at CP-4 do **not** inherit the shared-token fence — split auth so
runner tokens authorize only `claim/start/heartbeat/complete/fail/defer`, and the
producer+read surface (`/v1/jobs` enqueue, cancel, `/v1/snapshots*`, `/v1/health-events`, `/v1/runs`)
moves behind SSO/service identity. Reflect unmerged-snapshot provenance in the MCP trust block (see
MCP-R9). Register motion **P-A** (home: job-protocol JP-*). `server.ts:99-127,178-203,267-338`.

**F2 — Medium — Webhook socket cap trusts Content-Length; a chunked/under-declared body streams to
the ~64 MB global limit before the unauthenticated 401.**
The hook guard checks only the `Content-Length` header (`server.ts:108`), but Fastify still buffers
the hook body (`parseAs:"buffer"`, then discards) up to the **global** `bodyLimit`
(`resultMaxBytes + 64 KB` ≈ 64 MB), and the secret check runs *after* parsing. A client omitting
Content-Length (chunked) or lying about it forces ~64 MB of buffering per request with **no valid
secret** — unauthenticated memory-amplification DoS. SY-2 promises the 64 KB cap "guards the socket."
*Rec (accept):* register the hook route with a route-level `bodyLimit: cfg.sync.hookBodyMaxBytes` so
Fastify enforces the byte cap during read regardless of the header. `server.ts:62-114`.

**F3 — Medium — Core-side defense-in-depth secret redaction (job spec §7) is not implemented; a
connector exception can carry a driver-embedded secret into `jobs.error` / `health_events.detail`,
readable by any token holder.**
§7 requires the core to "redact any string matching a resolved-reference pattern from stored error
detail." The queue stores the error envelope verbatim (`queue.ts:378-408,454-463`); the runner builds
`detail` from `str(exc)` + `traceback.format_exc()` (`runner.py:129-139`). Tracebacks don't dump
locals (good), but exception *messages* routinely echo DSNs/URIs; that string lands in stored error
detail and is served by `GET /v1/health-events`. JC-8's canary test is not yet exercised against live
credentials, and the pilot is live (`example-estate.com`).
*Rec (accept):* implement §7 reference-pattern redaction on stored `error.detail`; when live-mode
credential resolution lands in the runner transport, scrub resolved values from exception
messages/tracebacks before building `JobError`. Must close before live-credential runners ship.

**F4 — Medium — Sync PR body interpolates snapshot-derived strings with inconsistent
backtick-wrapping and no markdown escaping — a crafted object name breaks out and injects markdown
into the PR the human reviewer trusts.**
`changelog.ts` builds the PR body from FQNs, view-definition `detail`, rename `interpretations`,
etc. Names are backtick-wrapped (a backtick *inside* a name closes the span), and some `detail`
strings are interpolated raw (e.g. `changelog.ts:117`). A snapshot object/column name or view
definition containing a backtick or markdown can mislead the reviewer, inject `@team` mention spam,
or hide the "## Breaking" section — undermining the D-47 review backstop that F1's integrity bound
relies on. Same class as LED-R5 (ledger text in PRs).
*Rec (accept):* escape/neutralize interpolated snapshot content (strip backticks + markdown control
chars, or fence in a code block that can't be broken) when composing PR title/body. `changelog.ts`.

**F5 — Low — Webhook `401` vs `404` is an existence oracle for configured hooks.**
`getHookSecretHash` returning null → `404` *before* any secret compare; a configured system with a
wrong secret → `401`. An unauthenticated caller learns which systems have a hook (`server.ts:389-401`).
The response *body* is uniform (M-4 spirit honored) and the split is what §4.2 literally prescribes;
system names are guessable (supabase/ga4/gsc), so leak value is low.
*Rec (defer):* accept as spec-prescribed; if hook-existence confidentiality later matters, return a
uniform `404` for both bad-secret and unknown-system (optional §4.2 clarification, motion **P-F**).

**F6 — Low — Runner-token rotation requires a core restart, unlike hook secrets.**
`CORE_RUNNER_TOKENS` is parsed once at boot into `cfg.runnerTokens` (`config.ts:185`); rotation needs
a redeploy — a gap vs J-8 "rotatable without redeploying the core" (hook secrets, by contrast, are
read per-request from Postgres).
*Rec (defer):* acceptable interim via orchestrator secret rotation + rolling restart. For J-8 parity,
store runner-token hashes in ops Postgres read per-request, or support a SIGHUP reload (motion **P-G**).

**F7 — Info — Subprocesses inherit the full core environment (all secrets).**
`gitEnv` spreads `...process.env` (`gitkb.ts:28`); the validator and Python stages spawn with the
inherited env by default. A compromised or verbose child (or a library it loads) could leak
`CORE_RUNNER_TOKENS`, `CORE_DATABASE_URL`, `SYNC_GIT_TOKEN`.
*Rec (defer, hardening):* pass a curated minimal env to each spawned subprocess.

**F8 — Verify (config, not code) — `contextlayer-sync` PAT least privilege.**
D-47 says main is protected and the steward merges; the code only pushes branches and opens/closes/
comments/labels PRs (`gitkb.ts`). Assert at deploy that the PAT is **fine-grained, scoped to the
single KB repo**, `contents:write` + `pull_requests:write` only, and **cannot** merge to `main` or
edit branch protection. Testable against the GitHub API; record the result with the SP-2 sign-off.

---

## Part 2 — MC-5: MCP server design review → CP-4 requirements checklist

The mcp-tool-reference + capability specs are strong; most surfaces the brief raises are already
ruled. Below, each item is **testable** and cites the ruling that solves it, or is flagged **NEW**
where the build must add a control the spec leaves implicit. Build the CP-4 MCP server to this list.

### Per-call identity ∩ profile (M-3, §3, MT-1/MT-9)

- **MCP-R1** — Identity `{subject, roles}` is resolved from the OIDC token on **every** call; roles
  are never session-cached (revocation effective next call). *Test:* MT-9 (revoke at IdP → next call
  denied). Ruling: §3.
- **MCP-R2** — The active profile is bound from client config but the server independently validates
  `roles ⊇ profiles/<p>.yaml roles:`; a profile the caller's roles don't permit fails the
  **connection**, and the per-call allow-set is recomputed from the token's roles, not the client's
  assertion. *Test:* client asserts a profile outside its roles → connection refused; MT-1. Ruling: §3, M-3.
- **MCP-R3 (session fixation)** — Because identity is re-resolved per call, a token swap mid-session
  must re-bind identity and re-evaluate the allow-set; no privilege from the connection-time profile
  may leak to a different subject. *Test:* open as user A, present user B's token on a call → B's
  roles govern, A's profile grants nothing. **NEW** (make the §3 property an explicit test).
- **MCP-R4 (tool + qualifier confusion)** — Tools outside `(roles ∩ profile.tools.allow)` are hidden
  from `tools/list` **and** denied on direct call; system/target qualifiers are enforced
  (`execute_sql:supabase` grants supabase only, not ga4). *Test:* MT-1 + a qualifier-mismatch call →
  denied. Ruling: M-3.

### validate_sql / execute_sql injection surface (M-1/M-2, §5, §6.6, CI-3/QE-1)

- **MCP-R5 (token binding)** — `execute_sql` re-verifies the validation token: signature ∧
  `statement_sha256` == executed bytes ∧ `subject` == caller ∧ `snapshot_ref` current ∧ not expired
  (300 s, MC-2). Any mismatch → `revalidate_required`, never silent re-validation or execution.
  *Test:* MT-3 (missing/expired/tampered/foreign-subject token) + MT-4 (snapshot moved). Ruling: M-2, §5.
- **MCP-R6 (multi-statement smuggling)** — `validate_sql` parses and rejects anything that resolves
  to >1 statement or a non-SELECT statement class; the token binds the exact single statement.
  *Test:* `SELECT 1; DROP …` → fail; a validated statement cannot be swapped for a batch at execute
  (hash mismatch). **NEW** (make the §6.6 "SELECT-only" explicit about statement multiplicity).
- **MCP-R7 (dialect/guardrail bypass)** — SELECT-only is enforced by the **parser**, not regex:
  CTE-wrapped writes, `SELECT … FOR UPDATE`, `COPY`, `DO`, `pg_read_file`/other side-effecting
  functions are refused; API dialect rejects undocumented dimensions/metrics (MT-8). Row-cap +
  timeout are enforced at the **executor** even if guardrails are absent from the payload (CC-3),
  **and** attached at the gateway (CI-3 defense in depth). *Test:* CC-3, MT-8, per-vector canaries.
- **MCP-R8 (no client guardrails)** — Profile `limits` are injected server-side; client-supplied
  guardrails in arguments are ignored. *Test:* MT-5. Ruling: §3.

### Snapshot-inventory binding — scope containment (M-4, §6.3/§6.5)

- **MCP-R9 (facts provenance — the MC-5 decision)** — `get_table` serves machine facts from the
  latest accepted snapshot (M-5/MC-5). Because snapshot acceptance (runner + J-6) is the **only**
  gate on the facts surface and bypasses human PR review (F1), the trust block must carry
  `snapshot_ref` **and signal when facts come from a snapshot ahead of the merged/verified render**
  (`hash_match:false` → `warn-user` already exists §4 — make it mandatory + explicit for the
  render-lag case). *Test:* MT-6 + a case where snapshot newer than the rendered doc → guidance
  `warn-user`, provenance visible. **NEW** requirement folded into the MC-5 disposition.
- **MCP-R10 (content visibility)** — every content tool (`search_context`, `get_entity`, `get_table`,
  `get_metric`) applies the role→visibility map server-side; hidden objects return `not_found` (never
  `permission_denied`), filtered search hits are simply absent. *Test:* MT-2. Ruling: M-4.
- **MCP-R11 (lineage visibility)** — `get_lineage` must visibility-filter **every node in the walk**,
  not just the entry object; a walk that reaches a hidden schema must not disclose hidden node FQNs
  or edges. *Test:* lineage from a visible object into a hidden schema omits/masks the hidden nodes.
  **NEW** — the spec (§6.5) does not state that M-4 applies node-by-node in the walk; register
  clarification motion **P-E**.

### Trust-block integrity (M-5, §4)

- **MCP-R12** — The trust block and `agent_guidance` are computed server-side from KB HEAD status +
  live hashes; the client cannot suppress the block, override `agent_guidance`, or supply
  contamination/staleness. Honest scope: for reads this is **advisory** to the agent (OD-1 limitation
  — the server cannot force an agent to refuse), so the *hard* controls remain: execute-path
  `snapshot_ref` block (§3), visibility (M-4), and the audit record. State this split explicitly in
  the CP-4 build so "trust block" is not oversold as enforcement for reads. *Test:* MT-6; a client
  that strips the block still gets execute-path staleness block + audited true status.

### Cross-cutting

- **MCP-R13 (audit completeness, M-8)** — one audit record per call incl. `denied`/`filtered`
  decisions; `args_digest` is a hash; full SQL/intent stored only for execute/validate/publish;
  record links to ledger via `audit_ref`. *Test:* MT-1/MT-2 (filtered reason recorded), MT-7.
- **MCP-R14 (rate limits, §7)** — per-identity limits enforced server-side (source protection);
  `flag_gap` rate-limited per session. *Test:* limit exceeded → `rate_limited`.
- **MCP-R15 (KB-F)** — repo-level docs (`index.md`/`conventions.md`/`_notes.md`, KB-1-exempt, served
  without a trust block) must still be visibility-checked and must not leak cross-scope content. The
  KB-F register trigger is literally "CP-4/M1 MCP server session" — resolve it here.

---

## Part 3 — FL-E: fault-ledger access review → CP-4 requirements checklist

Ledger + `list_gaps` ship with the MCP server (CP-4); review is against the fault-ledger spec. The
spec's privacy posture (L-8, §10, FL-E) is sound; the **larger real leak is query-term/description
content, not `distinct_subjects`**.

- **LED-R1 (read gating)** — `list_gaps` is allowlisted in the **Steward** (and `benchmark`) profiles
  only; absent from Reporter `tools/list`; direct call by a non-steward denied. *Test:* FL-5. Ruling: L-7.
- **LED-R2 (read visibility + PII, the substantive FL-E finding)** — `list_gaps` and KB Health omit
  issues whose `object_fqn` the caller's role cannot see (M-4). **But** `coverage_gap`/`missing_entity`
  fingerprints scope on **normalized query terms** (§3.3), and `title` is generated from them — user
  search text ("net salary by employee ssn") can surface to a triager. *Rec (amend the build):*
  require that (a) `description` and query-term-derived `title` are never populated with data values
  (server-side scrub + skill K-GROUND, §10), (b) they are visibility-filtered, (c) length-bounded.
  *Test:* extend FL-6 — a PII literal in a search query does not appear verbatim in any `list_gaps`
  title/terms. **NEW.**
- **LED-R3 (write integrity)** — `flag_gap` attaches **server-set** identity/session/profile/refs; a
  client cannot forge `subject`/`refs`/`class`; rate-limited per session (MCP §7). *Test:* client
  cannot set its own subject/refs; rate limit enforced. Ruling: §6.
- **LED-R4 (resolve integrity)** — only a **merged** KB PR carrying `CL-Resolves: <issue-id>` resolves
  an issue (`resolved_by: pr`, `pr_url`); merge requires steward/code-owner (D-47), which bounds who
  can resolve by trailer; the core validates the `issue_id` exists; recurrence reopens (L-4). Manual
  dashboard resolution requires steward role. *Test:* FL-4, FL-10. Ruling: L-5/L-4.
- **LED-R5 (injection via ledger text in dashboard/PRs)** — `description`/`title` are rendered in the
  KB Health dashboard (HTML → XSS surface) and may be cited in enrich PRs (markdown → same class as
  F4). *Rec (accept):* escape/neutralize ledger text at both render points. *Test:* a `<script>` /
  backtick payload renders inert in the dashboard and in any PR body. **NEW.**
- **LED-R6 (retention + audit of resolutions)** — events deleted at 90 d, issues + resolution history
  kept indefinitely; resolutions carry who/what/when/`pr_url`; reopen preserves prior resolution.
  *Test:* FL-7 (sweep deletes >90 d events, never issues), FL-10. Ruling: §10, L-4.
- **LED-R7 (`distinct_subjects` — the FL-E decision)** — `list_gaps` and KB Health expose
  `distinct_subjects` as a **count only**; individual identities are reachable solely via `audit_ref`
  → audit log under Audit-module roles. *Test:* FL-5 response carries the integer, no subject
  identifiers; identities only via `audit_ref`. **Affirm counts-only** (FL-E default).

---

## Threat-model one-pager — deployed topology

Topology (single customer VPC): **Internet** → **core** (webhook now; OAuth/MCP at CP-4) →
**ops Postgres** (queue, snapshots, ledger, audit, secret *hashes*); **runner** (outbound-only, J-2)
→ **vault** (runner identity, J-4) and → **sources** (Supabase/GA4/GSC, read-only creds); **core** →
**KB repo** (fine-grained PAT, push+PR only; `main` protected, steward merges — D-47); **MCP client**
(Claude Code) → core → **IdP** (OIDC, per-call).

Trust boundaries: (1) Internet→core pre-auth surface (hooks; OAuth at CP-4); (2) runner→core
(bearer; core never dials the runner); (3) runner→vault/sources; (4) core→ops-Postgres;
(5) core→KB (PAT, no merge); (6) MCP client→core (per-call OIDC); (7) **the human PR reviewer** —
the integrity gate for all KB content (D-47).

| # | Risk | Sev | Mitigation (ruling / this review) |
|---|------|-----|-----------------------------------|
| R1 | Leaked/rogue runner token → estate-metadata exfiltration + poisoned-snapshot facts injection | High | J-4 (no raw secrets), J-6 + system-binding, D-47 (merge gate) bound *integrity*; **split runner vs ops/read auth at CP-4 (F1/P-A)**; snapshot provenance in trust block (MCP-R9) |
| R2 | CP-4 MCP identity/authz bypass (forged profile, cross-scope pull, token replay) | High | Build to MC-5 checklist: per-call roles∩profile (MCP-R1/2/3), signed subject-bound tokens (MCP-R5), visibility incl. lineage (MCP-R10/11), no client guardrails (MCP-R8) |
| R3 | Secret leakage via error/health surfaces + subprocess env | Med | Implement §7 core redaction + connector message scrub (F3); curated subprocess env (F7); run JC-8 canary against live creds before pilot runners |
| R4 | Content injection into human-reviewed PRs / dashboards undermines the D-47 backstop | Med | Escape interpolated snapshot + ledger text (F4, LED-R5) |
| R5 | Unauthenticated webhook DoS + token-driven acquisition-cancel DoS | Med | Route-level hook `bodyLimit` (F2); authenticate/split the ops surface (F1); SY-6 single-flight + §8 dedupe already bound sync churn |

Out of window (flagged, not reviewed here): **direct-on-OLTP execution** is the pilot-ending risk
class and is CP-6 / security review #2 (plan §11); guardrails (read-only role, timeout, row cap,
reporting-views) are mandatory from the first query there.

---

## Register-ready dispositions (for your ruling)

### Close per plan §5 / §10

| Item | Finding | Disposition | Recommendation |
|------|---------|-------------|----------------|
| **SP-2** — benchmark-mode waiver leakage | The waiver keys to the **server-known** `benchmark` profile; a client cannot self-assert it *iff* profile binding is server-side (M-3/§3, AS-8) | **accept (close as non-issue) — conditional** | Confirm at CP-4 that the benchmark waiver reads the server-resolved profile, never a client flag; gate the closure on MCP-R2 + MT-1 passing. Expected outcome (non-issue) holds. |
| **MC-5** — snapshot-vs-render authority for facts | Snapshot authority is correct (facts must be current), but acceptance is the sole, human-review-bypassing gate on the facts surface (F1) | **accept default + amend** | Keep snapshot authority; **add MCP-R9**: trust block must carry `snapshot_ref` and signal render-lag (`warn-user`). Then close MC-5. |
| **FL-E** — `distinct_subjects` privacy | Counts-only is right; the real leak is query-term/description content | **accept default + amend** | Affirm counts-only (LED-R7); **add LED-R2 + LED-R5** (scrub + visibility-filter + escape ledger text) as CP-4 build requirements. Then close FL-E. |

### New proposals (enter via the register / OD-5 before build — proposed here, not enacted)

| ID | Proposal | Home | Tag |
|----|----------|------|-----|
| **P-A** | Split runner-claim auth from the producer/ops+read surface at CP-4 (F1) | job-protocol JP-* | amend → **recommend accept** as a CP-4 requirement |
| **P-B** | Route-level `bodyLimit` on `/v1/hooks/*` (F2) | code fix, no ruling | accept |
| **P-C** | Implement job-spec §7 core redaction + runner message scrub (F3) | already specified — build gap | accept |
| **P-D** | Escape interpolated snapshot/ledger text in PR bodies + dashboard (F4, LED-R5) | code fix | accept |
| **P-E** | Clarify M-4 applies node-by-node in `get_lineage` walks (MCP-R11) | MCP spec §6.5 | amend |
| **P-F** | Uniform `404` for bad-secret vs unknown hook (F5) | sync spec §4.2 | defer |
| **P-G** | Runner-token rotation without restart (F6) | job-protocol J-8 parity | defer |
| **P-H** | Assert `contextlayer-sync` PAT least privilege at deploy (F8) | deploy config / playbook | verify |

Nothing here blocks *starting* CP-4. The CP-4 build must, however, land P-A/P-C/P-D and the MC-5 /
FL-E checklists before M1 sign-off, since those are the controls M1's pilot-user exposure depends on.
