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
| SS-5 | CHECK constraints in the snapshot | **Open — elevated, decision scheduled CP-8** | Dropped at the boundary; proposed additive path: hash-included `stats.checks` (`pg_get_constraintdef` strings) on `table` | **Trigger fired 2026-07-27 (D-86.3b).** The CP-7 enrichment run needed these facts and read `pg_constraint` out of band; worse, the gap had already produced a false claim — `deploy/reporting-views.sql` and D-81's rationale called `ai_runs.status` unconstrained free text when a CHECK enforces `pending \| completed \| failed`. Our blind spot was mistaken for the source's vocabulary being open. Does not block M3 (spec + registry amendment) |
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
| JP-6 | Runner-token scope vs producer/ops surface (review #1 P-A) | **Closed** | D-66.1: runner tokens authorize claim/start/heartbeat/complete/fail/defer only; producer/ops/read surface behind platform identity (job spec §6 amendment, built at CP-4) | — |

## KB repository (KB-A..F)

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| KB-A | Visibility granularity | Open | Per-directory (system/schema) | Intra-schema confidentiality need |
| KB-B | `external:` dependency escape hatch | Open | Allowed per entry; excluded from scans | External refs proliferate |
| KB-C | Regeneration scope per drift run | Open | Changed objects only; KB-8 guards correctness | Template changes needing estate-wide re-render |
| KB-D | Human-doc localization | Open | Out of scope v1 | First non-English deployment |
| KB-E | Grouped API doc splitting threshold | Open | Split at 200 objects per kind-group | First estate hitting it |
| KB-F | Trust semantics of repo-level human docs (`index.md`, `conventions.md`, `_notes.md`) | **Closed** | D-68 (CP-4): default affirmed — no `status` front-matter, no trust block; repo-level docs are search-indexed and visibility-checked like every doc (MCP-R15), one-liners derive from title/first line only, and no tool serves their full body in v1 | — |

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
| MC-1 | Semantic search (embeddings) | Open | Lexical + aliases only (M-6) | Baseline (BASELINE-1; v1 skipped at CP-5 per D-80.1) shows recall is the accuracy bottleneck |
| MC-2 | Validation-token TTL | Open | 300 s | Revalidation friction in long sessions |
| MC-3 | Very-wide-table responses | Open | Full columns; paginate at 300 with continuation | First SAP-scale estate |
| MC-4 | Rate limits per profile class vs per identity | Open | Global per-identity defaults, profile-overridable | Pilot telemetry |
| MC-5 | Snapshot-vs-rendered-file authority for facts | **Closed** | D-66.4: snapshot authority affirmed by security review #1; MCP-R9 render-lag signal amended into MCP spec §4 and built at CP-4 | — |

## Skill specifications (SP-1..5)

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| SP-1 | Execute-without-resolution heuristic as class-1 detector | Open | Shipped log-only, disabled by default (ledger §5) | Pilot false-positive rate |
| SP-2 | Benchmark-mode waiver leakage | **Closed (conditional at M1 sign-off)** | D-66.8: non-issue — waiver keys on the server-resolved profile only (MCP-R2); closure gated on MCP-R2 + MT-1 green, satisfied by the CP-4 suite; final sign-off with the M1 live demo evidence | — |
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
| FL-E | `distinct_subjects` privacy stance | **Closed** | D-66.5: counts-only affirmed (LED-R7); LED-R2 scrub + LED-R5 render neutralization amended into ledger spec §3.3/§10 and built at CP-4 | — |

## Onboarding playbook (OB-1..4)

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| OB-1 | Compiled read-only KB bundles | Open | Not built until a real offline consumer exists | First air-gapped-site / no-MCP-team requirement |
| OB-2 | Entity draft authorship (skill vs R5) | Open | Skill-drafted, R5-paired, customer-certified | After 2–3 onboardings |
| OB-3 | Staged drift drill as shipped fixture | Open | Ship a standard drill fixture with the product | Build during phase 4 |
| OB-4 | Onboarding duration targets | Open | Measure first three; no promises before data | Third onboarding |

## Platform architecture (PA-*)

The architecture spec carries no spec-local register of its own, so items whose home is that document are tracked here directly (the same situation as the sync spec's SO-* items, which were never carried over at consolidation).

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| PA-1 | One-click setup export — how a compiled profile bundle (`.mcp.json` + `CLAUDE.md` + skills) reaches a user's own machine. §5 defines compilation and §6 lists the export as a Agent-Profiles dashboard action, but no delivery path exists outside the dashboard: the core serves `/mcp`, `/.well-known/*` and `/v1/*` only, and its MCP surface implements tools, not resources | Open | Operator-mediated file copy (`scp`, shared drive, USB). The bundle carries no credential, so out-of-band copying is safe if inconvenient | **Evidence, D-88.2:** the first second-machine onboarding hit this immediately — the M3 gate demo had to fall back to `scp.exe` from a Windows client. Trigger: the dashboard build, or the first real customer onboarding, whichever comes first. Distributing the bundle is a product surface, not an operator workaround |

## Plan-level (BASELINE-*)

Items whose home is the development plan rather than a spec; home ruling recorded in `DECISIONS.md`.

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| SUPPRESS-1 | Small-cell suppression threshold for aggregate reporting output (the `reporting.*` views expose counts on a ~24-user estate; a cell of 1–2 can identify even though no column names anyone). Home spec undecided between the lineage/artifact-formats spec and the MCP profile limits — settled at the trigger, not before (D-86.4) | Open | None. Every `reporting.*` human doc warns that low cells are sensitive rather than reportable; no numeric threshold is defined and none is enforced anywhere in the pipeline | **Before any report reaches an audience outside the team** — first external viewer, first shared dashboard, first exported artifact leaving the owner's own hands. The M3 pilot demo's audience is the owner reading their own estate, which is why M3 proceeds without one |
| BASELINE-1 | Full KB-value baseline via the benchmark skill (three-condition comparison; D-80.1 — v1 skipped at CP-5, standing constraint: no quantitative KB-value claims in customer or demo material until it exists) | Open | Rig re-runnable as landed (driver + preflight + conditions); no numbers claimed meanwhile | Before CP-8 go/no-go, or before the first external customer conversation that would benefit from numbers, whichever first |
