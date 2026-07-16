# Master Open Decisions Register (v1.0)

Status: authoritative tracking view over all spec-local registers, consolidated at spec-set v1.0. **Maintenance rule:** this register is the authority for *status*; spec-local registers remain as in-context snapshots and are reconciled here at each consolidation pass. New items are added in their home spec first, then registered here. Status values: **Open** (provisional default in force) · **Partial** (scope reduced, remainder open) · **Closed** (decided; pointer to the ruling).

Totals at v1.0: 48 items — 45 open, 1 partial (OD-2), 1 closed (CI-B), 1 standing rule (OD-5, exercised once). Post-v1.0 additions: SS-5–SS-7 (Open, entered via the snapshot spec's §10 register during task 1.2).

## High-level requirements (OD-*)

| ID | Item | Status | Default / resolution | Revisit trigger |
|---|---|---|---|---|
| OD-1 | Silent semantic errors have no in-line detector | Open | Stated limitation; mitigate via certified metrics, trust signals, benchmark-in-CI | Pilot shows correctness failures the benchmark misses |
| OD-2 | Class-1 detector rule set | **Partial** | Rules + defaults are ops configuration (ledger §5); open scope = threshold values | First month of pilot audit data |
| OD-3 | Freshness-warning threshold (P1 sync mode 3) | Open | Snapshot age > 30 days ⇒ warning (configurable) | Per customer at onboarding |
| OD-4 | Explorer profile publish rights | Open | Off by default, per-customer opt-in | First customer request |
| OD-5 | New MCP tools | Standing rule | Exercised once: `list_gaps` approved (ledger §12); every proposal enters here first | Any proposal |

## Snapshot schema (SS-*)

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| SS-1 | Cross-engine type normalization in diffing | Open | Types are source-native; cross-engine comparison out of scope | First source migrating between engines |
| SS-2 | Sample values in snapshots | Open | Not in v1; would be a separate hash-excluded `stats` registration, opt-in + masked | Enrich quality on L1 sources insufficient |
| SS-3 | `api_property` as object kind vs envelope data | Open | Envelope (`source_properties`) | Per-property docs need ownership/hashing |
| SS-4 | Row-estimate change as usage-drift signal | Open | Ignored by diff (hash-excluded, metadata-only) | Usage-driven enrichment suggestions built |
| SS-5 | CHECK constraints in the snapshot | Open | Dropped at the boundary; proposed additive path: hash-included `stats.checks` (`pg_get_constraintdef` strings) on `table` | Enrich needs value-domain facts the connector already saw |
| SS-6 | Enum type labels in the snapshot | Open | Dropped at the boundary; proposed additive path: new `enum_type` kind with hash-included `stats.labels` (grounds SS-2's enum-decoding half without sampling) | First customer schema using native enums for report-relevant states |
| SS-7 | No-slot gaps: identity/generated markers, schema/index comments, partition key definition | Open | Dropped at the boundary (identity/generated emit `default: null`); partition key is the strongest future §4.5 candidate | An agent journey fails for lack of one of these facts |

## Job protocol (JP-*)

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| JP-1 | Core-native `execute` short-circuit vs runner routing | Open | Route through runners — one path, one audit shape | JC-10 latency misses budget in pilot |
| JP-2 | Interactive latency budget | Open | ≤ 500 ms p95 claim-to-start, warm runner | M2 measurement |
| JP-3 | Result size cap & snapshot storage | Open | 64 MB inline; Postgres storage; retain last 10 snapshots/system | First estate approaching the cap |
| JP-4 | Webhook ingestion endpoint | Open | `/v1/hooks/{system}` + per-hook shared secret; normatively owned by the sync-orchestrator spec (not yet written — see index doc) | Sync-orchestrator spec authoring |
| JP-5 | Runner autoscaling under K8s | Open | Manual replica count in v1 | Enterprise deployment sizing |

## KB repository (KB-A..F)

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| KB-A | Visibility granularity | Open | Per-directory (system/schema) | Intra-schema confidentiality need |
| KB-B | `external:` dependency escape hatch | Open | Allowed per entry; excluded from scans | External refs proliferate |
| KB-C | Regeneration scope per drift run | Open | Changed objects only; KB-8 guards correctness | Template changes needing estate-wide re-render |
| KB-D | Human-doc localization | Open | Out of scope v1 | First non-English deployment |
| KB-E | Grouped API doc splitting threshold | Open | Split at 200 objects per kind-group | First estate hitting it |
| KB-F | Trust semantics of repo-level human docs (`index.md`, `conventions.md`, `_notes.md`) | Open | No front-matter, KB-1-exempt (KB spec §4.6); MCP serves them without a trust block | CP-4/M1 MCP server session (trust-block consumer exists) |

## Capability interfaces (CI-A..E)

| ID | Item | Status | Default / resolution | Revisit trigger |
|---|---|---|---|---|
| CI-A | Streaming for large `execute` results | Open | Inline + `truncated` + narrow-your-query guidance; reporting views absorb big recurring pulls | Legitimate >cap interactive needs in pilot |
| CI-B | API-request validation as separate tool | **Closed** | MCP ruling M-1: one `validate_sql`, dialect-switched | — |
| CI-C | Publisher probe cadence | Open | On configure + manual re-test | Stale effective flags cause failed journeys |
| CI-D | Incremental harvest cursors | Open | Reserved field; v1 full-harvests, dedupe by content_hash | First large Drive/Confluence estate |
| CI-E | SDK↔protocol↔snapshot version matrix | Open | Release notes carry it; manifest declares all three | Multi-version fleet reality |

## MCP tool reference (MC-1..5)

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| MC-1 | Semantic search (embeddings) | Open | Lexical + aliases only (M-6) | Baseline v1 (CP-5 per D-62; was CP-2) shows recall is the accuracy bottleneck |
| MC-2 | Validation-token TTL | Open | 300 s | Revalidation friction in long sessions |
| MC-3 | Very-wide-table responses | Open | Full columns; paginate at 300 with continuation | First SAP-scale estate |
| MC-4 | Rate limits per profile class vs per identity | Open | Global per-identity defaults, profile-overridable | Pilot telemetry |
| MC-5 | Snapshot-vs-rendered-file authority for facts | Open | Snapshot is authority (M-5 note) | Security-review feedback |

## Skill specifications (SP-1..5)

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| SP-1 | Execute-without-resolution heuristic as class-1 detector | Open | Shipped log-only, disabled by default (ledger §5) | Pilot false-positive rate |
| SP-2 | Benchmark-mode waiver leakage | Open | Waiver keyed to server-known `benchmark` profile; AS-8 guards | Security review (expected non-issue) |
| SP-3 | Enrich batch size | Open | 10 objects | Steward PR-review ergonomics |
| SP-4 | Saved/parameterized report re-runs | Open | Out of v1; re-run = re-journey | Recurring-report demand; pairs with FM-4 (packet demand evidence recorded at CP-2, D-56; baseline numbers land at CP-5, D-62) |
| SP-5 | Skill language localization | Open | Session-language naturally; checkpoints language-neutral | First non-English pilot |

## Lineage & artifact formats (FM-1..5)

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| FM-1 | Column-level contamination walks | Open | Node-level flagging; mappings served as context | Node flags too noisy on wide models |
| FM-2 | Visual registry growth | Open | Five kinds; additions via register | First inexpressible customer report (registry verdict from packet fields recorded at CP-2, D-56; re-tested at CP-5 baseline v1, D-62) |
| FM-3 | Artifact retention | Open | All published revisions kept (audit evidence); unpersisted drafts pruned | Storage telemetry |
| FM-4 | Parameterized artifacts | Open | Defaults-only filters | Pairs with SP-4 (see SP-4's D-62 re-point) |
| FM-5 | Cross-system source-to-source lineage edges | Open | Entity-doc knowledge only; blends edge into the report node from each side | Reconciliation needs source-to-source edges |
| FM-6 | Column-mapping expressiveness gaps: per-column derivation kind (sketched: optional additive `columns[].via`) + filter/join/group-key column dependencies (no `to` to attach to) | Open | Not expressible in v1; edge-level `operation` + relation-level edge carry the facts; walks node-level (FM-1) | FM-1's revisit — decide both together (entered via formats spec §7, task 1.9) |

## Fault ledger (FL-A..E)

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| FL-A | Priority scoring beyond sort order | Open | Sort by status/occurrences/last_seen | R2 says ordering misleads |
| FL-B | Notification channels | Open | Dashboard-only | First customer ask |
| FL-C | `abandoned_journey` noise floor | Open | Issue opens at ≥2 occurrences | Pilot noise measurement |
| FL-D | Causal cross-issue linking | Open | Manual `links` only | Frequent causal clusters in triage |
| FL-E | `distinct_subjects` privacy stance | Open | Counts only; identities via audit_ref under Audit roles | Security review |

## Onboarding playbook (OB-1..4)

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| OB-1 | Compiled read-only KB bundles | Open | Not built until a real offline consumer exists | First air-gapped-site / no-MCP-team requirement |
| OB-2 | Entity draft authorship (skill vs R5) | Open | Skill-drafted, R5-paired, customer-certified | After 2–3 onboardings |
| OB-3 | Staged drift drill as shipped fixture | Open | Ship a standard drill fixture with the product | Build during phase 4 |
| OB-4 | Onboarding duration targets | Open | Measure first three; no promises before data | Third onboarding |
