# Master Open Decisions Register (v1.0)

Status: authoritative tracking view over all spec-local registers, consolidated at spec-set v1.0. **Maintenance rule:** this register is the authority for *status*; spec-local registers remain as in-context snapshots and are reconciled here at each consolidation pass. New items are added in their home spec first, then registered here. Status values: **Open** (provisional default in force) · **Partial** (scope reduced, remainder open) · **Closed** (decided; pointer to the ruling).

Totals at v1.0: 48 items — 45 open, 1 partial (OD-2), 1 closed (CI-B), 1 standing rule (OD-5, exercised once). Post-v1.0 additions: SS-5–SS-7 (entered via the snapshot spec's §10 register during task 1.2); FM-6 (formats spec §7, task 1.9); PA-1/PA-2 (architecture spec, no spec-local register); SUPPRESS-1 and BASELINE-1 (plan-level); **SO-A–SO-G** (sync-orchestrator spec §13, written after consolidation and never carried over — added by ruling D-96.4).

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
| JP-4 | Webhook ingestion endpoint | **Closed** | Sync-orchestrator spec §12.1: adopted as that spec's §4.2 — `/v1/hooks/{system}`, path identity, per-hook shared secret, body ignored. Built and exercised at CP-3 (D-64: `sync hook set` → 202; rotate → old secret 401). The spec declared this Closed and said "master register updated"; the master row was never actually changed — reconciled here (D-96.4 bookkeeping batch) | — |
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

## Capability interfaces (CI-A..F)

| ID | Item | Status | Default / resolution | Revisit trigger |
|---|---|---|---|---|
| CI-A | Streaming for large `execute` results | Open | Inline + `truncated` + narrow-your-query guidance; reporting views absorb big recurring pulls | Legitimate >cap interactive needs in pilot |
| CI-B | API-request validation as separate tool | **Closed** | MCP ruling M-1: one `validate_sql`, dialect-switched | — |
| CI-C | Publisher probe cadence | Open | On configure + manual re-test | Stale effective flags cause failed journeys |
| CI-D | Incremental harvest cursors | Open | Reserved field; v1 full-harvests, dedupe by content_hash | First large Drive/Confluence estate |
| CI-E | SDK↔protocol↔snapshot version matrix | Open | Release notes carry it; manifest declares all three | Multi-version fleet reality |
| CI-F | Publish depth for Looker Studio — `template_link` only in v1 | **Closed** (supersession) | D-91.6 / D-92.1: closed by supersession — the escalation this item was waiting for arrived as the ruling itself. M3's target moved to an api-class publisher where the platform delivers the data and no per-report manual re-point exists; evidence pointer: `specs/report-authoring-spec.md`. The finding stands unchanged for the Looker leg, which remains on main as a secondary target carrying this documented limit (a database-backed source cannot be prefilled by a link at all — PostgreSQL is not a Linking API connector, D-89 — so every Looker-published report keeps its manual re-point + password step; GA4/GSC prefill fine) | — |

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
| OB-3 | Staged drift drill as shipped fixture | **Closed** | Sync-orchestrator spec §12.2: the drill fixture is a shipped artifact (that spec's §9), built as a CP-3 task — `fixtures/drill/` + `core/test/sync-drill.test.ts` (SO-4/SO-8). The spec declared this Closed and said "master register updated"; the master row was never actually changed — reconciled here (D-96.4 bookkeeping batch). **Note the scope:** what closes is the *fixture*, not the playbook's gate item 7, whose human half (R2 runs `review-sync` → repair PR → docs re-verified) has never been rehearsed and is blocked on `review-sync` being built (D-96.3c, Track A-1) | — |
| OB-4 | Onboarding duration targets | Open | Measure first three; no promises before data | Third onboarding |

## Sync orchestration (SO-*)

Home: `sync-orchestrator-spec.md` §13. That spec was written after the v1.0 consolidation, so its register was **never carried over** — noted unfixed in D-84.2, added here by ruling D-96.4's bookkeeping batch. Until now the authoritative status view had no row for any of these, including SO-F, which had already cost the pilot two days of silently unpublished drift.

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| SO-A | Webhook debounce window beyond job dedupe + run coalescing | Open | None — dedupe and single-flight already bound work to ≤2 runs per storm | CI storms measurably churning snapshot jobs at a source with quota cost |
| SO-B | Auto-merge for additive-only sync PRs | Open | Off; the PR carries a `sync:additive-only` label so customers can wire their own automation; **the product never merges** | First customer drowning in trivially-mergeable PRs |
| SO-C | Webhook↔repo topology (monorepo emitting for several systems) | Open | One hook per system; a monorepo's CI calls each relevant hook | First customer whose CI cannot target hooks per system |
| SO-D | Run acquisition budget | Open | 2 h default, config in `sync-policy.yaml` | First estate whose snapshots legitimately exceed it |
| SO-E | Estate-wide re-render as a run mode (`regen-all`, pairs with KB-C) | Open | Manual dashboard action producing a dedicated sync PR; never automatic | First template change requiring it in production. **Phase-2 inventory item U-14/U-17** (CP-8 report §5) |
| SO-F | Configured-but-disabled sync is silent in single-instance ops | Open | None — `/healthz` already reports `sync_enabled`; the gap is that nothing consumes it where there is no dashboard or alerting surface | **Fired once already** (D-84.2): the pilot ran two days with `SYNC_ENABLED=0` after a compose env-precedence slip, drift accruing unpublished, health green throughout. CP-8 disposition: **build the consumer** in the dashboard's KB-Health view (report §Part 2, Track B-1), not merely re-state the default. Second silent-off incident, or the first deployment where the operator cannot eyeball the process env, whichever first |
| SO-G | Refresh cadence for GA4/GSC data delivered into an api-class publish target | Open | None in v1: models are refreshed only by an explicit re-publish (a skill/agent-triggered revision, per RA-E). `scheduled_refresh: no` is declared on the Power BI connection's `publish.flags`, so the limitation is visible in the registration rather than implied | First standing report whose viewers depend on it being current, or the first "why is this report showing last week's numbers". Decide together with RA-G (lifecycle/teardown) and RA-D — the CP-8 review found the three are one design conversation |

## Platform architecture (PA-*)

The architecture spec carries no spec-local register of its own, so items whose home is that document are tracked here directly (the sync spec's SO-* items were in the same situation until D-96.4 added the section above).

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| PA-1 | One-click setup export — how a compiled profile bundle (`.mcp.json` + `CLAUDE.md` + skills) reaches a user's own machine. §5 defines compilation and §6 lists the export as a Agent-Profiles dashboard action, but no delivery path exists outside the dashboard: the core serves `/mcp`, `/.well-known/*` and `/v1/*` only, and its MCP surface implements tools, not resources | Open | Operator-mediated file copy (`scp`, shared drive, USB). The bundle carries no credential, so out-of-band copying is safe if inconvenient | **Evidence, D-88.2:** the first second-machine onboarding hit this immediately — the M3 gate demo had to fall back to `scp.exe` from a Windows client. Trigger: the dashboard build, or the first real customer onboarding, whichever comes first. Distributing the bundle is a product surface, not an operator workaround |
| PA-2 | Compiled-bundle staleness (filed D-94.3; sits beside PA-1 as the other half of the setup-export design, §5). The bundle's `CLAUDE.md` tool list is read by the session as the statement of what it may do, so it acts as **de facto client-side permissions**: it cannot widen the server allow-set (which is authoritative per call) but it can narrow what the session will even attempt. A bundle compiled before a profile change silently withholds capability the profile now grants | Open | Recompile and re-copy the bundle after any profile change; the runbook says so at 4.7. No product mechanism enforces it | **Evidence, 2026-07-29:** the interrupted M3 gate attempt — the reporter's bundle predated the `publish_report:powerbi` grant, so the session declined to build the report and filed gap `6473a5f1` instead (`results/cp7-gate/interrupted-run-2026-07-29/`). Trigger: the setup-export design (PA-1) — compile-on-profile-change, or a staleness warning the session can see, belongs in it |

## Plan-level (BASELINE-*)

Items whose home is the development plan rather than a spec; home ruling recorded in `DECISIONS.md`.

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| SUPPRESS-1 | Small-cell suppression threshold for aggregate reporting output (the `reporting.*` views expose counts on a ~24-user estate; a cell of 1–2 can identify even though no column names anyone). Home spec undecided between the lineage/artifact-formats spec and the MCP profile limits — settled at the trigger, not before (D-86.4) | Open | None. Every `reporting.*` human doc warns that low cells are sensitive rather than reportable; no numeric threshold is defined and none is enforced anywhere in the pipeline | **Before any report reaches an audience outside the team** — first external viewer, first shared dashboard, first exported artifact leaving the owner's own hands. The M3 pilot demo's audience is the owner reading their own estate, which is why M3 proceeds without one |
| BASELINE-1 | Full KB-value baseline via the benchmark skill (three-condition comparison; D-80.1 — v1 skipped at CP-5, standing constraint: no quantitative KB-value claims in customer or demo material until it exists) | Open | Rig re-runnable as landed (driver + preflight + conditions); no numbers claimed meanwhile | Before CP-8 go/no-go, or before the first external customer conversation that would benefit from numbers, whichever first |
