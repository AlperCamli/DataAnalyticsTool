# Contract Specification — MCP Tool Reference (v1)

Status: v1 draft for implementation. Normative reference for the MCP server's tool surface: `context-layer-v1-spec.md` §6 plus `flag_gap` (HLR §7.2) and `list_gaps` (added through the OD-5 register process; fault-ledger spec §12). Consumes: KB repository spec (trust semantics, visibility map), capability interfaces spec (guardrail/identity envelopes, effective Publisher flags), job protocol (interactive job class), HLR §6 (fault-ledger classes) and §7 (profiles, skills).

This spec resolves capability-spec open decision **CI-B** (ruling M-1 below) and makes one additive amendment to the KB spec (§10).

---

## 1. Scope

**In scope:** the session and enforcement model; common response envelopes (trust block, refs); the validation-token flow; the per-tool reference (parameters, responses, errors, gating) for all eleven tools; error taxonomy and rate limits; the audit contract; conformance tests.

**Out of scope:** MCP transport mechanics (streamable HTTP + OAuth are platform-architecture facts), search index implementation, and skill behavior *around* the tools (skill specifications).

## 2. Design rulings

| # | Ruling | Rationale |
|---|---|---|
| M-1 | One `validate_sql(system, request)` tool, dialect-switched by the system's class; API requests validate against the KB's documented dimension/metric surface | Resolves CI-B; one guardrail concept, two dialects (CI-6); tool surface stays minimal |
| M-2 | `validate_sql` returns a signed, short-lived **validation token**; `execute_sql` requires it and the gateway re-verifies the binding | "Validate must pass first" becomes cryptographically enforceable, not skill convention |
| M-3 | Tools outside (OIDC roles ∩ profile allowlist) are **hidden from `tools/list` and denied on call** | Hiding prevents attempts; denial guards clients that ignore the list; enforcement never trusts the client |
| M-4 | Objects hidden by the visibility map return `not_found`, never `permission_denied`; the audit log records the true reason | No existence disclosure via enumeration; admin debuggability preserved |
| M-5 | Every content response carries a uniform **trust block** per doc and **refs** (`kb_ref` commit SHA, `snapshot_ref` canonical-body hash per system) | Trust is data, not prose; mid-session drift is detectable; every answer is attributable to a KB version |
| M-6 | Search is deterministic lexical + structured (FQNs, titles, aliases, front-matter fields); no embeddings, no model artifacts in v1 | "No LLM in the product" includes no model files to ship, scan, and update in air-gapped VPCs |
| M-7 | Responses are token-budget-shaped: hierarchical tools return one-liners + refs, `get_*` tools return full docs; nothing returns directory dumps | Preserves the ~5–10K-token retrieval path (KB spec §11) as a server-side property, not agent discipline |
| M-8 | Every call is audited: identity, tool, argument digest, result metadata, decision (allowed/denied/filtered) | The audit trail is the measurement instrument (product spec §11) and fault-ledger class-1 input (HLR §6) |

## 3. Session and enforcement model

A session is established over streamable HTTP with OAuth against the customer IdP; the MCP server resolves `identity = {subject, roles[], display}` from the token on **every** call (no session-cached roles — revocation takes effect immediately). The active **profile** is bound at connection time from the client's profile-compiled config, but the server independently validates that the user's roles permit that profile (`profiles/*.yaml` `roles:` list); a role/profile mismatch fails the connection, not individual calls.

Per-call decision: `allowed(tool, args) ⇔ tool ∈ profile.tools.allow ∧ system/target qualifiers match (execute_sql:supabase grants supabase only) ∧ visibility(roles, object) for content tools`. Profile `limits` (row_cap, timeout_s) are injected into the guardrail envelope (capability spec §4) — the client never supplies guardrails.

**Amendment (D-71.1 / security review #2 F2, 2026-07-21) — visibility governs the execution surface.** The qualifier "for content tools" above is **struck**: `visibility(roles, object)` applies to every tool that names an object, `validate_sql` and `execute_sql` included. The M-4 map is therefore an access control over data, not only over documentation — a caller who cannot read *about* an object cannot read *from* it. Rationale: the pilot's only execute-granted profile is Steward with `visibility: ["**"]`, so the two surfaces coincide today and diverge the moment M3 gives a Reporter-class profile execute (plan §6.3); an operator reading `roles.yaml` should not have to know that the file governs one surface and not the other. Enforcement is specified in §6.6 (validation) and §5 (carried to execution). This narrows the surface only — no statement that passed before passes less, for any caller whose scopes already covered it. **This does not relieve the deployment obligation** that a profile granting execute be paired with a database role scoped no wider: the KB map is our gate, the database role is the wall, and a wall is not replaced by a gate.

**Read consistency (M-5):** each call reads the KB at the default branch's merged HEAD and the latest accepted snapshot per system. Responses carry both refs. `execute_sql` additionally cross-checks the validation token's pinned `snapshot_ref` (§5) — the one place where staleness blocks rather than warns.

## 4. Common response envelopes

**Refs** (every response): `{"kb_ref": "<commit-sha>", "snapshot_ref": {"supabase": "sha256:…", "ga4": "sha256:…"}}`.

**Trust block** (per doc returned):

```json
{ "status": "verified", "last_verified": "2026-07-11 (a.demir)",
  "written_against": "sha256:…", "current_hash": "sha256:…", "hash_match": true,
  "contamination": null,
  "agent_guidance": "use-freely" }
```

`agent_guidance` ∈ `use-freely | warn-user | refuse-unless-override`, computed server-side from status per KB spec §5 — the skill trust behaviors (HLR §7.3) key off this field, so the mapping lives in exactly one place. `hash_match: false` on a `verified` doc means drift landed after the last sync classification run (rare race); served as `warn-user`.

**Amendment (D-66.4 / security review #1 MCP-R9, 2026-07-17) — snapshot provenance and render-lag.** The trust block of every machine doc carries `snapshot_ref` — the canonical-body hash of the snapshot the served facts come from. When those facts come from a snapshot **newer than the one pinned at the merged render** (`.contextlayer/snapshots/<system>.json` at KB HEAD — i.e. a sync PR is still unmerged), the block MUST signal it: `render_lag: true` and `agent_guidance` at least `warn-user`. Rationale: snapshot acceptance (runner + J-6) is the only gate on the facts surface and bypasses human PR review; the provenance and the lag must be visible to the consuming agent, not inferable. Additive to the §4 block; absence of `render_lag` reads as `false`.

## 5. Validation-token flow (M-2)

```
validate_sql ──ok──► { verdict, validation_token }        token = signed{
                                                            statement_sha256, system,
execute_sql(sql, system, validation_token)                  snapshot_ref, subject,
   gateway verifies: signature ∧ statement hash matches     profile, exp (default 300s) }
   ∧ subject matches ∧ snapshot_ref still current
        └─ mismatch → error `revalidate_required` (never silent re-validation)
```

Tokens are server-signed (key in ops Postgres, rotated), single-system, and bound to the subject — not transferable between users or sessions. Expiry/`revalidate_required` is cheap by design: re-validating is one call. The token also rides into the audit record, linking every execution to the exact validation verdict that authorized it.

**Amendment (D-71.1 / security review #2 F2, 2026-07-21) — the token carries the resolved allow-set.** The signed payload gains `objects`: the exact set of object FQNs `validate_sql` resolved the statement against (§6.6). Before enqueue, `execute_sql` re-checks **every** member of that set against the caller's *current* visibility scopes; any member now hidden refuses the call with `not_found`, worded as in §6.6, and audits `decision: filtered` with the true reason.

Why a recheck rather than the existing pin: `snapshot_ref` pins the **facts** surface, and visibility is not in it. The map lives in the KB (`.contextlayer/roles.yaml` at `kb_ref`), so revoking a caller's access to an object changes no snapshot and advances no `snapshot_ref` — a token minted a moment before the revocation would verify cleanly against every §5 binding and execute. **The allow-set recheck is the mechanism that catches a mid-token visibility change; the `snapshot_ref` check cannot and is not asked to.** The two are complementary: `snapshot_ref` catches the schema moving, `objects` catches the caller's rights moving.

Re-resolving the statement at execute would be the alternative and is deliberately not done — §6.7 executes tokens, it does not form second opinions about SQL. Re-checking a signed list of names is not re-validation.

A token whose payload carries no `objects` claim is **not honoured** (`revalidate_required`): the claim is required, not optional, so a token minted before this amendment cannot outlive it. The TTL bounds that to one re-validation within 300 s.

## 6. Tool reference

Gating column: R = read/resolve set (all profiles), V = validate, X = execute (system-qualified), P = publish (target-qualified), F = flag, S = steward-only.

### 6.1 `search_context(query, limit=10)` — R

Resolves plain-language intent to entities, metrics, tables, and docs. Deterministic ranking (M-6): exact FQN/alias match ≫ title match ≫ front-matter field match ≫ body lexical score; entity and metric hits boosted above raw tables (they are the routing layer). Results are visibility-filtered (M-4 — filtered hits are simply absent).

Response items: `{ref_kind: entity|metric|table|view|api_object|doc, path, fqn?, one_liner, trust: <block>}` — one-liners only (M-7); the agent follows with `get_*`. Zero or all-low-confidence results emit a deterministic fault-ledger coverage-gap event (HLR §6 class 1) server-side — no agent cooperation required.

### 6.2 `get_entity(name)` — R

Full entity doc (human-owned) + rendered `maps:` routing table + blend keys, with trust block. `not_found` lists nearest aliases as suggestions (from the search index, visibility-filtered).

### 6.3 `get_table(system, name)` — R

Bundles the machine doc (facts at current snapshot) and the human doc (semantics) when present, each with its own trust block; machine content is always served from the *latest* snapshot even if the rendered file lags a sync PR (the snapshot, not the render, is authority for facts). Reverse-FK "referenced by" and hot/stub flag included. Serves any object kind despite the name (`get_table` on a view or API group roster entry works; name kept for surface stability).

### 6.4 `get_metric(name)` — R

Metric doc with `implementations` per system and certification trail. Only `status: verified` metrics are flagged `certified: true`; the `report` skill treats everything else as requiring a warning.

### 6.5 `get_lineage(object, direction=upstream|downstream|both, depth=3)` — R

Walks `lineage/graph.json` from the FQN. Returns nodes + edges with `{operation, columns?, evidence_tier}` and, per node, doc trust where docs exist. Depth capped at 10; cycles reported, not traversed. Dangling edges (capability LP-3) are served flagged. This is the "why doesn't this match the source system" tool.

**Amendment (D-66.3 / security review #1 P-E, 2026-07-17) — visibility applies node-by-node.** The M-4 visibility map applies to **every node and every edge in the walk**, not just the entry object: a node the caller's roles cannot see is **omitted** from the response together with all edges touching it — never masked-but-revealed (no placeholder nodes, no redacted FQNs, no edge stubs into hidden territory). The walk does not continue *through* a hidden node. An entry object the caller cannot see returns `not_found` per M-4. The audit record carries the true filtered reason.

### 6.6 `validate_sql(system, request)` — V

`request`: `{dialect: sql, statement}` or `{dialect: api, operation, body}` per capability CI-6; dialect must match the system's class. Deterministic checks against the latest snapshot: every referenced object/column exists (SQL: parse + resolve; API: dimensions/metrics ∈ documented surface, compatibility rules from connector docs), statement class is SELECT-only (SQL), and per-system conventions (`conventions.md` machine-readable guardrail section) hold.

Response: `{verdict: pass|fail, findings: [{severity, code, ref, message}], validation_token?}` — token only on `pass`. Repeated failures against the same object emit the class-1 doc/schema-mismatch fault event.

**Amendment (D-71.1 / security review #2 F2, 2026-07-21) — resolution runs against the caller's visible surface.** `validate_sql` resolves the request against the objects the caller can see, not against the whole snapshot: the visible surface is the input to resolution, not a filter applied to its output. Consequences, all of them deliberate:

- A statement referencing an object hidden from the caller **fails**, and no token is issued. The failure is `unknown_object` (SQL) or `unknown_dimension`/`unknown_metric` (API dialect, applied to the documented GA4/GSC field surface exactly as MT-8 applies it to undocumented fields).
- The refusal is **indistinguishable from the object not existing** — same `code`, same `ref`, same `message`, byte for byte. This is M-4's non-disclosure rule reaching validation: `validate_sql` must not become the enumeration oracle that `get_table` refuses to be. It follows that the caller is told an object "does not exist in the latest accepted snapshot" when it does exist; that wording is the point, not an inaccuracy to be fixed later.
- A statement touching several objects is refused if **any one** of them is hidden — a JOIN of one visible and one hidden table is refused, citing the hidden one exactly as it would cite a misspelled one. There is no partial validation and no hint that the rest of the statement was fine.
- Column resolution never widens the surface: a hidden object's columns are hidden with it, so no column check can confirm a hidden object's shape.
- The **audit record carries the true reason** — `decision: filtered`, the hidden FQNs, and the fact that they resolve in the full snapshot. M-4's second half is what keeps this debuggable: the caller cannot tell the two cases apart, the steward always can.

The resolved set is signed into the validation token as `objects` (§5), which is what carries this decision to `execute_sql`.

### 6.7 `execute_sql(system, request, validation_token)` — X

Verifies the token (§5) — including the allow-set recheck against current visibility added by the D-71.1 amendment — injects profile guardrails, enqueues an interactive `execute` job, awaits the result (job JC-10 latency budget). Response: the capability §6 result shape + refs; `truncated` passed through untouched (CI-7). Errors surface the capability code (`timeout`, `row_cap`, `quota_exhausted`, `schema_mismatch` → also fault-ledger).

### 6.8 `publish_report(artifact, target)` — P

Role→workspace check, then an interactive `publish` job. Response: capability §8.2 result verbatim (`mode`, `created`, `pending_human_steps`, `backing`). Before enqueue the server re-checks `artifact` coherence: every metric/dimension identifier it cites must resolve in the KB (`config_error` otherwise) — a report may not cite context that doesn't exist.

**Amendment (report-authoring spec §12.3 / D-91, 2026-07-29) — the mode contract for api-class targets.** For a target whose registered connection declares `create_report: api` (the connection registration stores the adapter's publish flags per capability CI-5), `publish_report` takes a required `mode` argument, `deliver_model | attest`, and publishing becomes a two-call contract (report-authoring spec §4/§7). Template-link and full targets keep the existing single-shot contract unchanged; `mode` supplied for them is `invalid_argument`, as is a missing `mode` for an api target.

Both modes run every existing gate above — structural validation including the formats §4.7 `layout` schema (`layout` in the §4.7 shape is *required* for api targets, with its `trust_element`), MT-10 visible-surface ref resolution, certification honesty, documented-blend-key checks, and F-7 re-validation — plus:

- **`deliver_model`** — after gates pass, the server executes each artifact query through the §6.7 gateway path (interactive `execute` jobs under the caller's identity and profile guardrails, trigger `gateway`, linked to this call's audit record). A result with `truncated: true` refuses the delivery (`guardrail`-class, naming the row cap and the reporting-view escalation) — a capped result must never quietly become "the model" (capability CI-7). The publish job then carries the results to the adapter (capability §8.2 amendment); on success the server persists the **delivery record** `{artifact_id, revision, target, workspace_id, dataset_id, tables as delivered, results}` — latest per `(artifact_id, target)`, superseded on the next successful delivery, retained so the next delivery can restore complete-or-previous (capability `previous`) — and returns the §8.2 `deliver_model` result with refs. The formats §4.6/FA-3 result-reuse short-circuit does **not** apply to api-target `deliver_model`: an unchanged content hash is the data-only-revision case (report-authoring RA-8) and re-executes/re-pushes under the same revision number and ids.
- **`attest`** — takes `attestation: {report_id, definition_hash}`. Requires a prior successful delivery for the same `{artifact_id, revision, target}`; absent → refused `revalidate_required`-class (report-authoring §8: prevents attesting stale work). `definition_hash` must be well-formed (`sha256:` + 64 lowercase hex); when the artifact's `layout.pbir_hash` is present it must equal the submitted `definition_hash` (the artifact is the durable record of what shipped). On success the server records the **attestation row** `{artifact_id, revision, target, workspace_id, dataset_id, report_id, definition_hash, verified_at, audit_ref}` — the F-4-style permanent record — writes the F-4 `report` node and gateway-tier edges for the attested report, and returns the §8.2 `attest` result carrying the workspace report URL.
- A delivery whose revision never reaches `attest` is **delivered-but-unattested**: a loud dangling state, listed by the ops surface (`cli publish deliveries` marks dangling deliveries) — never silent.
- Audit (M-8) is unchanged in shape: each mode call is a separate audited `publish_report` record; `result_meta` carries the mode. Rate limiting counts each mode call as a publish call (§7) — an api-target report costs two.

MT-10's wording extends to layout: a layout naming a table no artifact query delivers is refused pre-enqueue (`invalid_argument`, formats §4.7).

### 6.9 `report_freshness()` — R

Estate summary from ops state + KB statuses: per system {last snapshot at, trigger, next scheduled}, doc-status counts (verified/draft/stale/contaminated), open sync PRs, snapshot-age warnings per the P1 mode-3 threshold. The tool behind "how current is my context?" — and the dashboard KB Health module renders the same query.

### 6.10 `flag_gap(kind, description, object?, proposal?)` — F

`kind` ∈ `missing_doc | missing_join_path | uncertified_metric | missing_entity | schema_mismatch | capability_gap | result_disputed | enrichment_request | other`. Server attaches identity, session, profile, and current refs; writes the fault-ledger event, deduplicating into an issue (ledger spec §6); responds with `{issue_id, occurrences, routed_to}` so the skill can tell the user who was notified and whether the gap was already known (HLR §9.5 honest-failure rule; ledger L-6). Rate-limited per session to prevent flag spam — dedup makes residual spam harmless.

**Amendment (D-101.3, 2026-08-05) — the `proposal` argument.** `proposal` (optional string) carries the caller's *suggested content* for the gap being filed, so a session-side user can submit a knowledge request without the dashboard — the same queue, a different door. Server-side treatment is identical to `description`, with no exception carved for it: the **LED-R2** scrub runs over it before storage (quoted literals, numbers and identifier-like digit runs, email addresses and similar value-shaped tokens dropped) under the same server-enforced length bound, and it is stored on the event as `detail.proposal`, rendered markdown/HTML-inert wherever it is displayed (**LED-R5**). Identity handling is untouched: **LED-R3** stands — the server sets subject, session, profile and refs, and a client-supplied subject is ignored.

The enum's `enrichment_request` is the kind that carries the verdict lifecycle (ledger §4 amendment: `open → approved | rejected(reason)`, `approved → batched → resolved`). It is additive to the enum on the `result_disputed` precedent (SK-5) — a class-3 kind reachable through this tool, because a queue only browser users can file into is not the queue D-101 adopted. `proposal` is accepted on any kind and stored on the event as drafting evidence, but only `enrichment_request` opens a request with verdict states.

The response shape, the rate limit (§7), and the K-FAIL discipline are all unchanged: a proposal never substitutes for naming the gap, and the filer is told the same three things every filer is told — recorded, already-known-or-not, and who was notified.

### 6.11 `list_gaps(status=open|triaged, kind?, system?, limit=20)` — S

Steward-gated triage reads (fault-ledger spec §8): returns issues as `{issue_id, kind, title, object_fqn?, occurrences, distinct_subjects, first_seen, last_seen, links}`. Read-only; visibility-filtered per M-4 (issues attributed to objects the caller's role cannot see are omitted). This is the enrich skill's scope-selection priority-1 input (skill spec §6 S1).

## 7. Errors and limits

Tool errors: `{code, message, detail?}` with codes `not_found | invalid_argument | permission_denied (profile-level only, per M-4) | revalidate_required | guardrail | upstream_error (job failed; job error embedded) | rate_limited`. Per-identity rate limits (defaults, configurable in `.contextlayer/`): 120 read calls/min, 20 validate/min, 6 execute/min, 4 publish/hour, 10 flag_gap/session. Limits exist for source protection, not licensing — messages say so.

## 8. Audit contract (M-8)

One record per call: `{ts, subject, roles, profile, tool, args_digest, refs, decision, duration_ms, result_meta, setup_stamp}` where `result_meta` is tool-specific (rows returned + truncated for execute; created URLs for publish; verdict for validate; ledger_id for flag_gap) and `args_digest` is a hash — full SQL/intent text is stored only for execute/validate/publish (the product-spec §8 audit fields), not for reads. Retention and export are dashboard-Audit-module concerns; the record shape is fixed here.

**Amendment (D-108.4, register item PA-3, 2026-08-06) — `setup_stamp`, additive.** The record carries the compiled-setup stamp the session presented on its MCP URL (§5's `?setup=`), or the literal `unstamped` when it presented none. Rationale: the staleness mechanism (PA-2, D-107.2) compares the presented stamp at `initialize` and says so in the server's `instructions`, but that comparison was durable nowhere — an audit row could show *that* a session ran and not *which setup it ran*, so "the session was current" was an inference from timestamps rather than a fact in the record. The value is the client's claim about itself, recorded verbatim and never trusted for any decision: enforcement remains (roles ∩ profile) recomputed per call (M-3), and nothing reads this column to permit or deny anything. It is written on every audited call including the denied-connection rows, because a refused connection is exactly the row an investigator most wants it for.

## 9. Conformance tests

| # | Test | Implements |
|---|---|---|
| MT-1 | `tools/list` for a Reporter profile shows exactly the profile's allowlist; a hidden tool called directly is denied | M-3 |
| MT-2 | Visibility-hidden object: `get_table` → `not_found`; audit records the filtered reason | M-4 |
| MT-3 | `execute_sql` without token / with expired token / with tampered statement / from a different subject → `revalidate_required` or denial; never executes | M-2, §5 |
| MT-4 | Snapshot updated between validate and execute → `revalidate_required` | §5 |
| MT-5 | Client-supplied guardrails in arguments are ignored; profile limits appear in the executed job payload | §3 |
| MT-6 | Every content response carries refs + trust blocks; `agent_guidance` matches KB-spec §5 semantics table | M-5, §4 |
| MT-7 | Zero-result search and repeated validate failures produce class-1 ledger events without any `flag_gap` call | §6.1, §6.6, HLR §6 |
| MT-8 | API-dialect validate rejects an undocumented GA4 dimension; SQL-dialect rejects a dropped column, citing the object | M-1 |
| MT-9 | Role revocation at the IdP takes effect on the next call (no cached-role window) | §3 |
| MT-10 | `publish_report` with an artifact citing a nonexistent metric fails before enqueue | §6.8 |
| MT-11 | `validate_sql` on a table hidden from the caller fails with the *same* finding a nonexistent table produces (code, ref, message) and issues no token; the identical statement from a caller who can see it passes | §6.6 amendment, M-4 |
| MT-12 | A JOIN of one visible and one hidden table is refused; an API request citing a hidden custom dimension is refused; the audit records `filtered` with the true reason in both | §6.6 amendment, M-4, M-8 |
| MT-13 | A token issued while an object was visible is refused at `execute_sql` after the map hides it — caught by the §5 allow-set recheck, with the snapshot unmoved — and a token carrying no `objects` claim is not honoured | §5 amendment |
| MT-14 | `flag_gap(kind: enrichment_request, proposal: …)` with a canary value and a markdown payload in the proposal: the stored `detail.proposal` is scrubbed and length-bounded exactly as `description` is, a client-supplied subject is ignored in favour of the server-resolved one, and the response is the unchanged `{issue_id, occurrences, routed_to}` | §6.10 amendment, LED-R2/R3 |

## 10. Amendments to other specs (additive)

> **Status: applied.** All items below were folded into their home specs in the consolidation pass; this section remains as the change record.

1. **KB repository spec §4.3/§4.4:** entity and metric front-matter gain an optional `aliases: [string]` list, indexed by search (M-6). Additive; KB CI schema updated accordingly.
2. **Capability interfaces spec §12 CI-B:** resolved per ruling M-1 — closed in that spec's register with a pointer here.
3. **KB repository spec §7 conventions skeleton:** `conventions.md` gains a machine-readable guardrail section (fenced YAML) consumed by `validate_sql` per-system checks (§6.6). Additive to the bootstrap template.

## 11. Open decisions (spec-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| MC-1 | Semantic search (embeddings) to improve recall beyond lexical + aliases | Not in v1 (M-6); alias curation + benchmark-driven synonym growth | If phase-2 benchmark shows table-selection recall is the accuracy bottleneck |
| MC-2 | Validation-token TTL | 300 s | If long drafting sessions cause revalidation friction (it's one cheap call) |
| MC-3 | `get_table` response size for very wide tables (500+ columns) | Full column table always (facts are facts); wide tables paginate columns at 300 with continuation | First SAP-scale estate |
| MC-4 | Read-tool rate limits per profile class vs global per-identity | Global per-identity defaults, profile-overridable | Pilot telemetry |
| MC-5 | Serving machine facts from snapshot vs rendered file when a sync PR is unmerged | **Closed** (D-66.4) — snapshot authority affirmed by security review #1; MCP-R9 render-lag signal added to §4 as the condition of closure | — |
