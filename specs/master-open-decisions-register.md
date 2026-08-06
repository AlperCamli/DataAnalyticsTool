# Master Open Decisions Register (v1.0)

Status: authoritative tracking view over all spec-local registers, consolidated at spec-set v1.0. **Maintenance rule:** this register is the authority for *status*; spec-local registers remain as in-context snapshots and are reconciled here at each consolidation pass. New items are added in their home spec first, then registered here. Status values: **Open** (provisional default in force) · **Partial** (scope reduced, remainder open) · **Closed** (decided; pointer to the ruling).

Totals at v1.0: 48 items — 45 open, 1 partial (OD-2), 1 closed (CI-B), 1 standing rule (OD-5, exercised once). Post-v1.0 additions: SS-5–SS-7 (entered via the snapshot spec's §10 register during task 1.2); FM-6 (formats spec §7, task 1.9); PA-1/PA-2 (architecture spec, no spec-local register); SUPPRESS-1 and BASELINE-1 (plan-level); **SO-A–SO-G** (sync-orchestrator spec §13, written after consolidation and never carried over — added by ruling D-96.4); **U-1..U-19 and E2** (dashboard spec §3/§9, added by D-101's register action — U-1..U-18 are the CP-8 Part 5 inventory, U-19 is new with D-101; UI-A and UI-D closed by D-103, 2026-08-05 — stack and resolution-surfacing mechanism; UI-B/UI-C/UI-E remain spec-local until one is load-bearing).

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
| SS-5 | CHECK constraints in the snapshot | **Closed by capture** | D-96.3d (2026-07-31): hash-included `stats.checks` on `table` — verbatim `pg_get_constraintdef(oid, true)` over `contype = 'c'`, lexicographically sorted, Postgres only. Snapshot spec §4.5 carries the registration record: hash-**included** because a CHECK *is* a documented meaning and a widened one must be able to contaminate a doc (the S-2 test `indexes` fails and this passes); verbatim strings, no vocabulary parsing (S-8). Closed on the evidence in D-86.3b — the gap had already produced a false claim about the customer's own estate | — |
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
| OB-4 | Onboarding duration targets | Open | Measure first three; no promises before data. **D-96.3g: BUILD the per-step instrumentation (Track A-6)** — "cannot close" is not an acceptable state for a gate item the playbook cites; the instrumentation was never built (CP-0 task 0.3). A-6's gate arms it via a timed scratch-estate rehearsal and updates this row to "armed, awaiting onboarding #2" | Third onboarding (targets); A-6 (instrumentation) |

## Sync orchestration (SO-*)

Home: `sync-orchestrator-spec.md` §13. That spec was written after the v1.0 consolidation, so its register was **never carried over** — noted unfixed in D-84.2, added here by ruling D-96.4's bookkeeping batch. Until now the authoritative status view had no row for any of these, including SO-F, which had already cost the pilot two days of silently unpublished drift.

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| SO-A | Webhook debounce window beyond job dedupe + run coalescing | Open | None — dedupe and single-flight already bound work to ≤2 runs per storm | CI storms measurably churning snapshot jobs at a source with quota cost |
| SO-B | Auto-merge for additive-only sync PRs | Open | Off; the PR carries a `sync:additive-only` label so customers can wire their own automation; **the product never merges** | First customer drowning in trivially-mergeable PRs |
| SO-C | Webhook↔repo topology (monorepo emitting for several systems) | Open | One hook per system; a monorepo's CI calls each relevant hook | First customer whose CI cannot target hooks per system |
| SO-D | Run acquisition budget | Open | 2 h default, config in `sync-policy.yaml` | First estate whose snapshots legitimately exceed it |
| SO-E | Estate-wide re-render as a run mode (`regen-all`, pairs with KB-C) | Open | Manual dashboard action producing a dedicated sync PR; never automatic | First template change requiring it in production. **Phase-2 inventory item U-14/U-17** (CP-8 report §5) |
| SO-F | Configured-but-disabled sync is silent in single-instance ops | Open — **closes at B-1** | None — `/healthz` already reports `sync_enabled`; the gap is that nothing consumes it where there is no dashboard or alerting surface | **Fired once already** (D-84.2): the pilot ran two days with `SYNC_ENABLED=0` after a compose env-precedence slip, drift accruing unpublished, health green throughout. CP-8 disposition: **build the consumer** in the dashboard's KB-Health view (report §Part 2, Track B-1), not merely re-state the default. **Closure checkpoint fixed at B-1** (D-101 register action; dashboard spec §9.4): the consumer is inventory item U-8 and its conformance test is **DT-9** — configured-but-disabled renders the warning state from `/healthz`'s `sync_enabled`. Until then the trigger stands: second silent-off incident, or the first deployment where the operator cannot eyeball the process env, whichever first |
| SO-G | Refresh cadence for GA4/GSC data delivered into an api-class publish target | Open | None in v1: models are refreshed only by an explicit re-publish (a skill/agent-triggered revision, per RA-E). `scheduled_refresh: no` is declared on the Power BI connection's `publish.flags`, so the limitation is visible in the registration rather than implied | First standing report whose viewers depend on it being current, or the first "why is this report showing last week's numbers". Decide together with RA-G (lifecycle/teardown) and RA-D — the CP-8 review found the three are one design conversation |

## Platform architecture (PA-*)

The architecture spec carries no spec-local register of its own, so items whose home is that document are tracked here directly (the sync spec's SO-* items were in the same situation until D-96.4 added the section above).

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| PA-1 | One-click setup export — how a compiled profile bundle (`.mcp.json` + `CLAUDE.md` + skills) reaches a user's own machine. §5 defines compilation and §6 lists the export as a Agent-Profiles dashboard action, but no delivery path exists outside the dashboard: the core serves `/mcp`, `/.well-known/*` and `/v1/*` only, and its MCP surface implements tools, not resources | **Closed** (D-108.1) | Operator-mediated file copy (`scp`, shared drive, USB). The bundle carries no credential, so out-of-band copying is safe if inconvenient | **Evidence, D-88.2:** the first second-machine onboarding hit this immediately — the M3 gate demo had to fall back to `scp.exe` from a Windows client. **Ruled to Track A-2 (D-96.3):** authenticated bundle download served by the core, authorized server-side against the requester's own profile binding; the A-2 gate demo is a second human completing it hands-off. B-3's one-click export serves the same path a face. **Mechanism built 2026-08-05 (A-2 build, D-107.1/.3/.4/.5):** `GET /v1/setup/bundle` on the B-0 session layer — profile derived server-side from the requester's own `roles.yaml` binding, a `?profile=` refused as `profile_not_addressable`, compile-on-request (no cache), deterministic tar.gz, browser sent to sign in and script kept at 401; no-credential asserted by canary test. **Closed 2026-08-06 (D-108.1):** the second-human run happened — the colleague signed in as her own identity and took the one-link browser path to her own bundle; `results/phase2/a2/`. B-3 still owes the path a face, which is a view, not this item |
| PA-2 | Compiled-bundle staleness (filed D-94.3; sits beside PA-1 as the other half of the setup-export design, §5). The bundle's `CLAUDE.md` tool list is read by the session as the statement of what it may do, so it acts as **de facto client-side permissions**: it cannot widen the server allow-set (which is authoritative per call) but it can narrow what the session will even attempt. A bundle compiled before a profile change silently withholds capability the profile now grants | **Closed** (D-108.1) | Recompile and re-copy the bundle after any profile change; the runbook says so at 4.7. No product mechanism enforces it | **Evidence, 2026-07-29:** the interrupted M3 gate attempt — the reporter's bundle predated the `publish_report:powerbi` grant, so the session declined to build the report and filed gap `6473a5f1` instead (`results/cp7-gate/interrupted-run-2026-07-29/`). **Ruled to Track A-2 (D-96.3):** compile-on-profile-change or a session-visible staleness signal, demonstrated by repeating the 2026-07-29 failure shape and watching it *not* fail (A-2 gate). **Mechanism built 2026-08-05 (A-2 build, D-107.2):** the compile stamps the bundle (server URL + CLAUDE.md + every skill file) into its own `.mcp.json` URL; the MCP handler compares it at connection and returns `SETUP OUT OF DATE` (or `SETUP UNVERIFIABLE` for a pre-A-2, unstamped bundle) as the server's `instructions`, with the one-step refresh URL. The 2026-07-29 shape is repeated as a regression test and does **not** fail (`core/test/setup-bundle.test.ts`). **Closed 2026-08-06 (D-108.1)** on the second-human run; the evidence half it was missing is **PA-3**, filed and built the same day |

| PA-3 | Stamp-in-audit: an audit row could not state which compiled setup the session presented. PA-2's staleness comparison happens at `initialize` and is reported in the server's `instructions`, but nothing durable recorded the stamp — so evidence for "this session ran a current bundle" was an inference from timestamps rather than a column. Home: dashboard spec §5 / MCP audit fields | **Closed** (D-108.4, built 2026-08-06 at A-3/B-2 task 0) | `audit_records.setup_stamp` carries the presented stamp, or the literal `unstamped` when a session presents none (NULL is reserved for rows predating migration `0011`); written on denied-connection rows too; served by the §5.1 audit read and appended as the last field of `extract-audit.sh`'s `audit-chain.txt`. The value is the client's claim, recorded and never trusted — no code path reads it to permit or deny | — |

## Dashboard & UI inventory (U-*, E2)

Home: `dashboard-spec.md` — §3 (inventory → module → checkpoint map) and §9 (register actions). U-1..U-18 are the CP-8 go/no-go report Part 5 inventory made contractual by that spec; **U-19 is new with D-101** (the enrichment-request queue). **E2** is the CP-3b pre-ruling item whose Connections-UI slot the admin CLI has stood in for since D-63.8; like the PA-* items it has no spec-local register of its own and is tracked here directly. `Open` here means what it means everywhere in this register — not yet built or not yet served; the last column is the checkpoint at which the item closes, per dashboard spec §3. Rows are inventory, not new decisions: each one's *design* is already ruled by UI-1..UI-11.

| ID | Item | Status | Current state | Closure checkpoint |
|---|---|---|---|---|
| E2 | Connections UI — the admin CLI has been its explicit stand-in since D-63.8 ("E2's Connections-UI stand-in"), running direct-DB | **Closed** (A-3 + B-2, 2026-08-06) | `/v1/dashboard/connections` is the one writer of `sync_systems`, role-gated server-side (ops writes, steward reads, everyone else 403); the Connections module is its face; the admin CLI is a peer client and its direct-DB registry path is **deleted**, asserted at grep level over `cli.ts`. The D-84 cost is closed structurally: `upsertSyncSystem` re-reads and compares, so a write the store did not take raises instead of returning — proved against a trigger that swallows writes | — |
| U-1 | Connections: list, register, configure, test, health | **Served** (A-3 API + B-2 module, 2026-08-06) | CRUD + per-source health + `test_connection` over the governed API; the probe is the SDK's builtin (`health_probe: builtin`) and reports `unprobed` rather than a pass it did not perform; an `auth_error` renders a re-auth prompt naming the credential *reference*. Live-verified on all five pilot rows | — |
| U-2 | Setup export / bundle delivery | **Served** (A-2 build, 2026-08-05) | `GET /v1/setup/bundle` + `/v1/setup/status`, role-gated server-side; B-3 gives it a face | B-3 (the view; the path itself is built) |
| U-3 | Bundle staleness / compile-on-profile-change signal | **Built** (A-2 build, 2026-08-05) | Compile stamp in the client's own MCP URL, compared at connection; `/v1/setup/status` for scripts | B-3 (surfacing it in the Setup view) |
| U-4 | KB Health: freshness/trust map, doc-status counts, drift feed, sync-PR queue | Open | `report_freshness()` is specified as the same query the module renders; runs/freshness endpoints exist | B-1 |
| U-5 | Ledger / gap triage queue, LED-R5 neutralization on the render path | Open | `list_gaps` + ledger tables exist; no governed read API, no view | B-0 (API) / B-1 (view) |
| U-6 | Human gap filing — the class-3 `human_filed` inlet under the filer's identity | Open | `flag_gap` exists; the dashboard inlet does not | B-1 |
| U-7 | Freshness warnings at OD-3 thresholds, mode-independent | Open | `GET /v1/freshness-warnings` exists | B-1 |
| U-8 | Sync-state visibility — the SO-F consumer | Open | `/healthz` reports `sync_enabled`; nothing consumes it | B-1 (DT-9) |
| U-9 | Publish deliveries + attestation history; the delivered-but-unattested dangling state | Open | `model_deliveries` / `report_attestations` tables exist; no read API | B-0 (API) / B-1 (view) |
| U-10 | Run/job health feed + dead-letter re-enqueue | Open | `/v1/jobs`, `/v1/runs`, `/v1/health-events` exist; re-enqueue is `POST /v1/jobs` as the user | B-1 (read) / B-2 (re-enqueue) |
| U-11 | Webhook secret lifecycle — write-only (UI-8) | Open | Rotation works via the admin CLI; no API, no UI | B-2 |
| U-12 | Audit view + retention/export | Open | `audit_records` is written on every call; nothing serves it — `extract-audit.sh` is the workaround, and becomes a client of the B-0 endpoint. **Scope gap filed 2026-08-06 (D-110.3a), home dashboard spec §5.1:** the table is one row per *MCP call*, so connection CRUD and every other governance write land in no audit row — the durable trace today is the job's `triggers` array, which exists only where a job exists. Widening the contract is a ruling, not a patch. **Normative trigger: MUST close before the B-4 view ships** — an audit view that omits the writes changing who can reach what is dishonest in exactly the register the auditor role exists to read. D-107.3 (verdict history) and D-107.4 (jobs retention) are filed alongside it at §5.2 | B-0 (API) / B-4 (view) — **§5.1 blocks B-4** |
| U-13 | Benchmarks — scores per kb_ref | Open | Scores are not in ops Postgres yet (BASELINE-1); the view ships **dark** per UI-10 rather than inventing numbers | B-4 |
| U-14 | Profiles editor + role map | Open | Profile files are KB YAML; editing composes a PR under the editing user's identity — no write path to `main` (§7.1, DT-4) | B-3 |
| U-15 | Lineage explorer (read) | Open | `get_lineage` + `graph.json` exist; served inside KB Health, not as a separate module | B-1 |
| U-16 | Detector-rule configuration (thresholds as ops config, OD-2) | Open | `detector_rules` is ops config by design; no surface | B-2 (write surface) |
| U-17 | Estate-wide re-render trigger (`regen-all`, SO-E) | Open | The sync run exists; the trigger mode does not | B-2 (write surface) |
| U-18 | Small-cell suppression configuration (SUPPRESS-1's home, when built) | Open | Follows U-14's mechanism; nothing built, no threshold enforced anywhere | B-3 |
| U-19 | **Knowledge Requests queue** — submissions with optional proposal text, steward approve/reject verdicts (ledger state only, UI-11), the approved worklist, and the "deliver batch" trigger | Open | **New with D-101** (2026-08-05); nothing built. Its spec support lands in the same batch: ledger kind `enrichment_request` with verdict states, the `flag_gap` proposal inlet, and the enrich skill's queue-driven batch mode | B-1 — **DT-11/DT-12** plus the end-to-end demonstration in the plan's B-1 gate (request → verdict → batch → merged enrich PR → requester sees resolution) |

## Plan-level (BASELINE-*)

Items whose home is the development plan rather than a spec; home ruling recorded in `DECISIONS.md`.

| ID | Item | Status | Default | Revisit trigger |
|---|---|---|---|---|
| SUPPRESS-1 | Small-cell suppression threshold for aggregate reporting output (the `reporting.*` views expose counts on a ~24-user estate; a cell of 1–2 can identify even though no column names anyone). **Home ruled (D-96.3, superseding D-86.4's undecided):** enforcement in profile `limits.min_cell_count`, applied at the publish path's re-validation, disclosed in the artifact | Open | None yet built. Every `reporting.*` human doc warns that low cells are sensitive rather than reportable; no numeric threshold is defined and none is enforced anywhere in the pipeline | **Trigger tightened (D-96.3, Phase-2 plan §5): the first report with an audience beyond its author** — which Track B-1's demos may themselves trip; if outside viewers see reports before then, the build pulls forward into whichever checkpoint is current. The M3 pilot demo's audience was the owner reading their own estate |
| BASELINE-1 | Full KB-value baseline via the benchmark skill (three-condition comparison; D-80.1 — v1 skipped at CP-5, standing constraint: no quantitative KB-value claims in customer or demo material until it exists, carried verbatim into the Phase-2 plan per D-96.5) | Open | Rig re-runnable as landed (driver + preflight + conditions); no numbers claimed meanwhile | **Gate restated (D-96.3): entry condition of the first customer conversation that quotes value.** Not run at CP-8, deliberately. The CP-8 cost estimate (≈8–13 h operator attention) is recorded so the trigger firing books a two-day block, never an emergency (plan §2.2). MC-1 stays blocked behind it, correctly |
