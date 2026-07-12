# Contract Specification — Shipped Skill Specifications (v1)

Status: v1 draft for implementation. Specifies the four shipped Claude Code skills — `report`, `enrich`, `review-sync`, `benchmark` — as state machines with mandatory checkpoints, per `high-level-requirements-and-user-journeys.md` §7.3–§7.4. Consumes: MCP tool reference (trust blocks, validation tokens, `flag_gap`), KB repository spec (templates, front-matter, statuses), capability interfaces (effective Publisher flags, result shapes), HLR §6 (detector classes) and §9.5 (honest-failure rule).

Skills are **fixed product artifacts, identical across customers** (HLR §7.4); all customer variance lives in profiles, `conventions.md`, and CLAUDE.md fragments. This spec is the normative behavior each skill's implementation (its SKILL.md and any bundled scripts) must encode, and the basis for its acceptance scenarios.

---

## 1. Scope

**In scope:** the shared skill kernel; the enforced/attested checkpoint classification; per-skill state machines (states, mandatory checkpoints, failure exits); acceptance-scenario requirements; amendments to earlier specs.

**Out of scope:** SKILL.md authoring style, prompt wording, and the benchmark harness's scoring internals (the harness is a deterministic product component; §8 defines only its contract with the skill).

## 2. Design rulings

| # | Ruling | Rationale |
|---|---|---|
| SK-1 | Checkpoint compliance is verified **behaviorally through the audit stream**; each skill ships acceptance scenarios asserting audit-observable properties | We cannot deterministically control an LLM; we can deterministically observe every consequential action it takes |
| SK-2 | Every checkpoint is classified **enforced** (server mechanism exists) or **attested** (skill convention, scenario-verified); the spec never presents convention as enforcement | Honesty about the guarantee level, mirroring the fault-ledger's stated limitations |
| SK-3 | A shared **kernel** defines trust behaviors, the standardized failure exit, budget discipline, and grounding rules once; every skill imports it | One place to change agent-wide behavior; skills stay thin |
| SK-4 | Benchmark journeys run under a dedicated non-user `benchmark` profile, audit-tagged; adoption metrics exclude them | Pilot Metric 2 (reports by non-analysts) must be unpollutable by our own test traffic |
| SK-5 | The report skill's negative user confirmation is a first-class ledger kind, `result_disputed` | Detector class 3's primary signal deserves its own triage category, not `other` |
| SK-6 | The reporting-view handoff is a documented branch: migrations-repo access present → agent opens the PR; absent → the view SQL travels as a handoff artifact routed to R2 via the ledger | Makes HLR §4 handoff row 1 concrete for the common case (Reporter has no repo access) |
| SK-7 | Failure-exit loops are bounded: at most 2 self-repair attempts on a validation failure, then flag and stop | Prevents thrash; repeated failures also independently trip the class-1 detector server-side |

## 3. The skill kernel (mandatory in all four skills)

**K-TRUST.** Behavior keys off the server-computed `agent_guidance` on every doc used: `use-freely` — proceed; `warn-user` — proceed only after stating the doc's status and what that means for reliability; `refuse-unless-override` — do not build on it; name the contamination detail; proceed only on the user's explicit, informed instruction, and note the override in the final output. The mapping itself lives server-side (MCP §4) — skills consume `agent_guidance`, never re-derive it from raw statuses.

**K-FAIL (the standardized failure exit, HLR §9.5).** At any recognized dead end: (1) tell the user in plain language what is missing and why it blocks the request; (2) call `flag_gap` with the most specific applicable kind; (3) relay `routed_to` — who was notified; (4) stop, or offer only alternatives that do not require the missing piece. Never guess past a gap; never silently narrow the request to something answerable.

**K-BUDGET.** Follow the hierarchical retrieval path (index/search → entity → the specific object docs needed); never enumerate systems or schemas wholesale; prefer `get_entity` routing over table-guessing.

**K-GROUND.** Assert about the estate only what a tool returned this session; cite trust status when the user's decision depends on it; when results carry `truncated: true`, say so and state the cap — a truncated result is never presented as the full answer.

**K-IDENT.** All writes (git PRs from enrich/review-sync sessions) are authored under the session user's identity, never a shared identity (KB spec §9).

## 4. Checkpoint classes (SK-2)

| Class | Guarantee | Verification |
|---|---|---|
| **Enforced** | Server makes violation impossible (validation token M-2; profile allowlists M-3; guardrail injection MT-5; sync-PR write boundaries KB-4) | Server conformance tests |
| **Attested** | Skill convention; violation is possible but observable | Acceptance scenarios (SK-1) + server-side heuristics where defined (e.g. execute-without-prior-confirmation pattern in audit review) |

Each checkpoint below is tagged **[E]** or **[A]**.

## 5. `report` skill

Serves journey J3 (HLR §5). Profile context: Reporter (guided) — Explorer users may invoke it too.

```
intent → resolution → drafting → validation → execution → presentation → [publish]
```

**S1 intent.** Capture the request verbatim (it becomes `identity.intent`). Read the effective Publisher flags for the session's permitted targets **now** and state the journey's ceiling up front ("I can publish this fully / hand you a one-click template / give you validated SQL") — checkpoint **CP-R0 [A]**, the P5 expectation-setting rule. Ask at most one clarifying question when the request is ambiguous on grain, window, or breakdown; otherwise state assumptions explicitly and proceed.

**S2 resolution.** `search_context` → `get_entity`/`get_metric`/`get_table` along the routing path. **CP-R1 [A]:** before any drafting, present the resolved entities, metrics, and tables with their trust statuses and obtain the user's confirmation. Uncertified metrics are flagged here, not discovered later. *Failure exits:* nothing resolves → K-FAIL `missing_entity`/`missing_doc`; resolution contradicts the request (metric exists but wrong grain) → K-FAIL `uncertified_metric` or `missing_doc` with the specific mismatch.

**S3 drafting.** Draft per `conventions.md` for the target system(s): SQL for `sql` systems, structured API request for `api` systems, or the documented cross-source route (blend keys from the entity doc vs fetch-and-combine) — the entity doc's resolution rule decides, never improvisation. Certified metric implementations are used verbatim from `get_metric`; deviations require telling the user why.

**S4 validation. CP-R2 [E]:** `validate_sql` must pass; execution without its token is impossible (M-2). On `fail`, repair using the findings — at most 2 attempts (SK-7), then K-FAIL `schema_mismatch` or `missing_doc` per the findings.

**S5 execution.** `execute_sql` with the token. `truncated: true` → K-GROUND disclosure + offer to narrow or route to a reporting view. `quota_exhausted` → relay the retry-after honestly; offer to proceed with other sources if the report decomposes. `revalidate_required` → return to S4 silently is **forbidden**; tell the user the schema moved beneath them, then re-validate.

**S6 presentation. CP-R3 [A]:** present results with the refs and any trust warnings that applied. **CP-R4 [A]:** ask the confirmation question — does this match what you asked for? A negative → `flag_gap(kind: result_disputed)` with the user's stated discrepancy (SK-5), then offer to revise. This is detector class 3.

**S7 publish (optional).** Only on user request and profile permission. Behavior follows the effective `create_report` flag: `full` → publish, return URL; `template_link` → execute the backing path first (see below), then hand the link and relay `pending_human_steps` verbatim (PB-3); `none` → deliver validated SQL + instructions. **Backing path (SK-6):** when `sql_backing: views` and the report is recurring, produce the reporting-view DDL; if the session can open a PR on the migrations repo, do so and link it; otherwise attach the DDL as a handoff artifact in a `flag_gap(kind: capability_gap)` entry explicitly routed to R2, and tell the user their data team received it. **CP-R5 [A]:** never publish results the user has not confirmed in CP-R4.

## 6. `enrich` skill

Serves J1 levels 1–3 and J2 trigger 3. Profile context: Steward.

```
scope → evidence → drafting → self-check → PR
```

**S1 scope.** Select a bounded batch (default ≤ 10 objects) from, in priority order: fault-ledger triage items assigned to enrichment, hot objects lacking human docs (index hot/stub status), harvested documents awaiting conversion. **CP-E1 [A]:** state the batch and its rationale before writing anything.

**S2 evidence.** Per object: machine doc (facts), harvest results whose `mentions`/content cover it, usage evidence where present (join_pairs → evidence-grade join guidance), existing entity docs. Maturity-ladder discipline (HLR §8 P4): the evidence tier available dictates the `sources` grading — `customer doc: <uri>`, `observed in N queries`, or `inferred from column names`; never upgrade inference to observation.

**S3 drafting.** Canonical templates (KB §7), one human doc per object (or group doc edits for API kinds). **CP-E2 [A]:** every draft carries complete front-matter with `status: draft`, graded `sources`, and a `depends_on` list covering every FQN the body relies on (the K-2 declaration duty). **CP-E3 [E-adjacent]:** the skill never sets `verified` and never touches `*.schema.md` — violations are caught by KB CI checks KB-3/KB-7 at PR time, so the gate is enforced at merge even if the skill misbehaves.

**S4 self-check.** Run the KB CI validation locally (front-matter schemas, FQN resolution, links) before opening the PR; fix or drop failing drafts.

**S5 PR.** One PR per batch, under the session user's identity (K-IDENT), body summarizing per-doc evidence grades; ledger-originated items carry `CL-Resolves: <issue-id>` trailers so merge closes the loop (ledger spec §9). *Failure exits:* insufficient evidence for a scoped object → skip it and record `flag_gap(missing_doc)` noting what evidence would unblock it — an honest skip beats a fabricated draft.

## 7. `review-sync` skill

Serves J2 trigger 1 review. Profile context: Steward.

```
ingest → impact → recommendation → [repair-plan]
```

**S1 ingest.** Read the sync PR: changelog, diff classifications, contamination markings, rename candidates, undeclared possible references (KB §6, §9).

**S2 impact. CP-V1 [A]:** produce the ranked summary — breaking changes first, each with its contaminated docs and the lineage paths that carried contamination; rename candidates presented with *both* interpretations and the evidence for each; undeclared references listed as reviewer attention items, explicitly marked non-authoritative.

**S3 recommendation.** Additive-only PR → "safe to merge" with the one-line reason. Breaking PR → per-doc repair list ordered by blast radius (how many downstream docs/metrics each repair unblocks). **CP-V2 [A/E]:** the skill never merges and never edits the sync PR itself; repairs are separate PRs (the KB-4 boundary makes sync-PR human-body edits impossible anyway; the skill additionally must not merge — attested, since merge rights are the customer's branch policy).

**S4 repair-plan (optional).** On request, draft the repair PRs: body-text fixes plus the human's status transition (`contaminated → verified` requires the human to clear `contamination` and refresh `written_against_schema_hash` per KB §5 — the skill prepares, the human certifies). *Failure exit:* a contamination whose repair requires business knowledge the KB lacks → K-FAIL `missing_doc`, naming the person from the doc's `last_verified` trail as the likely owner.

## 8. `benchmark` skill

Serves product-spec §11 Metric 1. Profile context: the dedicated `benchmark` profile (SK-4) — execute permitted, publish absent from the allowlist (suppression by profile, enforced [E]).

```
load → per-request journey → hand-off to harness
```

**S1 load.** Read the golden suite (repo location configured; requests + analyst-verified SQL/results). **S2 journey.** Per request, run the report skill's S1–S5 in benchmark mode: no clarifying questions (assumptions logged instead), no user confirmations (CP-R1/R4 are waived — there is no user; the waiver applies only under the `benchmark` profile). **S3 hand-off.** Emit, per request, the machine-readable journey record (resolved refs, drafted statement, validation verdicts, execution result ref) for the **deterministic harness**, which owns scoring — table-selection precision/recall, first-try executable rate, result correctness — and persistence to ops Postgres. **CP-B1 [A]:** the skill never scores itself; the harness compares against verified outputs. The same harness runs the suite in CI against KB changes (KB-9) without any skill at all where journeys are replayable.

## 9. Acceptance scenarios (per-skill, shipped with the product)

Each skill ships scripted scenarios executed against a fixture deployment (fixture KB + fixture snapshots + stub connectors), asserting on the audit stream and git effects:

| # | Scenario (representative, non-exhaustive) | Verifies |
|---|---|---|
| AS-1 | report: happy path — audit shows resolution reads *before* validate, validate before execute, one confirmation exchange before publish | CP-R1..R5 ordering |
| AS-2 | report: contaminated entity in the path → transcript contains the refusal + override offer; no execute occurs without override | K-TRUST |
| AS-3 | report: unresolvable request → `flag_gap` with correct kind; no execute call in audit; user told `routed_to` | K-FAIL |
| AS-4 | report: 3rd consecutive validation failure → stop + flag; no 3rd repair attempt | SK-7 |
| AS-5 | report: truncated result → disclosure present; reporting-view offer made | K-GROUND, SK-6 |
| AS-6 | enrich: drafts carry `draft` status, graded sources, non-empty `depends_on`; PR under user identity; zero edits to machine files | CP-E2/E3, K-IDENT |
| AS-7 | review-sync: rename candidate summarized with both interpretations; no merge action; no sync-PR edits | CP-V1/V2 |
| AS-8 | benchmark: run under `benchmark` profile; publish absent from tools/list; adoption-metric query over the fixture audit excludes the run | SK-4 |

## 10. Amendments to other specs (additive)

> **Status: applied.** Folded into home specs in the consolidation pass; retained as the change record.

1. **MCP tool reference §6.10:** `flag_gap.kind` gains `result_disputed` (SK-5). Additive to the enum.
2. **HLR §7.1:** the profile template set gains a fourth, non-user template — `benchmark` (SK-4): skills `[benchmark]`, tools = read set + validate + execute, no publish; not role-assignable to humans by default.
3. **MCP audit record (§8):** gains `profile`-derived tag surfacing benchmark runs for metric exclusion (already carried via `profile`; this amendment fixes the exclusion rule in the Audit module's adoption queries).

## 11. Open decisions (spec-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| SP-1 | Server-side heuristic for CP-R1 (execute observed with no prior resolution reads in-session) as a class-1 detector | Log-only heuristic in v1; not user-facing | After pilot audit review shows its false-positive rate |
| SP-2 | Benchmark-mode waivers (no confirmations) leaking into user profiles | Waiver is keyed to the `benchmark` profile name server-known; skills must check profile, scenario AS-8 guards | If profile spoofing is a concern in security review (it shouldn't be — profiles are server-bound) |
| SP-3 | `enrich` batch size default | 10 objects | Steward feedback on PR review ergonomics |
| SP-4 | report skill offering saved/parameterized re-runs of confirmed reports | Out of v1; re-run = re-journey | Recurring-report demand in pilot |
| SP-5 | Localization of user-facing skill language | Follows the session user's language naturally (LLM behavior); canonical checkpoint content defined language-neutrally | First non-English pilot |
