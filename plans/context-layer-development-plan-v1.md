# Context Layer — Development Plan (v1.0)

Status: first full plan, built against spec set v1.0 and the agreed nine-checkpoint milestone structure. Deployment context: customer 2 (Supabase + GA4 + GSC → Looker Studio) is the first build; every task here is executed against the platform contracts so the architecture stays connector-generic. This plan lives in the platform repo alongside `specs/`; changes are PRs, same as everything else.

**The checkpoint model.** A checkpoint is a *demonstrable event* plus a *mechanically verifiable gate* — the same discipline the onboarding playbook applies to its readiness gate. A checkpoint is passed when its demo has been performed and every gate item checks green; no checkpoint passes on intent. M1, M2, and M3 keep their spec-set names and meanings: they are the three points where the design partner gets hands-on value and where security approval is sought incrementally.

**Landing is part of the gate** *(added per ruling D-74, 2026-07-21)*. Every checkpoint sign-off includes its branch landing on `main`: **a checkpoint is not closed while its work is unmerged.** This is a gate item, not bookkeeping — CP-2's harness sat unmerged through CP-3, CP-4 and CP-6, and CP-5 opened believing a premise (the harness, the seed suite, ruling D-62) that its own branch did not carry. The failure mode is not lost work; it is a premise believed true because the work was done, on a branch that never received it. CP-5 clears the accumulated debt: `cp5-skills` PRs to `main`, carrying M2 + CP-5 in one reviewed landing.

**Duration discipline.** Per OB-4, no duration promises before data. This plan commits to *sequence and dependency*, not dates; OB-4 instrumentation (armed at CP-0) is what makes dating the second build honest.

---

## 1. The checkpoint chain

```
CP-0 ──► CP-1 ──┬─► CP-2 ─┐
                └─► CP-3 ─┴─► CP-4 (M1) ──┬─► CP-5 ─┐
                                          ├─► CP-6 ─┴─► CP-7 (M3) ──► CP-8
                                          └─► dashboard track (gates nothing)
                                              (CP-6 = M2)
```

Two parallel windows: **Window A** (CP-2 ∥ CP-3, after CP-1) and **Window B** (CP-5 ∥ CP-6 ∥ dashboard, after CP-4). Both branches of each window must land before the window's convergence point.

| # | Checkpoint | Milestone | Proves | Converges from |
|---|---|---|---|---|
| CP-0 | Ready to build | — | Nothing external blocks engineering | — |
| CP-1 | The KB exists | — | The estate is describable from docs alone | CP-0 |
| CP-2 | We can measure | — | Accuracy claims have a baseline | CP-1 |
| CP-3 | Drift heals itself | — | Schema change → correct PR, unattended | CP-1 (+ sync-orchestrator spec) |
| CP-4 | Context + validated SQL | **M1** | Pilot users get read-only value, safely | CP-2 and CP-3 |
| CP-5 | The loop closes | — | Usage grows the KB | CP-4 |
| CP-6 | Governed execution | **M2** | Queries run under user identity, bounded | CP-4 |
| CP-7 | One click to a report — **CLOSED** (D-95; amended target per D-91, see §7) | **M3** | A non-analyst ships a real report | CP-5 and CP-6 |
| CP-8 | Go/no-go — **CLOSED** (D-96.1; amended shape, see §8) | — | The pilot converts on evidence | CP-7 + metrics window |

**Platform-plan mapping.** CP-1 = phase 1 (with the platform plan's phase 3 — source connectors + entities — folded in, since customer 2's "SAP phase" is the GA4/GSC connectors and entity docs, already tasks 1.3/1.4/1.8). CP-2 = phase 2. CP-3 = phase 4. CP-4 = phase 5. CP-5 = phase 6. CP-6 = phase 7. CP-7 = phase 8 with the Looker Studio adapter substituted for Power BI. CP-8 = phase 9.

---

## 2. CP-0 — Ready to build

**Purpose:** clear every external dependency before engineering burns time waiting on it. The playbook is explicit that credential/approval lead time is almost always the critical path — those asks go out first.

**Entry:** signed agreement; spec set v1.0 committed as `specs/` in the platform repo.

**Work:**

| # | Task | Owner |
|---|---|---|
| 0.1 | Issue the ask list (phase-1 plan §8 / playbook §1) and chase to completion | R5 |
| 0.2 | Discovery & topology classification: every source and target classified per the P1–P5 case matrices; record drives all later config | R5 + R2/R3 |
| 0.3 | Arm OB-4 instrumentation: per-step timers on all ten playbook steps, recording from this onboarding onward | R5 |
| 0.4 | Confirm the Looker Studio capability ceiling with the customer now ("one click to instantiate" is the automation limit) — not at M3 | R5 |
| 0.5 | Environments: platform install target (Compose-class VM vs K8s per topology), customer git server access for the KB repo | R3 + R5 |

**Exit gate (all mechanically verifiable):**
1. Customer packet complete: DDL files + existing docs; GA4 property ID + read service account; GSC verified property + service account; migrations-repo location + webhook permission; git server for the KB; Supabase tier answer (read replica available?).
2. Ten real report requests received, with any existing SQL (golden-benchmark seed).
3. Topology classification recorded per source/target (P1 access mode, P1 sync policy, P2 execution topology, P5 publish ceiling).
4. OB-4 timers running.
5. Looker ceiling acknowledged by the customer in writing.

**Register items due:** OB-4 instrumentation starts (gate item 4).

**Risks live here:** credential lead time (mitigate: asks issued day one, chased weekly); missing seed reports stall CP-2 (mitigate: accept partial list ≥10, top up later).

---

## 3. CP-1 — The KB exists

**Purpose:** the full KB-creation pipeline, machine phase and knowledge phase, end to end. This checkpoint reuses phase-1 tasks 1.1–1.9 verbatim — they are already specified to exit-criterion level and each is verified by named spec sections (spec-index §"What each phase-1 exit criterion now rests on").

**Entry:** CP-0 passed.

**Work (tasks 1.1–1.9, with parallelism):**

| Task | Content | Exit criterion | Verified by |
|---|---|---|---|
| 1.1 | Snapshot schema finalized; fixture files for all three systems | Fixtures validate against JSON Schema; sync diff runs on fixtures | Snapshot §8.1/§8.2, C-1 |
| 1.2 | Postgres introspector + ephemeral-DDL mode | DDL→snapshot identical to live introspection of same DDL | Snapshot C-2/C-3, capability MP-1, job JC-4 |
| 1.3 | GA4 connector | Live pull produces dimension/metric/event objects incl. custom definitions | Snapshot C-1..C-8, manifest CC-1 |
| 1.4 | GSC connector | Property list + fixed schema rendered | Snapshot C-1..C-8, manifest CC-1 |
| 1.5 | Generator + templates | Snapshots → repo renders; regeneration idempotent (no-op diff on no change) | KB §3/§4/§7, KB-8 |
| 1.6 | Customer KB bootstrap | Generated KB merged; `conventions.md` + role map committed; CI green | KB §10, playbook step 2 |
| 1.7 | Existing-docs ingestion via `enrich` skill | Customer docs converted to human-owned docs, landed as PRs | Capability KP-*, skill §6, AS-6 |
| 1.8 | Entity drafts (`user`, `page`, `conversion`) | Concrete key mappings drafted, reviewed by customer | KB §4.3, playbook step 6 |
| 1.9 | Lineage derivation from view SQL | Every DDL view's upstream tables + column mappings resolve; `get_lineage` walks them | Formats §3, FG-1..FG-5, capability LP-* |

Sequencing: 1.1 first; 1.2–1.4 parallel after it; 1.5–1.6 after any one connector lands (fixtures allow earlier template work); 1.7–1.8 overlap once 1.6 is merged; 1.9 alongside 1.5 (lineage ships with phase 1 per platform-architecture §7 — the demo customer's view definitions exercise it from day one).

Note: tasks 1.7/1.8 use an early cut of the `enrich` skill ahead of its full CP-5 packaging — the skill spec exists; what ships at CP-5 is the packaged, checkpoint-enforced version of all four skills.

**Exit gate:**
1. All nine task exit criteria hold.
2. Phase-1 master criterion: KB merged in the customer's git server, docs render correctly.
3. Scripted estate-description session passes — an agent reading only the merged KB correctly describes the estate (playbook step 4 exit).

**Register items due:** SS-3 closed at 1.4 exit (envelope confirmed by implementation); SP-3 answered from 1.7 steward-review ergonomics; SS-2 evidence recorded at 1.8 review (did doc-only grounding suffice for enum decodings and entity keys?).

**Risks live here:** DDL/live mode divergence (mitigate: C-3 conformance test is the 1.2 exit); GA4 quota throttling during connector development (mitigate: J-5 deferral semantics + manifest quota policy).

---

## 4. Window A — CP-2 ∥ CP-3

Independent tracks after CP-1; both must land before CP-4. Staff as two tracks if headcount allows; if serialized, CP-3's spec-authoring predecessor makes CP-2 the natural first track.

### 4.1 CP-2 — We can measure

**Purpose:** the golden benchmark and its baseline. M1's exit criterion is "pilot users produce validated SQL *for benchmark queries*" — the benchmark is therefore a hard M1 predecessor, not a nice-to-have.

**Entry:** CP-1 passed; ≥10 seed report requests in hand.

**Work:**

| # | Task |
|---|---|
| 2.1 | Convert seed requests into benchmark cases: request → analyst-verified SQL/result (customer-supplied SQL where it exists, verified otherwise) |
| 2.2 | Scoring harness: runs the suite against a KB commit, scores accuracy, records per-journey **retrieval recall** (the MC-1 metric) |
| 2.3 | Baseline runs: with the KB and without (live-discovery baseline) — the product's value claim in one number — **moved to CP-5 per ruling D-62 (2026-07-16)** |
| 2.4 | Wire benchmark into CI keyed to KB commits (regression detection from here on) |
| 2.5 | FM-2 check: map each seed report onto the five visual kinds; any inexpressible report goes to the register *now*, before phase-8 work builds against the registry |
| 2.6 | SP-4/FM-4 scan: flag seed requests that are obviously recurring; record demand evidence |

**Exit gate** *(amended per ruling D-62, 2026-07-16 — baseline deferred to CP-5)*:
1. Suite validates and all packet checksums reproduce.
2. CI integrity check green; the staged-defect test fires.
3. Harness proven end-to-end on the manual journeys: records ingested from
   files, scored per R4–R6, both scoring paths exercised (checksum and
   same-run golden re-execution), ≥1 journey per condition.
4. FM-2 and SP-4/FM-4 evidence emitted from packet fields.
5. Results artifact committed, keyed per R8 with transport "manual-interactive".

*Removed by D-62: the 90-journey (and reduced 30-journey) baseline. The full
three-condition baseline is CP-5's added exit criterion (§6.1); its journeys
are transport-proof only until then, and no quantitative KB-value claims go
into customer or demo material before baseline v1 lands.*

**Register items due:** MC-1's metric lands with CP-5 baseline v1 (D-62); FM-2 tested; SP-4/FM-4 demand evidence noted.

**Risks live here:** GA4 quota exhaustion under repeated benchmark iteration (mitigate: cache `runReport` results per session; document quota behavior in `conventions.md`).

### 4.2 CP-3 — Drift heals itself

**Purpose:** the sync engine — the mechanism that keeps the CP-1 KB alive. Exit is the platform plan's phase-4 criterion: a staged breaking change produces a correct contamination flag and PR within one cycle.

**Entry (hard):** CP-1 passed **and the sync-orchestrator spec is authored and merged**. This is the spec set's one deliberate gap (webhook ingestion detail, scheduling, and the drift-run pipeline tying snapshot diff → contamination scan → PR authoring into one process). CP-3 engineering does not begin against an unspecified process. Interim already in force: the phase-1 webhook receiver was built on the JP-4 default (`/v1/hooks/{system}` + per-hook shared secret); the spec formalizes it.

**Work:**

| # | Task |
|---|---|
| 3.0 | **Author the sync-orchestrator spec** (entry condition; register it through the change process, add its open-decisions to the master register) |
| 3.1 | Trigger layer: scheduled polling + CI-webhook ingestion per the new spec; per-source sync policy from `.contextlayer/sync-policy.yaml` |
| 3.2 | Drift run pipeline: re-snapshot → per-object hash diff (snapshot §7 classifications) → severity classes |
| 3.3 | Contamination scan per KB §6: `depends_on` primary, lineage-graph downstream walk, body-grep secondary net (surfaced, never auto-flagged) |
| 3.4 | Machine-doc regeneration for changed objects only (KB-C default); PR authoring with human-readable changelog; front-matter-only writes to human docs, CI-enforced |
| 3.5 | Build the **standard drift-drill fixture** (test schema + scripted breaking change) as a shipped product asset — this closes OB-3 |
| 3.6 | Freshness monitoring: OD-3 thresholds wired per customer-2 values (3 days GA4/GSC, 30 days Supabase) |

**Exit gate:**
1. Staged drill (using the 3.5 fixture): breaking change introduced in a test object → sync PR appears with correct contamination flag → within one cycle.
2. Additive change produces `stale` (not `contaminated`) markings — K-3 semantics verified.
3. A comment-only edit produces regeneration but zero contamination (S-2 verified end-to-end).
4. Sync-authored commits touch nothing below human-doc front-matter fences (CI check green).
5. Freshness warnings fire at configured thresholds in a clock-skew test.

**Register items due:** JP-4 closed by the spec; OB-3 closed by the fixture; OD-3 values in force.

**Risks live here:** spec authoring slips and stalls the track (mitigate: it is task 3.0 with a named owner, started during Window A's CP-2 work if tracks are serialized).

---

## 5. CP-4 — M1: Context + validated SQL

**Purpose:** the first pilot-value milestone. The MCP server becomes the single read surface; real users under real identities produce validated SQL. The fault ledger ships with the MCP server (its detectors read the audit stream that now exists).

**Entry:** CP-2 and CP-3 passed; security review #1 scheduled.

**Work:**

| # | Task |
|---|---|
| 4.1 | MCP server: the eleven-tool surface (read + validate), OAuth/streamable HTTP, validation tokens (300 s TTL per MC-2), trust blocks on every response |
| 4.2 | OIDC/SSO integration; role→doc-visibility map from `roles.yaml`; server-side profile enforcement on every call (no client config can widen access) |
| 4.3 | `validate_sql` dialect-switched per CI-B ruling, backed by snapshot authority per MC-5 |
| 4.4 | Fault ledger: events/issues tables, the four class-1 detector rules as ops config (shipped defaults; `execute_without_resolution` log-only disabled per SP-1), `flag_gap` + `list_gaps`, KB Health triage-queue contract |
| 4.5 | Dashboard track begins (§7 below) — Connections + KB Health first |
| 4.6 | Security review #1: benchmark-waiver leakage (SP-2), `distinct_subjects` privacy stance (FL-E), snapshot-vs-rendered-file authority (MC-5) |
| 4.7 | Readiness-gate items that are now testable: profiles enforce for a real pilot user (MT-1); benchmark CI-wired (from CP-2) |

**Exit gate:**
1. **The M1 demo:** a real pilot user, via Claude Code over MCP under their own OIDC identity, produces validated SQL for benchmark queries.
2. MT-1 passes: profile enforcement verified for a real pilot user; a Reporter profile cannot reach Steward tools.
3. Ledger live: a forced `zero_result_search` opens a `coverage_gap` issue visible in KB Health and via `list_gaps`.
4. Security review #1 signed (SP-2, FL-E, MC-5 dispositions recorded in the register).
5. Audit records written for every tool call, linkable from ledger events via `audit_ref`.

**Register items due:** SP-2, FL-E, MC-5 moved to Closed on review sign-off (expected outcomes: non-issue, counts-only affirmed, snapshot authority affirmed). Ledger telemetry begins accruing for OD-2, FL-C, MC-4.

**Risks live here:** security review scheduling (mitigate: booked at CP-4 entry, scope pre-agreed from the register); SSO integration friction with the customer IdP (mitigate: topology facts captured at CP-0 step 0.2).

---

## 6. Window B — CP-5 ∥ CP-6 ∥ dashboard track

Independent after CP-4: skills depend on the MCP surface, the gateway depends on the MCP surface, neither depends on the other. Both converge on CP-7 (the M3 journey uses the `report` skill *and* the gateway).

### 6.1 CP-5 — The loop closes

**Purpose:** the four shipped skills, packaged per the skill specs (state machines, kernel, enforced/attested checkpoints), and the ledger→enrich growth loop demonstrated end to end.

**Entry:** CP-4 passed.

**Work:**

| # | Task |
|---|---|
| 5.1 | Package `enrich` (production version: ledger-item scope priority, `CL-Resolves` trailers, batch size per the SP-3 answer from 1.7) |
| 5.2 | Package `review-sync` (drift-PR summarization + risk ranking; flags PRs whose body references FQNs missing from `depends_on`) |
| 5.3 | Package `benchmark` (runs the golden suite; benchmark-mode waiver keyed to the server-known profile per SP-2 ruling); its first complete run is **baseline v1** (D-62) |
| 5.4 | Package `report` (the guided J3 journey for business users, honest-failure behavior at every gap) |
| 5.5 | Skill acceptance CI per skill-spec conformance; checkpoints enforced server-side where the spec says enforced |
| 5.6 | Run one full growth cycle on real data: triage a real ledger issue → enrich batch → PRs with `CL-Resolves` → merge → issue auto-resolves → benchmark re-run |

**Exit gate:**
1. All four skills pass acceptance CI.
2. The 5.6 growth cycle demonstrated: a ledger issue resolved by a merged enrichment PR, loop closure attributed via trailer (L-5), occurrence counter behavior verified (L-4 reopen on recurrence, tested).
3. Benchmark accuracy measurably improves after the enrichment batch (the platform plan's phase-6 criterion, scaled to customer 2's estate).
4. *(added per ruling D-62, 2026-07-16)* **Baseline v1**: the benchmark skill's first complete three-condition run (10 cases × 3 conditions × ≥1 rep), executed via the skill in Claude Code under subscription/Agent SDK credit. MC-1's recall table and the enriched-vs-machine-vs-none comparison land here. Must inherit R2 fairness, R4–R6 scoring, R8 keying, and the harness's file-ingestion path unchanged.

**Register items due:** none new; SP-3's phase-1 answer is now baked into the packaged skill.

### 6.2 CP-6 — M2: Governed execution

**Purpose:** the execution gateway — queries run end to end under user identity, bounded by guardrails, fully audited. For customer 2 this is governed **direct-on-OLTP** execution, the deployment-configurable exception the product spec allows for DW-less estates, which makes the guardrails non-negotiable from the first query.

**Entry:** CP-4 passed; security review #2 scheduled.

**Work:**

| # | Task |
|---|---|
| 6.1 | Execution gateway: governed `execute_sql`, SELECT-only read-only role, `statement_timeout`, row caps, per-system policy; read replica wired if the CP-0 tier answer allows |
| 6.2 | Result handling per JP-3 defaults: 64 MB inline cap, `truncated` + narrow-your-query guidance (CI-A) |
| 6.3 | Guardrail terminations feed the ledger (`guardrail_hit` window rule live) |
| 6.4 | Reporting-views pattern operational: report-grade SQL lands as a migration PR into the `reporting` schema — never ad-hoc recurring queries against production |
| 6.5 | **JP-2 measurement:** p95 claim-to-start on a warm runner, measured against the committed 500 ms budget; JP-1 decided by the result (pass → runner routing stands and JP-1 closes; miss → core-native short-circuit is designed under JP-1) |
| 6.6 | Security review #2: execution path, identity propagation, guardrail bypass surface, audit completeness |

**Exit gate:**
1. **The M2 demo:** benchmark queries execute end-to-end under the pilot user's identity through the gateway.
2. Guardrails demonstrably terminate: a deliberate timeout, a deliberate row-cap breach, and a quota-exhaustion path each produce correct termination + ledger event.
3. JP-2 measurement recorded; JP-1 disposition recorded in the register.
4. Security sign-off #2.
5. Zero direct production writes possible: role privileges audited.

**Register items due:** JP-2 closed (measured), JP-1 closed or converted to design work by the measurement.

**Risks live here:** **direct-on-OLTP reporting is the pilot-ending risk class** — an agent load on production is exactly what the guardrails exist to prevent. Mitigations all mandatory from the first query: read-only role, timeouts, row caps, reporting-views for anything recurring, replica when available. GA4 quotas re-enter here for API-side execution (session caching per CP-2 mitigation).

### 6.3 Dashboard track (gates nothing)

One codebase, config-customized, per platform-architecture §6. Build order: **Connections** and **KB Health** first (they visualize state the pipeline already records — source health from CP-1/CP-3, triage queue from CP-4), then **Profiles** (editor + Claude Code setup export), then Audit and Benchmarks modules. Runs from CP-4 onward; no checkpoint depends on it; useful from its first module because R2's triage home screen (FL-B default: dashboard-only notifications) lives here.

---

## 7. CP-7 — M3: One click to a report

**Status: CLOSED** (ruling D-95, 2026-07-30), against the **amended** target: ruling D-91 replaced the Looker Studio template-link gate with text-to-report via Power BI (plain-language request → finished, AI-designed, trust-annotated report in the customer workspace; `pending_human_steps` empty or "open the report"). The Looker leg remains on `main` as a registered secondary target under its documented CI-F limits. Sign-off is an **owner acceptance on attestation** — the ruling party did not inspect the evidence (D-95.1, same class as D-80.2). Closure bookkeeping, including what the server record does and does not support, is `DECISIONS.md` § "D-95 part C"; the gate demo's own record lives in the ops database (window `2026-07-29T11:11:49Z`–`12:05:16Z`) and has **not** been extracted into `results/cp7-gate/`.

Exit-gate status as recorded at closure: item 1 **met** (Act 1, evidenced by four succeeded `powerbi` publish jobs, two attestations on one `report_id`, and the artifact's layout + trust notes); item 2 **pending** (F-4 attestations written in ops, but no graph-only drift run has carried them into the KB, so `get_lineage` cannot yet walk from the report node); item 3 **partially met** (see §9 — gate items 3, 4 and 6 do not hold on the example estate). Two acts of the demo — cross-source (Act 2) and the undocumented-blend refusal (Act 3b) — carry no server-side trace and rest on the attestation alone.

**Purpose (as planned):** the full J3 journey for a non-analyst, within the Looker Studio ceiling recorded at CP-0: the agent ships the reporting view as a migration PR, hands over a pre-wired template link, one human click instantiates the report.

**Entry:** CP-5 and CP-6 passed.

**Work:**

| # | Task |
|---|---|
| 7.1 | Intermediate report artifact implementation per the formats spec (validated SQL/dataset ref, semantic identifiers from the KB, tool-agnostic visual spec) |
| 7.2 | Looker Studio adapter with the recorded capability flags: `create_report: no`, `template_link: yes` (Linking API), `sql_backing: via reporting views`, `cross_source: blending` on entity-documented keys |
| 7.3 | Publish lifecycle: artifact revisions retained per FM-3; blend configs parsed into lineage at publish time (extending 1.9) |
| 7.4 | Capability-gap handoffs: where the flag says no, the journey emits a `capability_gap` ledger event with the DDL riding in `detail` (SK-6) rather than failing silently |

**Exit gate:**
1. **The M3 demo:** a real non-analyst pilot user, Reporter profile, takes one seed request through resolution → validation → execution → reporting-view PR → template link → instantiated Looker Studio report.
2. The published report's lineage resolves: `get_lineage` walks from the report node through the blend/view to source tables.
3. The remaining playbook readiness-gate items pass (see §9) — the customer is formally report-ready.

**Register items due:** none scheduled; FM-2 was pre-validated at CP-2, so any registry surprise here is a process failure, not a plan item.

**Risks live here:** the Looker API ceiling — already expectation-set at CP-0 gate item 5, so this checkpoint delivers exactly what was promised, not less than what was imagined.

---

## 8. CP-8 — Go/no-go

**Status: CLOSED** (ruling D-96.1, 2026-07-31), on `results/cp8/go-no-go-report.md`. The verdict is **GO with conditions for a real, vendor-assisted onboarding; NO-GO for an unassisted one from the playbook alone** — the platform passes, the playbook does not. The two-track Phase-2 shape proposed in that report is adopted as the planning basis (D-96.1/D-96.6).

**Closed against an amended shape, stated plainly.** The checkpoint as planned rests on a usage window that never ran, so three of its six tasks were not performed as written: **8.1** (no metrics window), **8.4** (no pilot-data register closure — 235 audit rows is not enough traffic to set OD-2/MC-4/SP-1/FL-C values; re-scheduled to the first customer's first month), and **8.5**'s benchmark half (BASELINE-1 skipped at CP-5 by D-80.1 and deliberately not revived here — D-96 carries the standing no-quantitative-claims constraint into Phase 2 instead). What the checkpoint *did* produce is a readiness review graded against a harder bar than the plan set: *can this product onboard the next customer from its own playbook, without the vendor in the loop?* Tasks **8.2**, **8.3** and **8.6** are answered by the report's disposition block and D-96's rulings on it.

**Exit-gate status at closure:** item 1 **not met as written** (no metrics window, no benchmark evidence pack) — the evidence pack is the go/no-go report itself; item 2 **met** (D-96.1); item 3 **partially met** — the bookkeeping reconcile landed (OB-3, JP-4, the missing SO-* section, SS-5 by capture), the pilot-data items are deferred with a named trigger, and the **v1.1 consolidation pass is not done** and is not claimed.

**Purpose (as planned):** run the success metrics over a defined usage window, harden from findings, and assemble the evidence pack for converting pilot to contract. Also the point where the pilot-data register items close.

**Entry:** CP-7 passed; usage window defined and agreed with the customer (length set here, not promised earlier — OB-4 discipline).

**Work:**

| # | Task |
|---|---|
| 8.1 | Run the success-metrics window (product spec §11 metrics over real usage) |
| 8.2 | Weekly triage cadence: ledger review → enrichment batches → benchmark trend (the CP-5 loop, operated) |
| 8.3 | Hardening backlog from window findings |
| 8.4 | Register closure pass from pilot data: OD-2 threshold values (at pilot + 30 days), MC-4 rate-limit shape, SP-1 false-positive verdict, FL-C noise floor |
| 8.5 | Evidence pack: baseline vs current benchmark, journey completion rates, ledger open/resolved trend, OB-4 duration data, security sign-offs |
| 8.6 | Spec-set consolidation pass v1.1: fold amendments, reconcile the master register |

**Exit gate:**
1. Metrics window complete; evidence pack assembled.
2. Go/no-go decision recorded with the customer.
3. Register updated: pilot-data items dispositioned; v1.1 consolidation committed.

---

## 9. Readiness-gate mapping (first build only)

The playbook's step-9 readiness gate assumes the full stack exists. For this first build, its items pass at the checkpoint that builds their machinery; for customer 3 onward the gate collapses back into a single onboarding pass.

| Playbook gate item | Passes at |
|---|---|
| 1 — snapshots accepted, health green, triggers armed | CP-1 (armed), CP-3 (health monitoring live) |
| 2 — machine KB merged, estate-description session | CP-1 |
| 3 — hot objects documented, report-path docs verified | CP-1 (1.7/1.8), deepened at CP-5 |
| 4 — every seed request resolves to entities + certified metrics | CP-2 (resolution verified while building cases) |
| 5 — profiles enforce for a real pilot user (MT-1) | CP-4 |
| 6 — benchmark baseline recorded, CI-wired | CP-2 |
| 7 — staged drift drill end-to-end | CP-3 |
| 8 — first real J3 journey with publish per the P5 ceiling | CP-7 |

---

## 10. Register calendar (consolidated)

Every register action from the v1.0 review pass, placed:

| When | Items |
|---|---|
| CP-0 | OB-4 timers armed |
| CP-1 | SS-3 close (1.4) · SP-3 answer (1.7) · SS-2 evidence (1.8) |
| CP-2 | MC-1 recall metric live · FM-2 verdict · SP-4/FM-4 demand scan |
| CP-3 entry | Sync-orchestrator spec authored → JP-4 close |
| CP-3 | OB-3 close (drill fixture) · OD-3 values in force |
| CP-4 | Security review #1 → SP-2, FL-E, MC-5 close |
| CP-6 | JP-2 measured → close · JP-1 dispositioned |
| CP-8 | OD-2 thresholds · MC-4 · SP-1 · FL-C from pilot data · v1.1 consolidation |
| Already booked | OD-4 closed (policy complete) · JP-2 budget number adopted (≤500 ms p95) |
| Parked, trigger-watched | Everything else per the register review pass — no dedicated plan work |

---

## 11. Risk register, mapped to where each risk goes live

| Risk | Live at | Mitigation (all pre-specified) |
|---|---|---|
| Credential/approval lead time (the usual critical path) | CP-0 | Asks issued day one; weekly chase; nothing in 1.1/1.5 waits on credentials (fixtures + DDL mode) |
| DDL/live snapshot divergence | CP-1 | Mode invariance is a conformance test (C-3), not a hope |
| GA4 Data API quotas | CP-2, CP-6, CP-7 | Session caching of `runReport`; quota behavior documented in `conventions.md`; J-5 deferral |
| Sync-orchestrator spec slip | CP-3 | Named owner; authoring runs during Window A; hard entry condition so slip is visible, not silent |
| Security review scheduling | CP-4, CP-6 | Two reviews with pre-agreed scope booked at checkpoint entry |
| Direct-on-OLTP execution (pilot-ending class) | CP-6 | Read-only role, timeouts, row caps, reporting-views pattern, replica if available — mandatory from first query |
| Looker Studio API ceiling | CP-7 | Expectation set in writing at CP-0; M3 journey designed inside the ceiling |
| Benchmark seed quality (customer SQL wrong/missing) | CP-2 | Analyst verification is part of case conversion, not assumed |

---

## 12. Instrumentation plan (what must be measured, from when)

| Metric | Starts | Feeds |
|---|---|---|
| Onboarding step durations | CP-0 | OB-4 (duration targets after third onboarding) |
| Benchmark accuracy + retrieval recall per journey | CP-2 | Value claim; MC-1 trigger; CP-5/CP-8 trend |
| Detector rule fire counts + triage dismiss rates | CP-4 | OD-2 thresholds, FL-C noise floor, SP-1 FP rate |
| Per-identity tool-call rates | CP-4 | MC-4 rate-limit shape |
| Claim-to-start latency p95 (warm runner) | CP-6 | JP-2/JP-1 |
| Artifact storage growth | CP-7 | FM-3 retention trigger |

---

## 13. Maintenance

This plan is versioned with the spec set. Checkpoint gates may only be *strengthened* without process; weakening or removing a gate item is a PR that names what evidence replaces it. New open decisions discovered during execution enter their home spec's register first, then the master register, per the standing change process. At CP-8's consolidation pass, this document is revised into the v1.1 plan for the next deployment — with dates, because by then OB-4 has data.
