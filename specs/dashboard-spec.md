# Contract Specification — Dashboard & Operator Surfaces (v1)

Status: v1 draft for implementation. Entry condition for Track B of the Phase-2 plan (B-0 builds only after this merges). Requirements source: the CP-8 go/no-go report Part 5 — its inventory (U-1..U-18), role→view matrix, and no-UI boundary list are incorporated as this spec's normative content, adjusted only where noted. The module registry slot this spec fills has existed since platform-architecture §6 ("dashboard track, gates nothing"); the parked register items it serves (Connections UI/E2, setup export, KB Health, LED-R5 render rule, SO-F, freshness, deliveries, audit) are its backlog made contractual.

---

## 1. Scope

**In scope:** the dashboard's design rulings; the module map and its mapping to checkpoints B-0..B-4; the read-API contracts the dashboard consumes (audit, publish deliveries, ledger triage — the B-0 deliverables); the write surfaces it may expose; the role→view matrix as the normative access statement; render-safety rules; the no-UI boundary; conformance tests.

**Out of scope (owned elsewhere, consumed here):** identity and role evaluation (MCP spec §3 / M-3 — the dashboard adds nothing to it); ledger semantics (fault-ledger spec); profile compilation (platform-architecture §5); connection CRUD semantics (checkpoint A-3 owns the API; module U-1 is its face); anything on the no-UI boundary list (§7).

## 2. Design rulings

| # | Ruling | Rationale |
|---|---|---|
| UI-1 | **The dashboard is a client of the governed API, never a second enforcement point.** Every permission consequence is a server 403 or server-filtered empty; no allow/deny logic exists in client code. A matrix cell reading "—" is a server response, not a hidden menu item | One enforcement point is the product's security story; a second one is a fork that drifts |
| UI-2 | **The user's own identity, always.** The dashboard authenticates the user's OIDC session and calls the API as that user. No dashboard service account, no privileged backend-for-frontend, no token that widens what the user could do from a session | A UI that holds more power than its user is a shadow permission system by construction |
| UI-3 | **Read APIs before pixels.** Audit (U-12), publish deliveries (U-9), and ledger triage (U-5) get governed read endpoints, subject/role-filtered server-side, before any view renders them. Filtering rules: a reporter reads only rows whose subject is their own token-derived identity; steward scope per role map; auditor read-only over all | B-0's gate; the trap named in CP-8 (fetch-all-filter-client) is structurally excluded |
| UI-4 | **View roles are server roles first.** Any role a view needs (the `auditor` role does not exist today) is added to the server model (roles.yaml + profile) before the view exists; the dashboard never knows a role the server doesn't | The single most likely place to grow a shadow permission system, closed in advance |
| UI-5 | **Render neutralization is layered, server-authoritative.** LED-R5's server-side scrub remains the authority; the dashboard additionally renders all user-supplied text (ledger titles/descriptions, gap text, error details, object names) inert — no markdown execution, no HTML injection — asserted by test on the render path | The PR-body injection class (F4/LED-R5) applies to every surface that displays user text |
| UI-6 | **The no-UI boundary (§7) is normative.** The dashboard routes to git/PR/session flows and never replaces them; it has no write path to KB `main` — asserted by test | The PR flow is the product; each convenience button that bypasses it forks the governance story |
| UI-7 | **Write surfaces are ops-config only**, each behind server-side role checks: connection CRUD (via A-3's API), detector-rule thresholds (L-3, already ops config), webhook secret lifecycle, the `regen-all` trigger (SO-E), suppression threshold (SUPPRESS-1's home, when built). Profile *editing* is not a write surface — it composes a PR (§7.1) | These are the things git is genuinely bad at; everything else stays in PRs |
| UI-8 | **Secrets are write-only.** A secret is displayed exactly once, from the creation response; no read endpoint returns one; the UI never stores one | J-4's posture, carried to the last surface that could break it |
| UI-9 | **Ships with the core, configured from the KB.** The dashboard versions and releases with the core; `dashboard.yaml` (already bootstrapped in every KB) selects modules and view-role bindings per deployment. No separate deployment lifecycle, no second auth domain | One release train, one config source, one identity domain |
| UI-10 | **Dark states are honest.** A view whose data does not exist (Benchmarks before BASELINE-1; deliveries before the first publish) renders a stated dark/empty state naming why — never placeholder numbers, never sample data | The no-claims constraint (plan §2.3) enforced structurally, and the product's honesty character carried into pixels |
| UI-11 | **Verdicts are not content.** The Knowledge Requests queue's approve/reject is a steward-gated write surface that changes LEDGER STATE ONLY: approval means "worth drafting," never "enters the KB." Requester-proposed text is drafting input for the enrich skill (cited as "customer-provided, <name>, <date>") and never lands in the KB verbatim; the certification act remains the human merging the batch PR's reviewed diff (§7.2 unbroken). Approve produces no git call — asserted by test | The queue must not become the skip-the-diff button through the side door; intent-triage and content-certification are two different judgments at two different gates |

## 3. Module map (inventory → module → checkpoint)

| Module | Serves inventory items | Checkpoint | Notes |
|---|---|---|---|
| **KB Health** | U-4 freshness/trust map, U-7 freshness warnings, U-8 sync-state (SO-F consumed at last), U-15 lineage explorer (read) | B-1 | R2's home screen (HLR §3); drift-PR queue routes to the git provider — no merge button (asserted, §7.3) |
| **Gap Triage & Knowledge Requests** | U-5 triage queue, U-6 human gap filing (`human_filed` inlet under the filer's identity), U-19 enrichment-request queue (submissions with optional proposal text; steward approve/reject verdicts; approved worklist; "deliver batch" trigger), F-10 resolution surfacing, F-11 worklist ordering | B-1 | LED-R5 render test lives here; queue ordered by occurrences / distinct_subjects; verdicts per UI-11 (state-only, steward-gated); batch flow: approved items → one enrich-skill drafting pass → one PR carrying per-request resolution trailers → merge notifies every requester. Batches are cut on demand or at ~10 approved — bounded and fresh, never an immortal rolling PR |
| **Connections** | U-1 list/register/test/health | B-2 | Thin face over A-3's API; the admin CLI is a peer client of the same endpoints |
| **Setup** | U-2 bundle download, U-3 staleness signal | B-3 (download served by A-2) | Download authorizes against the requester's own profile binding server-side; a URL never carries a profile name |
| **Profiles** | U-14 editor, U-18 suppression config (when built) | B-3 | Composes a PR under the editing user's identity with the CL-Resolves trailer generated where applicable; no write to `main` (§7.1) |
| **Ops** | U-10 run/job health + dead-letter re-enqueue, U-11 webhook secrets (write-only), U-16 detector rules, U-17 regen-all trigger | B-1 (read) / B-2 (write surfaces) | Re-enqueue is `POST /v1/jobs` as the user |
| **Publish** | U-9 deliveries + attestation history; the delivered-but-unattested dangling state gets its viewer (F-15) | B-0 API, B-1 view | Per-artifact revision history; "what changed in this revision" (F-17) renders from attestation rows |
| **Audit** | U-12 audit view, retention/export | B-0 API, B-4 view | Auditor role added server-side first (UI-4); reporters, if granted a view at all, see only their own rows via server filter |
| **Benchmarks** | U-13 scores per kb_ref | B-4 | Ships dark behind BASELINE-1 per UI-10 |

## 4. Role → view matrix (normative)

The CP-8 Part 5 matrix is adopted verbatim as this spec's access statement, with its flagged corrections binding: per-subject audit filtering is server-side (UI-3); `auditor` exists server-first (UI-4); U-2 download authorization is server-side against the requester's own binding; U-11 is write-only (UI-8); U-5 rendering is layered (UI-5). Any future change to the matrix is a change to this section — an amendment under the fence, not a frontend decision.

## 5. Read-API contracts (B-0 deliverables)

Three endpoints, each: authenticated by the caller's OIDC session; role-and-subject filtered server-side per §4; paginated; stable JSON shapes versioned with the core.

1. **Audit read** — query by time window, subject (self-only unless role permits), tool, decision; returns audit records as stored (args digests, decisions incl. denied/filtered, and per D-108.4 the `setup_stamp` the session presented — `unstamped` when it presented none, absent/null only on rows predating the column); `extract-audit.sh` becomes a client of this endpoint (its direct-DB path retires).
2. **Publish deliveries read** — by artifact id or window: model deliveries, attestations, dangling (delivered-unattested) state, per-revision definition hashes.
3. **Ledger triage read + workflow writes** — read: open issues and enrichment requests ordered by occurrences/distinct_subjects, visibility-filtered per M-4, counts-only subjects (LED-R7), server-scrubbed text (LED-R2/R5). Writes, each role-gated server-side: the `human_filed` gap inlet under the filer's server-derived identity; the enrichment-request inlet (optional proposal text, scrubbed and length-bounded); steward verdict writes (approve / reject-with-reason — ledger state only per UI-11, recorded with the steward's identity and timestamp); the "deliver batch" trigger marking approved items batched. Rejection reasons and batch-merge resolutions surface to the filer (F-10).

Conformance for each includes the negative: a reporter's call cannot return another subject's rows (DT-1) — proven by test, not by review.

### 5.1 CLOSED at B-1 (D-114.1) — governance writes are in the audit read

**Closed 2026-08-06**, ahead of the trigger below rather than at it, under the amendment fence D-113 set for the B-1 session (proposed in five lines, authorized by the operator). **The contract widens from "one row per MCP call" to "one row per governed act."** No schema change was needed — `audit_records` was already tool-agnostic. Connection upsert/delete/test, ledger verdicts, the deliver-batch trigger and the `batched → approved` return each write one row carrying the acting subject and roles from the resolved session, `tool` naming the act (`dashboard.connection.upsert`, `dashboard.ledger.verdict`, …), `session_id: null` and `setup_stamp: unstamped` (a browser session is neither an MCP session nor a stamped one, and inventing values would make governance rows indistinguishable from tool calls in the register meant to tell them apart), an args digest over the request, and **`decision: allowed | denied`** — denied included, because a reporter's refused verdict attempt is precisely the row an auditor wants and a success-only log would omit it.

Every existing consumer filters by `tool`, so none re-reads differently; asserted by test rather than by review. One consequence, recorded so a future evidence extraction does not read it as corruption: **audit-window row counts now include governance rows**, correctly attributed to the acting subject.

Not done, and not needed for the closure: a separate governance-write table (the other candidate below), and any retro-fill of writes that predate this.

**B-4's gate no longer inherits a blocking clause here.** The original filing is kept below because the reasoning is the record.

#### The original filing (D-110.3a, 2026-08-06)

**The gap, stated plainly.** `audit_records` is specified as one row per MCP call, and it is exactly that. Connection CRUD — the A-3 writes that register, reconfigure and remove a source through `/v1/dashboard/connections` — writes **no audit row**. Today the durable record of a dashboard act is the job's `triggers` array, which carries the acting identity for a probe but exists only where a job exists: a registration that enqueues nothing leaves nothing behind. The same will be true of every governance write B-2/B-3 adds (webhook rotation, detector thresholds, profile edits) unless the shape changes first.

**Why it is filed rather than fixed here.** The fix is a schema question, not a patch: either `audit_records` widens beyond "one row per MCP call" and its every existing consumer is re-read against the wider contract, or a second governance-write table joins it at the read API. That is a ruling, and inventing it inside a build session is how a spec gets contradicted silently.

**Trigger — normative.** This MUST close **before B-4's audit view ships**. An audit view that renders MCP calls and silently omits the writes that changed who can reach what is not an incomplete feature; it is a dishonest one, and it would be dishonest in exactly the register the auditor role exists to read. B-4's gate inherits this clause.

### 5.2 Filed as recorded (D-110.3b)

Two A-2 rulings whose surfaces the read APIs will meet, recorded here so they are not rediscovered at B-4:

- **D-107.3 — verdict history.** An ambiguous profile binding is refused, not resolved. The refusal is a decision with a subject, a time and a reason, and nothing currently retains it; whether verdict history is an audit concern or a ledger one is open.
- **D-107.4 — jobs retention.** A browser gets the login flow and a script gets 401; both leave job rows whose retention is unset. The audit read's window semantics assume a horizon that no policy defines.

## 6. Render-safety rules

All user-supplied text renders inert (UI-5) — ledger text, gap descriptions, object/column names (the F4 lesson: names are attacker-influenceable), error details, PR titles echoed from the git provider. Links out (drift PRs, reports, git) carry no credentials and open the provider's own auth. Nothing in the dashboard persists API payloads client-side beyond the session.

## 7. The no-UI boundary (normative — Phase 2 inherits the line, not just the list)

1. **Profile and role changes** — KB YAML under branch protection; the Profiles module composes a PR under the user's identity and must not write to `main` (asserted, DT-4).
2. **Enrichment content and certification** — `verified` means a human merged a reviewed diff with their name (KB-7). No certify button detached from a diff. This is the single most important line in this section.
3. **Drift review and merge** — the product never merges (SO-B). Queue view yes; merge button never.
4. **Reporting-view DDL** — the dashboard may show pending handovers; it may not apply them (D-81).
5. **Report authoring** — RA-1: authoring intelligence lives in the customer's Claude Code session; no chart builder.
6. **The KB itself** — one physical source of truth; no dashboard doc editor.

Exceptions to this section are rulings, never patches.

## 8. Conformance tests

| # | Test | Implements |
|---|---|---|
| DT-1 | Reporter calls each B-0 endpoint → own rows only; crafted request for another subject → 403/filtered server-side | UI-3 |
| DT-2 | A view denied by role renders the server's 403 state; client bundle contains no role-conditional logic (static assertion + e2e) | UI-1 |
| DT-3 | Script/markdown/backtick payloads in ledger title, gap text, and an object name render inert in Gap Triage and KB Health | UI-5, §6 |
| DT-4 | Profiles module: edit → PR under the editing user's identity with generated trailer; no code path pushes to KB `main` (asserted) | UI-6, §7.1 |
| DT-5 | Webhook secret: shown once on creation; no GET returns it; UI state after reload holds no secret | UI-8 |
| DT-6 | Benchmarks with no scores → stated dark state; no placeholder numerals anywhere in the DOM | UI-10 |
| DT-7 | Auditor view refuses until roles.yaml + profile carry the role; adding them server-side lights it with no client change | UI-4 |
| DT-8 | Connections module performs every operation through A-3's API; no direct-DB path exists in dashboard code | UI-1, §3 |
| DT-9 | Sync configured-but-disabled → KB Health renders the warning state from /healthz's sync_enabled (the two-silent-days shape now visible) | SO-F, §3 |
| DT-10 | A resolved gap surfaces to its filer's next dashboard session (mechanism per UI-D decision) | F-10 |
| DT-11 | Verdict writes are steward-gated server-side: a reporter's approve/reject call → 403; a steward's verdict records identity + timestamp in ledger state; approve makes NO git call and writes NO KB content (asserted) | UI-11 |
| DT-12 | A request's proposal text containing script/markdown payloads renders inert in the queue AND appears nowhere verbatim in the batch PR's diff — the drafted doc cites it ("customer-provided, <name>, <date>") without embedding the raw submission | UI-5, UI-11 |

## 9. Register actions and authorized amendments (additive, diffs leading)

1. **Platform-architecture §6**: module registry aligned to §3's map (naming only; the slot exists).
2. **Fault-ledger spec**: one additive amendment (authorized by D-101): the `enrichment_request` kind with proposal payload, verdict states, and batch lifecycle — this spec binds to it; all existing LED rules (scrub, length bounds, counts-only, render neutralization) apply to proposals unchanged.
3. **KB spec**: none — `dashboard.yaml` is already enumerated; its module/view-role schema is versioned with the core per UI-9.
4. **Register**: E2 (Connections UI) closes at B-2; SO-F closes at B-1 (DT-9); U-items tracked against checkpoints; the auditor-role addition is a KB content change (roles.yaml + profile PR), not a spec amendment.

## 10. Open decisions (spec-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| UI-A | Frontend stack | **Closed** (D-103.1, 2026-08-05): a light **SPA (React)** built to **static assets served by the core** — no separate frontend server, no client-side permission logic, no client persistence. UI-1, UI-2 and UI-9 are restated as build constraints rather than aspirations: an asset bundle served by the core has no second identity domain to acquire and no server of its own to grow allow/deny logic in. Component and library specifics are the B-1 session's proposal, ≤5 lines. (Platform-architecture §4 already recorded "React + TypeScript, served by core"; it now has a ruling behind it.) | — |
| UI-B | Pagination/retention windows for read APIs | Server defaults, config-overridable; audit export honors MCP §8 retention | First large window query |
| UI-C | Theming/branding | Product default only | First customer branding ask (pairs with RA-C) |
| UI-D | F-10 resolution-surfacing mechanism | **Closed** (D-103.2, 2026-08-05): the provisional default is confirmed as v1 — a **dashboard badge on the filer's next session**, carrying batch-merge resolutions and rejection reasons alike (ledger §4 amendment, D-101.2). In-session surfacing via a `report_freshness`-style line remains a skill-side candidate and is **unbuilt** — named so it is not mistaken for shipped. DT-10's "mechanism per UI-D decision" now reads: the badge | — |
| UI-E | Notifications beyond the dashboard (email/webhook for SO-F, freshness) | None in v1; health surfaces are pull | First customer whose ops team demands push |
