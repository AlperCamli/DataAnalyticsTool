# CP-8 — GO/NO-GO retrospective

**Date:** 2026-07-30 · **Scope:** review only; the amendment fence was
absolute. The one write authorized (and made) is the CP-7 part-C
bookkeeping: `DECISIONS.md` § "D-95 part C" and the CP-7 closure markers
in `plans/context-layer-development-plan-v1.md` §1/§7. No code, no spec,
no register, no KB change. Every recommendation below is tagged
**accept / amend / defer** for ruling; nothing here has been applied.

**The bar this report grades against:** *can this product onboard the
next customer from its own playbook, without the vendor in the loop?*
Where the bar is unmet, the finding is classified as blocking a **REAL**
onboarding (vendor present, doing the work) or only an **UNASSISTED**
one (customer's own staff, playbook in hand).

*Naming note:* the plan calls the example estate "customer 2" and the next
one "customer 3". This report says "the next customer" throughout to
avoid ambiguity with the prompt's "second customer".

---

## 0. Executive verdict

> **GO WITH CONDITIONS** for a real, vendor-assisted onboarding.
> **NO-GO** for an unassisted onboarding from the playbook alone.

The platform half is real and evidenced: snapshots are deterministic and
conformance-tested, drift produces reviewed PRs, identity and profile
enforcement hold server-side with denials on the record
(`audit_records`, 2026-07-20 / 07-27 / 07-29), governed execution
returns real rows under a database-level read-only role, and the M3
journey put an AI-designed, trust-annotated report into a real Power BI
workspace with a two-call attestation trail and F-4 lineage rows
(`report_attestations` ×2 on one `report_id`, 2026-07-29). That is a
product, not a demo rig.

What is not ready is the **onboarding-as-a-product**: the pilot's own
record shows that every step which touches the customer's infrastructure
was executed by the vendor from knowledge held outside the playbook —
DDL applied by hand, roles provisioned by hand, connections registered
through an admin CLI the playbook never mentions, tenant settings and a
service principal created by hand, the reporter's bundle carried to the
user's machine with `scp.exe`. The playbook describes a dashboard-driven
flow for several of these; the dashboard does not exist. Two knowledge
artifacts the gate itself depends on are also absent on the example estate
(zero certified metrics, 41 draft docs against 1 verified), and the
benchmark that would let anyone claim value is unmeasured and not
CI-wired.

### Conditions — blocking a REAL onboarding

| # | Condition | Why it blocks | Evidence |
|---|---|---|---|
| **C-1** | Land the `deploy/runner-config.yaml` Power BI connector line | It is still an **uncommitted working-tree change**. A clean checkout of `main` builds a runner that cannot claim a `powerbi` publish job — the exact blocker `READINESS-2026-07-29.md` called NO-GO. CP-7 is marked closed over unlanded work (D-74.2/D-82) | `git status`; `git diff deploy/runner-config.yaml` |
| **C-2** | Ship `review-sync`, or record its removal | The skill is specified (`specs/skill-specifications.md` §7, AS-7) and **named in the shipped steward profile** (`.contextlayer/profiles/steward.yaml` `skills: [enrich, review-sync]`), but `core/skills/` holds only `benchmark`, `enrich`, `report`. Compiling a steward setup today emits `profile names skill "review-sync", which this core release does not ship` — a **non-fatal warning** ([compile.ts:125](core/src/compile.ts#L125)). The steward's half of the drift loop (playbook gate item 7, journey J2) has no shipped tool | `ls core/skills/`; grep of `review-sync` |
| **C-3** | A supported path for bundle delivery **and** bundle freshness | PA-1 + PA-2. Every reporter start is a manual file copy today; a bundle compiled before a profile change silently narrows what the session will attempt — that is what ended the 2026-07-29 09:13 gate attempt | Master register PA-1/PA-2; `results/cp7-gate/interrupted-run-2026-07-29/` |
| **C-4** | Certified metrics + human-verified report-path docs on the estate | Playbook gate items 3 and 4 **fail** on the pilot: `origin/main` has **no `metrics/` directory at all**, and 41 `draft` / 44 `machine` / **1** `verified` doc. The gate report's own trust notes say so: *"All source docs are status=draft… the estate carries 41 draft docs and 1 verified"* and *"No certified metric exists for tokens-per-run"* | KB `origin/main`; `report_artifacts.body.semantics.trust_notes` |
| **C-5** | Benchmark wired into KB CI | Gate item 6's second half. `origin/main`'s `.github/workflows/kb-ci.yml` runs `generator.validate` and nothing else — no benchmark job, so KB-9's "any change that degrades accuracy is caught pre-merge" is not in force anywhere | KB CI workflow |
| **C-6** | Extract and commit the CP-7 gate evidence; carry the F-4 nodes into the KB | The demo's record exists only in a running container; `extract-audit.sh` was never run for the window. And CP-7 exit-gate item 2 (`get_lineage` walks from the report node) is **pending**: attestations are in ops, but `lineage/graph.json` on `origin/main` has 28 nodes / 25 edges and no report node | D-95 part C; KB `lineage/graph.json` |

### Additional conditions — blocking an UNASSISTED onboarding

| # | Condition | Evidence |
|---|---|---|
| **U-1** | Connections must be operable by the customer. Playbook §6 names a "dashboard Connections module"; registration is an admin CLI running direct-DB (D-63.8, "E2's Connections-UI stand-in") | playbook §6; D-63 §8 |
| **U-2** | The customer-DBA steps must be in the playbook, not in a session runbook. DDL apply, `execution-role.sql` / `introspection-role.sql`, the Power BI SP + tenant setting — all hand-run this pilot from `results/cp7-gate/RUNBOOK.md`, which is a gate script, not a playbook step | D-81, D-84.1, D-91.7 |
| **U-3** | The drift drill must be rehearsed with a human steward, not only in CI. Gate item 7's human half (*R2 runs `review-sync` → repair PR → docs re-verified*) has **never been performed**: `review-sync` appears nowhere in `DECISIONS.md` | grep; C-2 |
| **U-4** | OB-4 instrumentation must exist before it can measure anything. CP-0 task 0.3 / gate item 4 ("timers running") has **no implementation and no record** — no code, no `DECISIONS` mention. The next onboarding cannot be measured either, so OB-4's "measure the first three" is unstartable | grep for OB-4 |
| **U-5** | Small-cell suppression must have a threshold before any report leaves the team (SUPPRESS-1). The gate report itself surfaced 2- and 3-run cells and *labelled* them — honest, and entirely dependent on the agent's judgement | `trust_notes`; §1c below |

None of the six REAL-blocking conditions requires new architecture. C-1
and C-6 are chores; C-2 is one skill file plus its acceptance scenario;
C-4 and C-5 are estate/CI work the pilot skipped; C-3 is the one that is
genuinely a product surface (and is the seed of the Phase-2 dashboard
track).

---

## Part 1 — scheduled decisions

### 1a. BASELINE-1 (D-80.1) — the skipped three-condition baseline

**Evidence.** The rig is landed and re-runnable: condition builder +
isolation preflight (`benchmark/conditions.py`, `make conditions`,
`make preflight`), the MCP executor the journeys run through
(`benchmark/mcp_executor.py`), ingestion and deterministic scoring
(`make ingest` / `make status` / `make score`), the seed suite
(`benchmark/suite/benchmark-seed-v0.yaml`) with its pinned snapshots, and
the operator protocol (`OPERATOR.md`). The transport is proven: five
journeys ran clean end to end, scored, and committed
(`results/manual-20260716T103207Z/`, D-61), with the standing caveat that
they are transport-proof and **never citable as value evidence** (D-62.2).
Two corrections must ride the revival: QE-5 result canonicalization for
golden comparison, which may need one re-execution pass over the frozen
`verified_results` (D-85.5), and the `ai_runs.status` correction — the
CHECK-enforced `pending|completed|failed` vocabulary (D-86.3a) that a
`v_ai_runs_by_day`-shaped golden may assume is open text.

**Cost, from the built assets — the honest number is operator time, not
tokens.** The gate is 10 cases × 3 conditions × ≥1 rep = **30 journeys**
(D-62.3). D-61's five journeys ran *headless*, in parallel, all inside one
600 s invocation — so machine time for 30 is roughly **one hour** in six
parallel batches. But headless runs are explicitly **not baseline
records** (D-61), and the CP-5 gate says "via the skill in Claude Code";
D-62.5 already flagged that a strict reading needs literal interactive
sessions. Interactive, per `OPERATOR.md` §3–§4, each journey is: export
the log path, copy the prompt, launch a fresh session, paste, watch,
`/exit` — and any steer, crash, or rate-limit stop voids the journey and
costs a rerun.

- Setup: `make conditions` + preflight (enriched-KB pin has moved since
  the last build) — **~1 h**, including a `--force` rebuild.
- 30 interactive journeys at 5–15 min of attended time — **3–7 h**,
  realistically over 2–3 sittings against rate limits.
- Golden re-execution under QE-5 + suite corrections — **2–4 h**
  (D-85.5's pass, plus the RB-04 GA4 golden that is
  correctness-unwinnable until Signals is enabled or it is re-scoped,
  D-61).
- `make score` + reading the result — **~1 h**.

**≈ 8–13 hours of operator attention**, no engineering. Doing it headless
instead costs ~3 h total but produces numbers the project has already
ruled uncitable — which is the worst outcome available: the cost without
the claim.

**Recommendation — `defer`, with a hard gate.** Do **not** run it now:
CP-8 is a readiness review, and BASELINE-1's stated trigger is *"before
CP-8 go/no-go, **or** before the first external customer conversation
that would benefit from numbers"*. This report's verdict does not turn on
the number; the next customer conversation will. Carry the
**no-quantitative-KB-value-claims constraint into Phase 2 explicitly**
(it is easy to violate accidentally in a sales deck), and make baseline
v1 a **gated entry condition of the first onboarding that quotes value**
— not a Phase-2 checkpoint of its own. If the operator would rather have
the number in hand before any customer conversation, the honest schedule
is a dedicated two-day block, and it should be booked as such rather than
squeezed alongside onboarding work, because a steered journey is a void
journey.

### 1b. SS-5 — CHECK constraints dropped at the snapshot boundary

**Evidence.** The item stopped being hypothetical on 2026-07-27
(D-86.3b): the CP-7 enrichment run had to read `pg_constraint` out of
band to document enum vocabularies, and — worse — the gap had already
produced a **false claim about the customer's estate**.
`deploy/reporting-views.sql` and D-81's rationale both called
`ai_runs.status` "free text with no CHECK constraint" and "its vocabulary
is ungrounded", when `ai_runs_status_check` enforces
`pending | completed | failed` and `ai_runs_completion_consistency_check`
ties that vocabulary to `completed_at`. A reader working only from the KB
saw no constraint and took **our blind spot for the source's vocabulary
being open**. That is the product's core failure mode — a confident,
grounded-sounding statement that is wrong because the grounding surface
omitted the fact — and it happened to us, in our own file, on our own
estate.

**Options.**
1. **Capture** — additive registration on `table`: hash-included
   `stats.checks` carrying `pg_get_constraintdef(oid)` strings (the
   register's own proposed path).
2. **Affirm the drop** with a documented mitigation (an enrichment
   convention: "read `pg_constraint` when documenting a status column").
3. **Capture narrowly** — only single-column CHECKs on columns the
   generator already renders, dropping table-level and expression CHECKs.

**Recommendation — `amend`, option 1, scoped tightly.** Severity: high
for correctness, low for effort. The mitigation option fails on the
evidence: a convention is exactly what did not hold, and the false claim
was written by a careful session that had every reason to be careful. The
capture is genuinely additive under S-7 and the scope is small:

- **What:** on `kind: table`, a hash-**included** `stats.checks: [str]` —
  the verbatim `pg_get_constraintdef(oid, true)` text of every
  `contype = 'c'` constraint on the table, sorted lexicographically for
  determinism. Verbatim strings only, honouring S-8 (facts, never
  synthesized prose): no parsing into enum sets, no vocabulary inference.
- **Where the boundary sits:** Postgres only (the API connectors have no
  analogue); no new `kind`; `NOT NULL` stays out (already expressed);
  domain and exclusion constraints stay out (SS-6/SS-7 territory).
- **Why hash-included:** a dropped or widened CHECK is a semantic change
  a report can be wrong about — it must be able to contaminate a doc.
  That makes it a **breaking-diff-capable** field, which is the point.
- **Cost:** one catalog query in the postgres connector, one schema
  registration, C-1/C-2/C-3 re-verified against the example estate, one
  generator template line, one additive drift PR on the customer KB.
  Half a day, plus the wheel rebuild D-46 requires.
- **Register consequence:** SS-5 moves Open → **Closed by capture**;
  SS-6 (enum type labels) explicitly stays Open — this decision does not
  pre-empt it, and the two should not be bundled.

### 1c. SUPPRESS-1 — small-cell suppression

**Evidence.** The estate is a small fixture user population. Every report so far has been the
owner reading their own data, which is why M3 proceeded without a
threshold (D-86.4). But the gate report is the first artifact where the
question became concrete, and the record is instructive: the artifact's
own trust notes carry

> "SMALL CELLS — NOT FOR EXTERNAL DISTRIBUTION: professional_summary
> (3 runs) and multi_option (2 runs). On a ~24-user estate the source docs
> treat groups of 1-2 as potentially personal even though no column names
> anyone."

and the layout renders that table with a note rather than suppressing the
rows. So today's behaviour is: **the agent notices, labels, and publishes
anyway** — into a Power BI workspace whose access is a workspace
membership list, not a product-enforced audience. The honesty rule
carried it; nothing else did. There is no threshold in any profile, in
any view, in the artifact schema, or in the publisher.

**Where the threshold should live — recommendation.** Not one place;
**two, with a clear division**, and explicitly *not* in the skill design
rules:

1. **Profile limits (MCP §3 / profile `limits:` block) — the enforcement
   point.** `limits:` already carries `row_cap` and `timeout_s`, is
   **injected server-side on every call** and cannot be widened by a
   client (MCP-R8). A `min_cell_count: n` alongside them is the only
   candidate that is enforceable, per-customer, per-profile, and
   auditable. Enforcement shape: the publish path (F-7 re-validation, which
   already re-runs every artifact query) refuses an artifact whose result
   sets contain a cell below the threshold in a column declared as a
   count/`distinct_*` measure, with the existing actionable-error shape.
2. **Formats/trust rules — the disclosure point.** The artifact records
   `suppression: {threshold: n, cells_suppressed: k}` so the report can
   say what was withheld. Suppression that is invisible is its own
   integrity problem.
3. **Not the skill design rules.** The skill is the right place to *warn*
   and it already does, well. It is the wrong place to *enforce*: it is
   client-side, it is the surface a user can talk out of a decision, and
   SUPPRESS-1 exists precisely because "the docs warn, nothing enforces".

**Blocking classification: it does not block onboarding the next
customer; it blocks that customer's first external-audience report.**
Which, on the evidence of this pilot, arrives roughly one week after
onboarding. Treat it as an early-Phase-2 item with a **named trigger in
the onboarding record** ("first report with an audience beyond its
author"), not as a gate. Tag: **`defer` with the trigger tightened** —
amend SUPPRESS-1's row to name the profile-limits home and the
publish-path enforcement point, so the decision at trigger time is a
value, not a design.

### 1d. RA-F — push-API deprecation and the Fabric/DirectLake decision

**Date confirmed from the pinned reference**, not from memory:
`connectors/powerbi/reference.py` pins
`PUSH_MODEL_DEPRECATION = {"new_model_creation_supported_until":
"2027-10-31", "existing_models": "unaffected", "ref":
"realtime-retirement"}`, sourced from the Microsoft realtime-retirement
page as updated 2025-12-04, and asserted by
`tests/test_powerbi_reference.py:193`. The date is a **new-model-creation
cutoff**; models already created keep working. It matches RA-F's row and
D-92.2's trigger. ✔

**What the date actually costs us.** Every new customer onboarded onto
the Power BI leg creates *new* push models — one per artifact id (§5).
So the deadline is not "our reports stop working in 2027"; it is **"after
2027-10-31 we cannot onboard another Power BI customer on the v1 data
plane"**. That reframes it from a maintenance date to a **sales-capacity
date**, and it interacts with RA-D (one workspace per deployment) and
SO-G (nothing refreshes a delivered model) — the three are one design
conversation, as RA-G already notes.

**Recommendation — `defer` the build, `amend` the trigger to a decision
date.** Severity: medium, ~15 months of runway. Do not build DirectLake
now: it is a new storage tier (lakehouse + capacity) that would land
untested against a v1 the pilot has barely exercised. But do not leave
the trigger phrased as "the first onboarding after mid-2027" either —
that dates the *decision* to the moment it is most expensive. Recommend:

- **Decision due 2027-01-31** (≈9 months before the cutoff, ≈6 months of
  build runway), or **immediately on the first `push_limit_exceeded`
  capability failure**, or **on the second Power BI customer**, whichever
  comes first. The second-customer clause is the real one: two customers
  on push is the point at which the escalation stops being hypothetical
  and the workspace/naming questions (RA-D) bind.
- Add one cheap thing now, in Phase 2 rather than at the deadline: the
  publisher already knows `PUSH_LIMITS`; have it emit a **warning at 80 %
  of any limit** so the scale trigger fires from telemetry instead of
  from a failed customer publish.

### 1e. JC-4 and the docker-heavy sync flake

**Time-boxed diagnosis, from test code and the recorded history only — no
test runs were made this session.**

**JC-4 — diagnosed, and it is not a product defect.** The failing test is
[e2e.test.ts:225](core/test/e2e.test.ts#L225). The decisive fact is in its
setup: [e2e.test.ts:103](core/test/e2e.test.ts#L103) starts the core with
`{ leaseTtlS: 2, sweepIntervalMs: 200 }`, and the SDK's heartbeat
interval defaults to **lease TTL ÷ 2** ([service.py:103](connectors/sdk/service.py#L103),
`_default_interval`) — so a **1 s heartbeat against a 2 s lease**. That is
a 2:1 margin, and the runner is a Python process doing an HTTP POST on a
worker thread. Meanwhile production runs `CORE_LEASE_TTL_S = 60`
([config.ts:261](core/src/config.ts#L261)), and **every other suite** uses
the 60 s default with the sweeper effectively off
(`sweepIntervalMs: 60_000`, [helpers.ts:107](core/test/helpers.ts#L107)).
`e2e.test.ts` is the only file that compresses it.

On a saturated machine, one scheduling stall over ~1 s expires a **live**
lease; the sweeper picks it up within 200 ms, writes `lease_expired`, and
requeues with `attempt + 1` while runner A is still working
([queue.ts:821](core/src/queue.ts#L821)). Everything downstream in the
test then mismatches: `expect(requeued.attempt).toBe(2)` sees 3, or the
state machine thrashes through an extra claim/expiry cycle and one of the
15 s / 30 s waits times out — which is exactly the reported symptom
("lease-expiry timeouts", 35.3 s, D-85). The counterfactual already on
record — identical failure with the changes stashed, pass in isolation at
21 s — fits this and rules out a regression. `batch` jobs allow 5 attempts
([registry.ts:22](core/src/registry.ts#L22)), so nothing dead-letters;
the test simply asserts a state sequence that a spurious expiry perturbs.

**Recommendation — `accept` the fix (test-only), tagged for a Phase-2
chore, not a blocker.** The product behaviour under test is correct; the
harness under-provisions the margin it needs. Proposed diff **(proposed,
not landed — per the scope fence)**:

```diff
--- a/core/test/e2e.test.ts
+++ b/core/test/e2e.test.ts
@@ -66,6 +66,11 @@ async function spawnRunner(
       runner_id: runnerId,
       connectors,
       classes: ["batch"],
+      // Pin the heartbeat instead of inheriting lease_ttl/2. The SDK's
+      // default would give a 1 s beat against this file's compressed
+      // lease, and one scheduling stall on a loaded machine then expires
+      // a LIVE lease — the JC-4 flake (D-85/D-86.2, watch item).
+      heartbeat_interval_s: 0.5,
       wait_s: 2,
       claim_backoff_s: 0.5,
       resolver: { kind: "process-env" },
@@ -100,7 +105,10 @@ let runnerB: RunnerProc | null = null;
 
 beforeAll(async () => {
-  core = await startCore({ leaseTtlS: 2, sweepIntervalMs: 200 });
+  // 8 s lease + 0.5 s heartbeat = 16:1 margin (production is 60 s).
+  // Still short enough that JC-4's reclaim happens inside the test's
+  // budget; long enough that suite load cannot expire a live lease.
+  core = await startCore({ leaseTtlS: 8, sweepIntervalMs: 200 });
   client = new WireClient(core.baseUrl, TEST_TOKEN, TEST_OPS_TOKEN);
@@ -236,7 +244,7 @@ it("JC-4: runner killed mid-job → reclaim by a second runner ...
-  // lease (2 s) expires; sweeper (200 ms) requeues with attempt+1
-  const requeued = await client.waitForState(jobId, ["queued"], 15_000);
+  // lease (8 s) expires; sweeper (200 ms) requeues with attempt+1
+  const requeued = await client.waitForState(jobId, ["queued"], 25_000);
   expect(requeued.attempt).toBe(2);
 
   runnerB = await spawnRunner("runner-b1", ["tests.job_fixtures.slow_demo:connector"]);
-  const done = await client.waitForState(jobId, ["succeeded", "dead_lettered"], 60_000);
+  const done = await client.waitForState(jobId, ["succeeded", "dead_lettered"], 90_000);
   expect(done.state, JSON.stringify(done.error)).toBe("succeeded");
   expect(done.runner_id).toBe("runner-b1");
-}, 120_000);
+}, 180_000);
```

`expect(requeued.attempt).toBe(2)` is deliberately left strict: with a
16:1 margin a spurious expiry is a real signal and should still fail.
Verification standard for the fix: three consecutive full-suite runs
**with a docker build running alongside** — reproduce the load, don't
avoid it.

**The docker-heavy sync flake — different animal, `quarantine-with-trigger`.**
It is *not* lease-related: `sync-drill`, `sync-run` and `sync-triggers`
all call `startCore({})`, i.e. 60 s lease and a 60 s sweep
([sync-drill.test.ts:81](core/test/sync-drill.test.ts#L81)). Its
load-sensitivity comes from what the drill actually does: a disposable
`postgres:16` container per vitest run ([global-setup.ts](core/test/global-setup.ts)),
plus a real Python SDK runner process, an **ephemeral Postgres for the
ddl-file introspection**, and git scratch repos — container readiness is
polled against a wall-clock deadline. Contention there is a
container-start-latency problem, not a protocol one, and diagnosing it
properly needs the failure output, which is not on record (the READINESS
report names only *"one `property.test.ts` `deferJob` transaction
failure"* alongside the two e2e timeouts). **Recommendation:** keep
D-92.3's accepted standard (two consecutive green full runs on an idle
machine) as the interim, and **add a trigger**: the next occurrence must
be captured with full output into `results/` before it is re-run green.
The current practice — re-run until green, record the green — is how a
real defect stays invisible. Severity: low now, medium if it ever fires
in a customer's CI.

---

## Part 2 — standing risk acceptances: carry or close

| # | Acceptance | Origin | State today (evidence) | Recommendation |
|---|---|---|---|---|
| **R-1** | **Customer KB is public** — owner's own data, confidentiality waived | D-80.2(a) | `github.com/AlperCamli/DataAnalyticsTool` is public (D-47). The KB now carries reporting-view semantics, entity key mappings, and a certified `entities/page.md` — i.e. a readable map of the estate. Its own revisit trigger reads *"revisit before any real second customer"* | **CLOSE by honouring the trigger.** The trigger fires the moment the next customer is scheduled. `amend` — the next customer's KB is private from bootstrap, and the pilot KB either goes private or is explicitly kept public as a reference estate with a one-line note in its `index.md`. Do not carry this silently into a two-customer world |
| **R-2** | **Leaked exec DSN + service-account key: rotation deferred** | D-80.2(b) | **Partly honoured.** The trigger fired at the second-machine session and the exec password was rotated end-to-end, verified live (D-84.1). The **service-account key half (GA4/GSC) was still `pending` at that entry** and no later entry records it done | **CARRY only if the SA recycle is confirmed; otherwise it is an open item, not an acceptance.** `accept` — operator confirms the GA4/GSC SA key recycle, or schedules it before the next customer. One line of evidence closes it |
| **R-3** | **Git-history exposure of the leaked credentials** | implied by R-2 | **Checked this session: clean.** `.secrets/` is git-ignored (`.gitignore:3`) and `git log --all -- .secrets/` returns nothing — no secret file was ever tracked. The three tracked files matching `postgresql://` are connector code and tests with synthetic DSNs. The exposure was chat/session-side, not repository-side | **CLOSE.** `accept` — record that the check was made and came back clean, so no history rewrite is contemplated later on a rumour |
| **R-4** | **`.secrets/` handling discipline** | JC-8, D-86 standing practice | Discipline holds: `chmod 600`, references-not-values in every config (`dsn_env`, `credentials_file`), JC-8 canary green in `e2e.test.ts`, and the `re.subn` near-miss produced a durable rule (read-back after any secrets-file write, D-86). But the **model is a directory of plaintext files on one laptop**, which is not the shape a customer deployment can use (playbook §4 assumes a vault) | **CARRY for the pilot; `amend` for Phase 2** — the first customer install must use the vault path the playbook already specifies, and the `.secrets/` pattern must be named in the playbook as *pilot-only*, or it will be copied |
| **R-5** | **SP scoping per RA-10** ("member of the designated workspace(s) only") | D-91.5, authoring spec §10 | **Stated, not asserted.** `connectors/powerbi/preflight.py` checks that the target workspace **is among** those the SP can see (`member = env.workspace_id.lower() in ids`); it never checks that it is the **only** one — `len(ids)` appears solely in the failure message. Least privilege here is a human promise | **CARRY with a cheap hardening.** `amend` — add an advisory preflight line when the SP sees more than the configured workspace(s). Not a blocker (delivered data is exec-role aggregates), but it is the check RA-10 implies and it costs three lines |
| **R-6** | **PAT holds workflow-write (the wheel carry)** | security review #2 **F7**, adopted 2026-07-20 | **Still in force, structural fix not done.** `kb-ci.yml` still pins the wheel by filename in the workflow (`.github/vendor/contextlayer_snapshot-0.5.0-py3-none-any.whl`), so carrying a wheel still requires editing a workflow file. Mitigation (c) is *effectively* present — CODEOWNERS is `* @AlperCamli`, which covers `.github/**` — but by wildcard, not by intent. D-84.5 records the carry not triggering recently (both sides 0.5.0), which is luck, not resolution | **CARRY for the pilot; `amend` before the next customer.** Do fix (b): move the wheel filename into a non-workflow config the workflow reads (e.g. `.github/vendor/VENDOR-MANIFEST.yaml`, which already exists and already names the version). Then the sync PAT drops workflow-write and the blast radius returns to "propose content a human reviews". On a customer repo the wildcard-CODEOWNERS accident will not repeat |
| **R-7** | **Wheel-relocation motion** | D-46 update path | No relocation motion is on record anywhere in `DECISIONS.md` or the specs — the only related item is F7 above. **Recommend not carrying a phantom**: the actionable item is R-6's option (b), which *is* the relocation | **CLOSE as duplicate of R-6.** `accept` |
| **R-8** | **Fixture profiles must track product profiles** | D-79 watch-note | Held once by luck and once by discipline: D-83 records the fixture reporter tracking KB PR #23. But the divergence class is live — the fixture steward profile (`mcp-helpers.ts:99`) declares `skills: [enrich, review-sync]` exactly as the product profile does, and **neither can be satisfied** (C-2). The watch note has no mechanical enforcement | **CARRY, `amend` to a test.** A test asserting that every skill named by any shipped profile (fixture or KB) exists in `core/skills/` would have caught C-2 the day `review-sync` was skipped. That is a five-line test and it closes both R-8 and part of C-2's detection story |

---

## Part 3 — the playbook walk-through (readiness verdict)

Graded against `specs/customer-onboarding-playbook.md`, step by step, as
if onboarding the next customer tomorrow. **PASS** = the playbook text
suffices. **ASSISTED** = it works, but only with vendor knowledge that is
not written down. **FAIL** = the mechanism is missing.

| Step | What the playbook says | What the pilot actually did | Grade |
|---|---|---|---|
| **1 — inputs / ask list** | Issue the ask list; receive sources, platform facts, BI target, 10–50 seed requests, named counterparts | Done in substance: the seed packet exists (`benchmark-seed-v0.yaml`, 10 cases) and drove both the benchmark and the task-7.0 view scope (D-81) | **PASS** |
| **0 — discovery & topology** | Classify every source/target on P1–P5; record signed off by R2/R3 | The classification exists implicitly (P1-B/C, P2-C governed direct-OLTP, P4-L1/L2, P5 changed mid-flight from `template_link` to `api`). **No topology record artifact exists** in the repo or KB — it lives in the specs' prose and in `.secrets/connections.md` | **ASSISTED** — the decision tree is real, the record is not. A customer's R3 could not produce this document from the playbook |
| **1 — platform install** | Compose bundle / Helm; wire OIDC; **register the vault**; runner vault identity. Exit: dashboard reachable, OIDC login, runner claims a no-op | Compose stack works and is the tested path. OIDC works (`devidp` container; real IdP wiring never exercised against a customer IdP). **The vault does not exist** — credentials are `.secrets/*.env` files resolved by `process-env` (`resolver: {kind: "process-env"}`). **Exit criterion "dashboard reachable" is unsatisfiable** — there is no dashboard | **FAIL** (as written) — two of the three exit conditions cannot be met by any customer. The install itself is ASSISTED-grade |
| **2 — KB repo bootstrap** | Generator bootstraps `index.md`, `conventions.md`, `.contextlayer/` (`sources.yaml`, `sync-policy.yaml`, `roles.yaml`, `profiles/`, `dashboard.yaml`) + KB CI installed | Real and repeatable — this is the product's strongest onboarding step (task 1.6, D-45/D-46/D-47). Caveats: the vendored-wheel update path is manual and its failure mode is silent (D-46), and `dashboard.yaml` is bootstrapped for a module set that does not exist | **PASS**, with the wheel caveat (R-6) |
| **3 — connect sources → first snapshots** | Per-source P1 flow via the **dashboard Connections module**; sync policy per source; exits: one accepted snapshot per system, health green, triggers armed | Every connection was registered by hand through the **admin CLI running direct-DB** (D-63.8, explicitly "E2's Connections-UI stand-in"), and the pilot's own record shows this failing quietly twice: the `looker_studio` connection "had never been registered" and a drift PR "had never been opened" despite both being claimed done (D-84); and GA4/GSC were still unregistered on the stack the day before the gate (READINESS item c). The onboard skill (`.claude/skills/onboard/SKILL.md`) documents a **different, local-CLI path** that writes snapshots to `~/Desktop` — vendor tooling, not the product path | **ASSISTED**, verging on FAIL for unassisted. The mechanism exists (jobs, runners, snapshots, health); the *operable surface* is a vendor CLI |
| **4 — generation: machine KB** | Deterministic render + lineage; lands as the initial generation PR; R2 merges. Exit: an agent reading only the merged KB describes the estate | Works, and is conformance-tested (KB-8 idempotency, C-2/C-3, D-50 exit evidence). Lineage from view SQL is real (`graph.json`, 28 nodes / 25 edges) | **PASS** |
| **5 — enrichment (P4 ladder)** | `enrich` under Steward; drafts land as PRs, `status: draft`; **exit: hot objects documented, every L1-derived report-path doc human-verified** | The drafting half works well (PRs #21, #26 — real semantics on the reporting views). The **certification half did not happen**: `origin/main` carries **41 draft / 44 machine / 1 verified**. The single verified doc (`entities/page.md`) was certified on 2026-07-29 as a gate prerequisite, under an explicit delegation ruling (D-94.5). The gate report ran on drafts and said so in its trust notes | **FAIL** on the exit criterion. The machinery is right (KB-7 blocks agent certification); the human act never scaled past one document |
| **6 — entities & metrics** | Entity docs for the concepts seed requests need; **metric docs seeded from the customer's own SQL, each with per-system `implementations` and an owner**. Exit: every seed request resolves to entities + certified metrics | Entities: three exist (`user`, `page`, `conversion`) — real, with key mappings (task 1.8, D-51). **Metrics: there is no `metrics/` directory at all.** D-81 already recorded this ("the KB has no `metrics/` catalog"), and the gate artifact's trust notes confirm the consequence: *"No certified metric exists for tokens-per-run"* | **FAIL** — half the step was never executed on the pilot |
| **7 — profiles, roles, dashboard** | OIDC groups → `roles.yaml`; instantiate four profile templates; **export the one-click Claude Code setup**. Exit: pilot user connects with the exported setup and `tools/list` shows exactly their allowlist | Profiles and enforcement are the strongest part of the product: server-side, per-call, with real denials on the record. But **profile changes are raw KB PRs hand-authored by a session** (PRs #23, #27, #28 — and #27 shipped without its `CL-Resolves` trailer, so a second PR was needed to close the gap), and **the "export" has no delivery path** (PA-1): the bundle was compiled on machine 1 and copied with `scp.exe`. The exit criterion is met; the step's stated components (dashboard Profiles module, one-click export) do not exist | **ASSISTED** |
| **8 — golden benchmark baseline** | Convert seeds to the golden suite; run three conditions; **wire the suite into KB CI (KB-9)**. Exit: baseline scores in ops Postgres, dashboard Benchmarks module shows the comparison | Suite and harness exist and are proven end-to-end (D-58/D-61). **The baseline was skipped by explicit decision** (D-80.1) and **KB CI has no benchmark job**. No scores in ops Postgres; no Benchmarks module | **FAIL** |
| **9 — readiness gate & handover** | Nine checklist items, all mechanically verifiable | See the item-by-item table below | **FAIL** as a whole (items 3, 4, 6 do not hold; item 7's human half unrehearsed) |
| **§11 — KB distribution model** | Four access forms; live projection is the default | Rows 1–3 are real (MCP projection, profile fragments, git working copies). Row 4 (compiled bundle) is still OB-1-deferred — but note the **compiled *setup* bundle** (PA-1/PA-2) is a different artifact that turned out to be load-bearing and undelivered | **PASS** for the model; the delivery gap is C-3 |

### §9 readiness-gate mapping — does the plan's claim hold?

| Gate item | Plan says passes at | Holds? | Evidence |
|---|---|---|---|
| 1 — snapshots accepted, health green, triggers armed | CP-1 / CP-3 | **Yes, with a scar** | `accepted_snapshots` populated; triggers armed. The scar is D-84.2: the pilot ran **two days with sync silently disabled** by a compose env-precedence slip, drift accruing unpublished, `/healthz` reporting `sync_enabled` to nobody (register SO-F) |
| 2 — machine KB merged, estate-description session | CP-1 | **Yes** | D-50 (task 1.8 landed / CP-1 closed) |
| 3 — hot objects documented, report-path docs verified | CP-1 (1.7/1.8), deepened CP-5 | **No** | 41 draft / 1 verified on `origin/main`; the gate report cited only drafts |
| 4 — every seed request resolves to entities + **certified metrics** | CP-2 | **No** | No `metrics/` directory; D-81 records it as a standing KB defect |
| 5 — profiles enforce for a real pilot user (MT-1) | CP-4 | **Yes — the best-evidenced item** | Real `denied` rows: `execute_sql … only for supabase, not ga4` (2026-07-20, 2026-07-27 ×4), `publish_report … only for looker_studio, not google_sheets` (2026-07-29) |
| 6 — benchmark baseline recorded, CI-wired | CP-2 | **No, on both halves** | BASELINE-1 skipped (D-80.1); KB CI runs only `generator.validate` |
| 7 — staged drift drill end-to-end (**incl. R2 runs `review-sync` → repair PR → docs re-verified**) | CP-3 | **Machine half yes; human half never rehearsed** | Drill fixture shipped (`fixtures/drill/`, `core/test/sync-drill.test.ts`, SO-4/SO-8) — the OB-3 closure is real. But `review-sync` is unbuilt (C-2) and appears nowhere in `DECISIONS.md`. Note also: **OB-3 is still marked Open in the master register** although sync spec §12.2 says "Closed… Master register updated" — the same is true of **JP-4** (§12.1), and the master register has **no SO-\* section at all** (noted, unfixed, in D-84.2) |
| 8 — first real J3 journey with publish per the P5 ceiling | CP-7 | **Yes for the single-source journey** | Four succeeded `powerbi` publish jobs; two attestations on one `report_id`; F-4 lineage rows. The cross-source half rests on attestation alone (D-95 part C) |
| 9 — role/credential least-privilege, three identities (D-72.4) | CP-6 / D-71 | **Yes for the two database identities; partial for the third** | `contextlayer_exec` read-only at DB level with a startup check that fails closed (G3, D-70 — the artifact is executed by tests); `contextlayer_introspect` measured `rolsuper=f, rolbypassrls=f` (D-84.4), with the C-3 byte-identity comparison done and its confound named. The **sync PAT is fine-grained and single-repo but holds workflow-write** (R-6), which the item's own wording does not permit ("contents + pull-request write and nothing else"). Add: OB-5 (profile↔database-role pairing) is still a stated obligation with **nothing checking it**, and it becomes load-bearing at the first customer with two execute-granted profiles |

### Verdict sentence

> **The platform passes; the playbook does not.** Six of ten steps are
> PASS or ASSISTED and would carry a real onboarding with the vendor in
> the room, but three steps (5, 6, 8) have exit criteria the pilot itself
> never met, one step (1) names exit conditions no customer can satisfy
> because the vault and dashboard do not exist, and the §9 gate fails on
> items 3, 4 and 6 with item 7 half-rehearsed — so the next onboarding is
> **GO with the vendor operating it and the six C-conditions closed**,
> and **NO-GO as a self-service playbook** until the Phase-2
> product-flow track lands.

---

## Part 4 — product-feel journey audit (the polish inventory)

Traced end to end from the pilot's own record. Severity: **S1** = a real
user stops or is misled · **S2** = real friction with a workaround ·
**S3** = papercut.

### Onboarding → first sync

**F-1 (S1) — Connections are a database, not a product.**
*What a user feels:* "I connected GA4 — why does the demo say it isn't
registered?" *Today:* registration is an admin CLI writing direct-DB;
there is no list, no test button, no health view, and no confirmation
that survives a session. The pilot's own record has two claimed-done
registrations that were never made (D-84) and GA4/GSC unregistered the
day before the gate (READINESS item c). *To close:* the Connections
module — list + register + test + health, over the job API that already
exists. (One line: build the read+write API and the module.)

**F-2 (S2) — Two onboarding paths, one product.** The `onboard` skill
drives `connectors.sdk.local` into `~/Desktop/kb-snapshots/`; the product
path is register → job → runner → accepted snapshot. Both are correct;
nobody is told which one they are on, and only the second produces the
state the rest of the product reads. *To close:* mark the skill
explicitly as vendor bootstrap/diagnostic tooling, and make the product
path the documented one in the playbook.

**F-3 (S1) — Credentials are plaintext files on the operator's laptop.**
The playbook promises vault references (J-4); the deployment resolves
`process-env` from `.secrets/*.env`. It works and it is disciplined
(JC-8 canary, read-back rule after the `re.subn` near-miss, D-86) — and
it is not something a customer's security contact can accept. *To close:*
one vault resolver behind the existing `resolver:` seam (the seam is
already there — this is a plugin, not a redesign).

**F-4 (S2) — DDL and roles are hand-applied, correctly, by design — and
invisibly.** "We never run DDL against the customer estate" is the right
rule (D-81), but the product gives the DBA nothing: no generated,
reviewable file to hand over, no acknowledgement that it was applied, no
detection that it wasn't. The pilot found `reporting.*` views missing
only when queries came back empty (D-80.3). *To close:* a "pending DDL
handover" state with an applied/not-applied probe — the exec role's
startup check already proves the pattern works.

### Profile / identity setup

**F-5 (S1) — Profile changes are raw pull requests, hand-authored.** To
give a reporter one publish target, a session hand-wrote a YAML PR, and
**PR #27 shipped without its `CL-Resolves` trailer**, so the ledger gap
did not close and PR #28 had to be authored to do it (READINESS item d,
`l5-loop-closure/`). A steward with a form would not have to know the
trailer exists. *To close:* Profiles module — edit → PR with the trailer
generated → merge.

**F-6 (S1) — The bundle reaches the user by `scp`, and nothing tells it
it's stale.** PA-1 + PA-2, and both bit at the gate: delivery fell back
to `scp.exe` from a Windows client (D-88.1), and a bundle predating a
profile change **silently narrowed** what the session would attempt,
ending a gate attempt with a filed gap instead of a report (D-94.3,
`interrupted-run-2026-07-29/`). This is the single highest-value polish
item in the inventory: it is the first thing every user of every
onboarding touches. *To close:* served, authenticated setup download +
compile-on-profile-change (or a staleness signal the session can read).

**F-7 (S2) — Compiling a profile that names a missing skill warns and
proceeds.** `compile.ts:125` pushes a warning to a `warnings[]` array; a
steward bundle today ships without `review-sync` and nothing stops it.
*To close:* fail the compile, or surface warnings where the operator
must acknowledge them.

**F-8 (S2) — The reporter must hand-set Power BI credentials on their own
machine.** The gate hit exactly this at 11:43:26: a `capability_gap`
filed because `POWERBI_TENANT_ID/CLIENT_ID/CLIENT_SECRET` were "literal
angle-bracket placeholder text" and `POWERBI_FABRIC_TOKEN` unset — deep
in the flow, **after** `deliver_model` had already succeeded, with an
error about "parameter tenantId has an unsafe value". The user's report
was half-built when it failed. *To close:* validate the session's
publish-side credentials at session start (the preflight already knows
how), and make the failure arrive before any work is done.

### Asking a question → gap → enrichment → drift

**F-9 (S2) — Gaps are filed beautifully and triaged nowhere.** The ledger
works: 11 open issues, correct routing (`data-team`), occurrence counting
(issue `8f8a233d` reached its **3rd occurrence** across three separate
sessions — the same missing daily-token view, requested three times).
There is no queue anyone looks at; `list_gaps` exists as a tool, but only
a steward *in a Claude Code session* ever sees it. *To close:* KB Health
triage queue (the API is `list_gaps` + the ledger tables — already
built).

**F-10 (S2) — A capability gap has no reply path.** The reporter files a
gap; the steward resolves it with a PR trailer; **the reporter is never
told.** L-5 closure is recorded server-side (verified at the gate:
`6473a5f1` → `resolved / pr / pull/28`), and the only person who learns
it is whoever runs the sweep. *To close:* the resolution should surface
in the next session (a `report_freshness`-style "gaps you filed were
resolved" line costs nothing).

**F-11 (S3) — Enrichment batches are steward-initiated with no worklist.**
The loop closes, but the steward has to know what to enrich. The ledger
already ranks by occurrences and `distinct_subjects` — nothing renders it.

**F-12 (S1) — Configured-but-disabled sync is silent.** Two days of
unpublished drift on the pilot, health green throughout (D-84.2, SO-F).
`/healthz` reports `sync_enabled`; nothing consumes it. *To close:* a
freshness/health surface that consumes it, or an alert. This one is a
correctness risk, not a polish item: the KB was silently stale while the
product reported itself healthy.

**F-13 (S2) — Drift PRs land in a review flow with no reviewer tooling.**
PR #25 was reviewed by reading the diff (D-84.3). `review-sync`, the
skill specified to summarize and risk-rank exactly this, is unbuilt (C-2).

### Report → publish → revise

**F-14 (S2) — The CP-R4 pause is a good rule with a bad shape.** The
checkpoint is real and held under pressure (D-93.1) — but it is a
conversational confirmation only the transcript records, which is why
**Act 3a and Act 2 of the gate cannot be evidenced from the server** at
all (D-95 part C). *To close (design note for Phase 2, not a mechanism
change):* have the skill record the confirmation as a structured line the
artifact carries, so "the human confirmed" becomes evidence rather than
recollection. The server still cannot check whether a human nodded; it can
at least record what the session says happened.

**F-15 (S2) — Publishing is a two-call contract with an invisible middle.**
Three `deliver_model` calls preceded the first `attest` at the gate
(11:39:53, 11:41:02, 11:41:55 → attest 11:54:13) — twelve minutes in
which the user is watching an agent retry. Nothing surfaces "delivered
but not yet attested" to anyone but ops. *To close:* the publish
deliveries view (dangling deliveries are already a designed loud state —
they just have no viewer).

**F-16 (S3) — The publish budget is an env var.** The demo needed
`CORE_MCP_PUBLISH_PER_HOUR=12`, added as a compose passthrough with a
test (D-94.4). A rate limit a user can hit should be a profile limit
they can see, not a container variable.

**F-17 (S2) — Revision is real, and unlabelled.** AT-6 worked live: same
`report_id`, new `definition_hash`. But the artifact's revision 2 quietly
substituted `line` → `bar` (push datasets cannot back a continuous date
axis) — the right call, recorded in trust notes, and **invisible to the
user** unless they read them. *To close:* surface "what changed in this
revision" at hand-off.

**F-18 (S1, latent) — Nothing retires a report.** RA-G, filed but
undecided: a dropped reporting view leaves a semantic model refreshing
against nothing, and `publish_report` has no `retire` mode. Pairs with
SO-G — **nothing re-delivers a model either**, so a "live" Power BI
report is a point-in-time copy the viewer cannot distinguish from a
current one. The trust element mitigates misreading; it does not stop the
number being old.

**F-19 (S2) — The Looker leg's per-report manual step is permanent.**
CI-F: a database-backed source cannot be prefilled by a link, so every
Looker-published report carries a manual re-point + password entry,
forever (D-89). Documented, honest — and it is the reason the target
moved. Any customer choosing Looker must be told at step 0, in writing,
exactly as the Looker ceiling was (CP-0 gate item 5).

**F-20 (S3) — Report identity is a UUID.** `ra-85561dbe-8572-…` and
`cl-livepowerbij` are what the user sees in a workspace listing. RA-D
already parks naming; it is worth one line of thought when it is decided.

---

## Part 5 — dashboard / UI requirements inventory

Input to a Phase-2 spec. **Not a design.** Every item is sourced; the
"API" column asks only whether a governed server-side API already serves
it.

### Inventory

| # | Item | Source | Serves | Serving API today |
|---|---|---|---|---|
| U-1 | **Connections**: list, register, configure, test, health per source | playbook §6; platform-arch §6; D-63.8 (admin CLI is the "stand-in"); F-1 | operator-admin, steward | **Partial** — `POST/GET /v1/jobs`, `GET /v1/health-events`, snapshots; **no** connection CRUD endpoint (the CLI writes direct-DB). Needs building |
| U-2 | **Setup export / bundle delivery** | PA-1; D-88; F-6 | reporter, steward, operator-admin | **No** — `compileProfile` exists in-process; the core serves `/mcp`, `/.well-known/*`, `/v1/*` only, and its MCP surface has tools, not resources. Needs a served, authenticated download |
| U-3 | **Bundle staleness / compile-on-profile-change** | PA-2; D-94.3; F-6 | reporter | **No** — needs a compiled-at vs profile-changed-at comparison the core does not record |
| U-4 | **KB Health**: freshness/trust map, doc-status counts, drift feed, sync-PR queue | platform-arch §6; MCP §6.9; HLR §3 ("R2's home screen") | steward, operator-admin | **Yes, mostly** — `report_freshness()` is specified as the same query the module renders; `GET /v1/runs`, `GET /v1/freshness-warnings` exist |
| U-5 | **Ledger / gap triage queue**, with LED-R5 render neutralization | ledger spec §3.3/§10, FL-B ("dashboard-only"), D-66.5; F-9/F-11 | steward | **Yes** — `list_gaps` + ledger tables. **LED-R5 is a hard requirement on this view**: ledger text is user-supplied and must render markdown/HTML-inert |
| U-6 | **Human gap filing** (class-3 `human_filed` inlet) | ledger spec §5 (three inlets; (b) is "dashboard filing") | steward, reporter | **Partial** — `flag_gap` exists; the `human_filed` kind under the filer's identity is a dashboard-only inlet today |
| U-7 | **Freshness warnings** at OD-3 thresholds, mode-independent (SY-7) | sync spec §8; OD-3; F-12 | operator-admin, steward | **Yes** — `GET /v1/freshness-warnings` |
| U-8 | **Sync-state visibility** — configured-but-disabled sync is silent | **SO-F** (D-84.2); F-12 | operator-admin | **Yes** — `/healthz` already reports `sync_enabled`; nothing consumes it |
| U-9 | **Publish deliveries view** — delivered-but-unattested (the designed dangling state), attestation history per artifact | authoring spec §7; F-15 | reporter, auditor, steward | **Partial** — `model_deliveries` / `report_attestations` tables exist; no read API |
| U-10 | **Run history / job health feed**, dead-letter re-enqueue | job spec §110 (dead-letters "visible in the dashboard health feed… manually re-enqueueable") | operator-admin | **Yes** — `/v1/jobs`, `/v1/runs`, `/v1/health-events`; re-enqueue is `POST /v1/jobs` |
| U-11 | **Webhook secret lifecycle** — per-hook shared secret, rotation | JP-4 / sync spec §4.2; D-64 ("`sync hook set` → 202; rotate → old secret 401") | operator-admin | **Partial** — rotation works via admin CLI; no API/UI |
| U-12 | **Audit view** — queries, publishes, identities; retention/export | MCP §8 ("retention and export are dashboard-Audit-module concerns") | auditor, operator-admin | **No read API** — `audit_records` is written on every call; nothing serves it. This is what `extract-audit.sh` exists to work around |
| U-13 | **Benchmarks module** — three-condition comparison, scores per KB version | playbook §12 exit; plan §6.3; C-5 | steward, operator-admin | **No** — scores are not even in ops Postgres yet (BASELINE-1) |
| U-14 | **Profiles editor + role map** | platform-arch §5/§6; F-5 | steward, operator-admin | **Partial** — profile files are KB YAML; editing means a PR. **See the boundary list** |
| U-15 | **Lineage Explorer** — upstream/downstream per object, edge operations, contamination overlay | platform-arch §6 module registry | steward, reporter | **Yes** — `get_lineage` + `graph.json` |
| U-16 | **Detector-rule configuration** (thresholds as ops config, OD-2) | ledger spec L-3 ("dashboard-editable"), §5; OD-2 partial | operator-admin | **Yes** — `detector_rules` table is ops config by design |
| U-17 | **Estate-wide re-render action** (`regen-all`) | **SO-E** ("manual dashboard action producing a dedicated sync PR; never automatic") | steward | **Partial** — the sync run exists; the trigger mode does not |
| U-18 | **Small-cell threshold configuration** (if SUPPRESS-1 lands in profile limits) | SUPPRESS-1; §1c | operator-admin | **No** — follows U-14's mechanism, whatever it becomes |

### Role → view matrix

Built strictly from the **existing server-side role model**:
`.contextlayer/roles.yaml` maps OIDC groups → doc visibility; profiles
carry `tools.allow` + `limits`; the MCP server evaluates
(roles ∩ profile allowlist) **on every call** (M-3, MCP-R1/R2/R4/R8).
Today's shipped roles: **R1 reporter**, **R2 steward**, **R3 ops**
(bound to the steward profile), **benchmark**. `auditor` is a *view*
role, not a profile — see the flag below.

| View | Reporter (R1) | Steward (R2) | Operator-admin (R3) | Auditor |
|---|---|---|---|---|
| U-1 Connections | — | read | **full** | read |
| U-2 Setup export | **own bundle only** | own | all profiles | — |
| U-3 Staleness signal | own | own | all | — |
| U-4 KB Health | scoped read (own visibility) | **full** | full | read |
| U-5 Ledger triage | own filings | **full** | read | read |
| U-6 File a gap | yes | yes | yes | — |
| U-7 Freshness | scoped | full | full | read |
| U-8 Sync state | — | read | **full** | read |
| U-9 Publish deliveries | **own artifacts** | all | all | **all** |
| U-10 Run history | — | read | **full** | read |
| U-11 Webhook secrets | — | — | **full** (write-only; never display a secret) | metadata only |
| U-12 Audit | **own calls** | own + team | full | **full, read-only** |
| U-13 Benchmarks | — | read | read | read |
| U-14 Profiles | read own | **propose (PR)** | propose (PR) | read |
| U-15 Lineage | scoped read | full | full | read |
| U-16 Detector rules | — | propose | **full** | read |
| U-17 Re-render action | — | **trigger** | trigger | — |
| U-18 Suppression config | — | propose | **full** | read |

**The rule this matrix must not break:** *the UI is a client of the
governed API, never a second enforcement point.* Every cell above must be
a consequence of the server's existing evaluation, not a new check in a
React component. Concretely: the dashboard must call the same endpoints
with the user's own OIDC session, and a cell reading "—" must be a
**403/empty from the server**, not a hidden menu item.

**Items that would tempt a second enforcement point — flagged:**

- **U-12 Audit / "own calls" for reporters.** There is no per-subject
  audit filter today. The temptation is to fetch all rows and filter in
  the client. If reporters get an audit view at all, the filter must be
  server-side and subject-derived from the token.
- **The `auditor` role does not exist.** It appears in
  `dashboard.yaml`'s illustrative `view_roles: [data-team, security]` and
  in the module registry, but no OIDC group, no `roles.yaml` entry, no
  profile. Building an auditor view means **adding a role to the server
  model first** — not granting a view to a group the UI knows about.
  This is the single most likely place to grow a shadow permission
  system.
- **U-2 "own bundle only".** Bundle download must authorize against the
  requester's own profile binding server-side; a URL carrying a profile
  name is a widening surface.
- **U-11 webhook secrets.** Write-only, always. A UI that can display a
  secret has changed the product's secret-handling posture (J-4).
- **U-5 ledger rendering.** LED-R5 neutralization is a *server-side*
  scrub (D-66.5); the UI must not be the only thing making user text
  inert.
- **U-9 / U-13** need read APIs that do not exist. Writing them is the
  work; writing them **without** a `subject`/role filter baked in is the
  trap.

### What should NOT get a UI — the boundary Phase 2 inherits

The PR flow is the product. These stay git-native, and the dashboard's
job is to *route to them*, never to replace them:

1. **Profile and role changes** — they are KB YAML under branch
   protection and code-owner review; the audit story is `git blame`
   (K-IDENT). A UI may compose a PR under the editing user's identity
   (platform-arch §5 says exactly this), but **must not write to `main`**
   and must not maintain its own copy of the allow-set.
2. **Enrichment content** — human docs are certified by a human merging a
   PR with their name in `last_verified` (KB-7). A "certify" button
   detached from a reviewed diff would destroy the one act that makes
   `verified` mean anything. This is the single most important line in
   this section.
3. **Drift review and merge** — SO-B is explicit: *the product never
   merges*. A drift-PR queue view is welcome; a merge button is not.
4. **Reporting-view DDL** — we do not run DDL against a customer estate
   (D-81). The UI may show pending handovers; it may not apply them.
5. **Report authoring** — RA-1: all authoring intelligence lives in the
   customer's Claude Code session. A chart builder in the dashboard would
   re-open the entire "no LLM in the product / visual plane is the
   agent's" boundary.
6. **The KB itself** — §11's ruling stands: one physical source of truth,
   projections and compilations, never forked copies. A dashboard doc
   editor is a forked copy with extra steps.

---

## Proposed Phase-2 shape — a PROPOSAL for the operator's planning session

Not a plan. Two tracks, sequenced so the first customer-facing onboarding
does not wait on the dashboard. Gates are stated in the CP-style the
current plan uses (demonstrable event + mechanically verifiable gate).

### Track A — product-flow hardening (blocks the next onboarding)

| # | Checkpoint | Proves | Gate |
|---|---|---|---|
| **A-0** | **Close the CP-7 tail** | `main` matches what shipped | Runner-config line committed; gate evidence extracted and committed; graph-only sync run carries F-4 nodes into the KB and `get_lineage` walks from the report node (CP-7 exit item 2) |
| **A-1** | **The steward loop is whole** | The drift half of the product has a tool | `review-sync` shipped and AS-7 green; a **live drill on the example estate**: staged breaking change → sync PR → steward runs `review-sync` → repair PR → doc re-verified (playbook gate item 7, human half); a test asserts every profile-named skill exists (R-8) |
| **A-2** | **Setup delivery is a product surface** | A user gets their own bundle | Authenticated bundle download from the core, authorized by the requester's own profile binding; bundle carries no credential; **staleness**: a profile change invalidates or re-compiles, and a session can tell (PA-1 + PA-2 closed) |
| **A-3** | **Connections are operable** | An operator-admin can wire a source without a DBA shell | Connection CRUD + test over the governed API; health per source; an `auth_error` produces a re-auth prompt; the admin CLI becomes a thin client of the same API |
| **A-4** | **Secrets have a supported home** | A security contact can say yes | One vault resolver behind the existing `resolver:` seam, with the pilot's `process-env` path retained as explicitly pilot-only; playbook §4 amended to match reality |
| **A-5** | **The knowledge floor the gate assumes** | Onboarding produces what the gate checks | On a example estate: a `metrics/` catalog seeded from the customer's SQL with owners; every report-path L1 doc human-verified; benchmark wired into KB CI (KB-9). *(Gate items 3, 4, 6.)* This is onboarding work, not engineering — but it is what "report-ready" means |
| **A-6** | **Onboarding measures itself** | OB-4 can ever close | Per-step timers armed and recording from the next onboarding's first step (CP-0 task 0.3, never built) |

**Track A exit = the playbook grades PASS or ASSISTED-with-written-knowledge
at every step, and the §9 gate passes on a example estate.**

### Track B — dashboard (gates nothing; starts in parallel)

| # | Checkpoint | Proves | Gate |
|---|---|---|---|
| **B-0** | **Read APIs before pixels** | The UI can be a pure client | Governed read endpoints for audit (U-12), publish deliveries (U-9), and ledger triage (U-5) — each subject-filtered **server-side**, each with a conformance test proving a reporter cannot read another subject's rows |
| **B-1** | **KB Health + ledger triage** | R2 gets their home screen | Freshness map, doc-status counts, drift-PR queue (routing to GitHub, never merging), triage queue ordered by occurrences/`distinct_subjects`, LED-R5 neutralization asserted by test on the render path |
| **B-2** | **Connections module** | A-3's API gets a face | The playbook's step-3 exit ("dashboard reachable… health green") becomes satisfiable as written |
| **B-3** | **Profiles + setup export** | F-5/F-6 close visibly | Editor that composes a PR under the editing user's identity; one-click export served per A-2; **no write path to `main`** — asserted by test |
| **B-4** | **Audit + Benchmarks** | The auditor role exists | `auditor` added to the **server** role model first (`roles.yaml` + profile), then the view; benchmark trend per `kb_ref` |

**Standing constraint for both tracks:** no quantitative KB-value claim
in any customer or demo material until BASELINE-1 lands (D-62.3, D-80.1).

**Register decisions that should be taken before Track A starts:** SS-5
(§1b), SUPPRESS-1's home (§1c), R-1's public-KB disposition, R-6's wheel
pin. Each is a small decision that changes what Track A builds.

---

## Register-disposition block — for ruling

Every item this review touched. **accept** = affirm as stated ·
**amend** = change the row/wording/trigger · **defer** = leave the
default in force with the trigger re-stated. *No register file was
edited; this block is the motion.*

| Item | Home | Motion | Severity | Next action (concrete) |
|---|---|---|---|---|
| **SS-5** | snapshot spec §10 + master | **amend → close by capture** | High (correctness) | Additive `stats.checks` on `table`, hash-included, verbatim `pg_get_constraintdef` strings, Postgres only; C-1/C-2/C-3 re-run; wheel rebuilt per D-46 |
| **SUPPRESS-1** | master (plan-level) | **defer, trigger tightened** | Med | Amend the row to name the home: enforcement in profile `limits.min_cell_count`, disclosure in the artifact; record the trigger in the next customer's onboarding record |
| **BASELINE-1** | master (plan-level) | **defer, gate restated** | Med | Not run at CP-8; becomes an entry condition of the first customer conversation quoting numbers; book ~2 days; carry the no-claims constraint into Phase 2 |
| **RA-F** | authoring spec §13 | **amend (date the decision)** | Med | Decision due 2027-01-31, or first `push_limit_exceeded`, or second Power BI customer — whichever first; add an 80 %-of-limit warning in the publisher |
| **RA-G** (lifecycle/teardown) | authoring spec §13 | **defer** | Med (latent) | Decide together with RA-D + SO-G, at the first unretired report or first delete request |
| **SO-G** (refresh cadence) | sync spec §13 | **defer** | Med | Pairs with RA-G; `scheduled_refresh: no` stays visible on the connection |
| **SO-F** (silent sync-off) | sync spec §13 | **amend → build in B-1** | High (correctness) | It already cost two days of silent staleness; make `/healthz`'s `sync_enabled` consumed by the health view |
| **SO-E** (regen-all) | sync spec §13 | **defer** | Low | Inventory item U-17 |
| **PA-1** (setup export) | master (PA-\*) | **amend → Track A-2** | High | Served authenticated download; closes F-6 |
| **PA-2** (bundle staleness) | master (PA-\*) | **amend → Track A-2** | High | Compile-on-profile-change or a session-readable staleness signal |
| **OB-1** (compiled read-only KB bundle) | playbook §14 | **accept (defer)** | Low | Still no offline consumer; unchanged |
| **OB-2** (entity draft authorship) | playbook §14 | **accept** | Low | Pilot evidence: skill-drafted + operator-certified worked (D-51, D-94.5); revisit after onboarding #2 as designed |
| **OB-3** (drill fixture) | playbook §14 + master | **amend (bookkeeping)** | Low | Sync spec §12.2 declares it **Closed**; the master register still says Open. Reconcile |
| **JP-4** (webhook ingestion) | job spec + master | **amend (bookkeeping)** | Low | Same: sync spec §12.1 declares it Closed; master still Open |
| **SO-\* section missing from master** | master | **amend (bookkeeping)** | Low | Noted unfixed in D-84.2; SO-A..G have no home in the authoritative status view |
| **OB-4** (duration targets) | playbook §14 | **amend** | Med | The instrumentation was never built (CP-0 task 0.3). Either build it (Track A-6) or record that OB-4 cannot close and say so |
| **OB-5** (profile↔db-role pairing) | playbook §14 | **carry, watch armed** | Med | Load-bearing at the first customer with two execute-granted profiles; today nothing checks the wall matches the gate |
| **OD-3** (freshness thresholds) | HLR + master | **accept** | Low | Mechanism shipped; values per customer at onboarding |
| **OD-2 / MC-4 / SP-1 / FL-C** (pilot-data items) | various | **defer** | Low | CP-8's §8.4 assumed a metrics window that has not run; there is not enough traffic (235 audit rows) to set thresholds. Re-schedule to the first customer's first month |
| **MC-1** (semantic search) | MCP spec | **defer** | Low | Trigger is BASELINE-1's recall table — blocked behind it, correctly |
| **FM-2** (visual registry) | formats spec | **accept, evidence recorded** | Low | CP-7 exercised `line`/`bar`/`table`; `scorecard`/`pivot` unexercised; one recorded substitution (`line`→`bar`, push-dataset axis). Advisory-for-api-targets works as amended. Evidence now in D-95 part C |
| **CI-F** (Looker publish depth) | capability spec | **accept (closed)** | — | Closed by supersession D-91.6/D-92.1; the per-report manual step stands as a documented limit of the secondary target (F-19) |
| **R-1 public customer KB** | D-80.2(a) | **close at trigger** | High before customer 2 | Next customer's KB private from bootstrap; decide the pilot KB's disposition explicitly |
| **R-2 credential rotation** | D-80.2(b) | **accept, one confirmation outstanding** | Med | Confirm the GA4/GSC service-account key recycle (exec DSN done, D-84.1) |
| **R-3 git-history exposure** | this review | **close** | — | Checked clean: `.secrets/` never tracked, `.gitignore:3`; no history rewrite needed |
| **R-5 SP scoping (RA-10)** | authoring spec §10 | **amend** | Low | Preflight asserts membership, not exclusivity; add the advisory check |
| **R-6 PAT workflow-write (F7)** | sync spec §10 / D-46 | **amend → do option (b)** | Med | Move the wheel pin out of `kb-ci.yml` into the existing `VENDOR-MANIFEST.yaml`; drop workflow-write from the sync PAT; do not rely on wildcard CODEOWNERS on a customer repo |
| **R-8 fixture↔product profile drift** | D-79 watch-note | **amend → test it** | Med | A test asserting every profile-named skill ships; it would have caught `review-sync` |
| **JC-4 flake** | job spec JC-4 / D-86.2 | **accept the fix (test-only)** | Low | The diff in §1e; verification = three consecutive full runs under deliberate load. Not a product defect: production lease is 60 s, only `e2e.test.ts` compresses it to 2 s |
| **Docker-heavy sync flake** | D-92.3 | **quarantine-with-trigger** | Low | Keep the two-green standard; **next occurrence must be captured with full output** into `results/` before re-running |
| **`review-sync` unbuilt** | skill spec §7 (new finding) | **amend — needs a ruling** | **High** | Not currently a register item. Either build it (Track A-1) or amend the skill spec to three skills and remove it from both profiles. It is named in shipped profiles today |
| **CP-7 gate item 2 pending** | plan §7 (new finding) | **accept as recorded** | Med | One graph-only sync run + one additive KB PR |
| **Uncommitted runner-config** | D-74.2 / D-82 (new finding) | **accept — land it** | **High** | `git add deploy/runner-config.yaml` and commit; CP-7 is closed over unlanded work until then |

---

### Method note

Everything above is sourced from committed files, the KB's `origin/main`,
and **read-only** queries against the live ops database on machine 1
(`audit_records`, `jobs`, `ledger_*`, `model_deliveries`,
`report_attestations`, `report_artifacts`, `lineage_attestations`,
`runs`). No state was changed, no demo re-run, no test executed, no live
estate operation performed. Two checks were deliberately **not** run and
are left as operator-runnable: `results/cp7-gate/extract-audit.sh
'2026-07-29T11:00:00Z'` (writes the gate evidence files), and a full
suite run under deliberate load to reproduce the JC-4 flake.
