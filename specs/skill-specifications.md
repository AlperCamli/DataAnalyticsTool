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

**S7 publish (optional).** Only on user request and profile permission. Behavior follows the effective `create_report` flag: `full` → publish, return URL; `template_link` → execute the backing path first (see below), then hand the link and relay `pending_human_steps` verbatim (PB-3); `api` → the S8 authoring flow (two-call publish contract; amendment below); `none` → deliver validated SQL + instructions. **Backing path (SK-6):** when `sql_backing: views` and the report is recurring, produce the reporting-view DDL; if the session can open a PR on the migrations repo, do so and link it; otherwise attach the DDL as a handoff artifact in a `flag_gap(kind: capability_gap)` entry explicitly routed to R2, and tell the user their data team received it. **CP-R5 [A]:** never publish results the user has not confirmed in CP-R4.

**S8 authoring flow (api targets — amendment, report-authoring spec §12.4 / D-91, 2026-07-29).** Entered from S7 when the target's effective `create_report` is `api`. Implements report-authoring spec §4 stages 4–10; CP-R4 confirmation and CP-R5 still gate entry (RA-9: the target changed, the honesty rules did not).

1. **Design (CP-R6 [A]).** Decide pages, visual kinds, encodings, and titles per report-authoring §6.1: the five-kind registry is design guidance; a target-native kind outside it carries a one-line justification in `layout…notes`. Documented data caveats bind design — a series without a calendar spine must not render as an interpolating line; clipped window edges are annotated; small-cell sensitivity is noted in the trust element. Titles and labels come from human-doc semantics where docs exist. Write the design into the artifact's `layout` section (formats §4.7) **before** any publish call — the design record precedes the delivery it describes (RA-3), and the RA-4 `trust_element` is part of it.
2. **Deliver (CP-R7 [E]).** `publish_report(mode: "deliver_model")` — call #1. Server gates are enforced (MCP §6.8); the result returns the delivered table schemas.
3. **Author.** Generate the deployed definition (PBIR) with the skill-local tooling (RA-5) strictly against the **returned** `delivered.tables[].columns` names and types — never against guessed field names; a schema mismatch regenerates from the returned schema, and a persistent mismatch is a K-FAIL flag, not a guess (report-authoring §8). The RA-4 trust element renders in every authored definition.
4. **Deploy.** Skill-local Fabric deployment: create the report on revision 1, update the same `report_id` in place thereafter (RA-8).
5. **Verify (CP-R8 [A]).** RA-7 read-back: deployed hash equals authored hash AND every field reference resolves against the delivered schema. On mismatch: redeploy once, then fail loudly. **Never attest unverified work.**
6. **Attest (CP-R9 [E-adjacent]).** `publish_report(mode: "attest", attestation: {report_id, definition_hash})` — call #2. The server refuses an attest without its matching delivery (report-authoring AT-5), so a skipped delivery or a stale revision cannot be attested; the skill's own duty is to attest **only after** step 5 passed.
7. **Hand off.** Relay the returned workspace report URL. `pending_human_steps` is empty or `["open the report"]` — anything more is a defect to surface, not a step to relay as normal (D-91.1).

Failure exits ride the report-authoring §8 table; SK-7's bounded-repair rule applies per stage (at most 2 repair attempts, then flag and stop).

**Amendment (D-114.3c, 2026-08-06) — volunteered knowledge is filed, not absorbed.** §5 above describes a pipeline and its failure exits, and had no clause for the commonest way a session produces knowledge: **the session goes fine and the user tells you something the KB should have said.** *"That's right, but the KB should really say that a refund is counted in the month the credit note is issued."* Nothing in S1–S8 or K-FAIL covers that, because it is not a failure — and a skill with no instruction either filed it under a kind that carries no proposal or, more often, let it pass in conversation.

**The clause, and it binds every session, not only a report one:** when a user volunteers content the knowledge base should carry, the skill **files it** —

```
flag_gap(kind: "enrichment_request",
         description: <the gap, in the skill's words — what a steward reads in a queue>,
         object:      <the FQN it is about, when they named one>,
         proposal:    <what they said it should say, in THEIR words, verbatim>)
```

Four bounds, each of which is the clause failing if dropped:

1. **`proposal` is the user's words verbatim, `description` is the skill's summary of the gap.** The proposal is *drafting evidence* and is cited to them by name and date when a doc is later grounded on it (§6 S1b). A tidied, summarized or paraphrased proposal is the agent's prose wearing the user's authority — which is exactly what the citation rule exists to prevent.
2. **A dead end where the user also supplies the answer is two filings, not one:** the gap that blocked the session *and* the knowledge they volunteered. They route the same way and are answered differently, and a proposal attached to a K-FAIL kind never reaches the verdict queue (ledger §4). This is also the line against `result_disputed`: that kind is CP-R4's *the answer was wrong*; this clause is *the KB is missing something*, and a session can produce both.
3. **Say "I've filed it", never "I've added it" or "the KB now says".** Nothing enters the knowledge base until a human merges a reviewed diff (KB-7); the request is *worth drafting* at best until a steward's verdict says so. Relay `routed_to`, and relay `occurrences` when it exceeds 1 — *"you're the third person to ask for this"* is the argument that gets it approved (ledger §4's demand signal). **Relay `value_flags` when the response carries them** (D-115): they name what the stored text was found to contain, the submission was kept verbatim, and the session is the only thing that can tell a filer who has no browser open. It is a notice, never a rejection — do not offer to re-file without the values and do not edit the user's words.
4. **Do not ask permission to file.** Filing costs the user nothing and the queue deduplicates; a request that dies because the skill asked *"shall I note that?"* and got *"don't worry about it"* is knowledge the estate lost to politeness.

**Why this is in the spec at all.** The inlet (`flag_gap`'s `enrichment_request` kind with its proposal, MCP §6.10), the queue, the verdicts, the batch and the merge loop were all built and conformance-tested, and **no skill knew the move** — so in practice it was a queue only browser users could file into, which is the thing ledger §4 legislated against by name. A capability with no caller passes every test written against the capability (finding B1-F2). This clause is the caller.

*Evidence status, stated rather than implied:* the shipped conformance test for this clause greps the skill file for the instruction, which catches its **absence** and is not evidence of agent behaviour (D-78). The behavioural scenario that would be — a real session in which a user volunteers knowledge and the transcript shows the filing under their identity, with their words unedited in the proposal — belongs beside AS-18 in §9 and **is not built**. It must not be reported as covered by the grep.

## 6. `enrich` skill

Serves J1 levels 1–3 and J2 trigger 3. Profile context: Steward.

```
scope → evidence → drafting → self-check → PR
```

**S1 scope.** Select a bounded batch (default ≤ 10 objects) from, in priority order: fault-ledger triage items assigned to enrichment, hot objects lacking human docs (index hot/stub status), harvested documents awaiting conversion. **CP-E1 [A]:** state the batch and its rationale before writing anything.

**S1b queue-driven batch mode (amendment, D-101.4, 2026-08-05).** A second entry into the same state machine: instead of the skill selecting a batch from S1's priority order, the steward's approved worklist delivers one. Input: the `enrichment_request` issues stamped with a `batch_id` by the dashboard's "deliver batch" trigger (ledger spec §4 amendment / §8) — at most ten, SP-3's default unchanged. S2–S5 run exactly as specified below; what the mode adds is one grounding rule and one honesty rule, both per item.

- **The approved request is itself a citation**, of the customer-provided class: `sources: customer-provided, <name>, <date>` — the requester and the submission date as the ledger recorded them (LED-R3 server-set), never re-typed from the body of the request. On the S2 maturity ladder it sits beside `customer doc: <uri>`: **stated** by someone who knows the business, not **observed** by us, and never upgraded to observation because it arrived as confident prose (HLR §8 P4 — the ladder exists precisely because confidence is not evidence).
- **The submission is drafting input, not content.** Requester text is never embedded verbatim: the doc is written in the KB's own voice through the canonical templates (KB §7) and *cites* the request. Dashboard test DT-12 asserts the same rule from the other side — the raw submission appears nowhere in the batch PR's diff.
- **CP-E5 [A] — per-item honesty, unchanged in substance.** An approved request the skill cannot ground beyond the proposal is drafted **citing exactly that provenance and nothing better**: `customer-provided` alone, with no inferred-from-column-names dressing to make it look sturdier. One the skill cannot draft at all **returns to the queue** with a note stating what evidence would unblock it (ledger: back to `approved`, note recorded) and is dropped from the batch's trailers — never guessed at, never turned into prose no one can source. S5's failure-exit rule holds here verbatim: an honest skip beats a fabricated draft.
- **CP-E3 is untouched.** The skill still never sets `verified`. Approval means *worth drafting*, not certified (dashboard spec UI-11); the certification act is the steward merging the reviewed diff under their own name (KB-7).

**Amendment (D-116.5, 2026-08-07) — S1b reads its batch through `list_gaps`, and nothing else (finding B1-F8).** As shipped, S1b told the session to fetch the batch from the dashboard's ledger API with `authorization: Bearer $CL_TOKEN`. That token does not exist in the sessions this mode is for: a compiled bundle carries no credential (PA-1) and the MCP client's OAuth token is not reachable from the session's shell, so the mode's *first step* was unperformable — the whole of it, for anybody following the page as written. The input is now the tool the session already holds:

```
list_gaps(status: "batched", kind: "enrichment_request")
```

which returns, per issue, the filing behind it — `filing.{by, at, description, proposal, value_flags}` (MCP §6.11.1). That is exactly the citation's raw material: **`by` and `at` are what the ledger recorded**, so "never re-typed from the body of the request" is now structural rather than a rule to remember. No second channel, no token, no `curl`. A session whose profile does not grant `list_gaps` cannot run this mode and says so — which is the honest failure, not a fallback.

**Not fixed by that amendment, and named so at the time (finding B1-F9):** the third per-item outcome — *return it to the queue* — is a governed **write**, and it had no session-reachable inlet (no MCP tool, no dashboard control). A request the skill could not draft was named in the PR body's returned section **and handed back to the steward in words**, with CP-E5's ledger half (`batched → approved`, note recorded) performed by whoever held an API credential. The skill was forbidden from pretending it returned something it could not.

**Amendment (D-118.3, 2026-08-07) — B1-F9 closed: the third outcome is an act again.** `return_request(issue_id, note)` (MCP spec §6.12) is the inlet — steward-gated, symmetric with `list_gaps`, the same write the dashboard already performed. CP-E5's ledger half returns to the skill: an item it cannot draft is **returned**, with the note, and the skill may then say *returned to the queue* because it moved the row. Three rules survive the fix intact, and they are the load-bearing part:

1. **The words still go in the PR body**, in the *Returned to the queue* section — the ledger note is for the next steward, the PR section is for the reviewer reading this diff, and neither substitutes for the other.
2. **The item still appears in no `CL-Resolves` trailer.** That absence is what keeps the request open, and a returned request is by definition unanswered.
3. **The say/do rule is unchanged, only its verdict flips.** Where the tool is *not* in the session's profile — a deployment that has not granted it — the skill is back to handing it back in words, and must say *handed back*, not *returned*. Claiming a state change you did not make is the same class of error as claiming a doc entered the KB when you only opened a PR. The rule was never about this tool; it is about matching the claim to the act.

The note is scrubbed at storage as every reader-facing ledger reason is (LED-R2), and the tool reports when the stored text differs from what was sent; where it lost something that mattered, say so in the PR body, where nothing is scrubbed.

**Amendment (D-117, 2026-08-07, owner ruling) — a request-driven item is grounded in the request and the estate, and nowhere else.** S2's evidence list is written for *skill-selected* batches, where hunting down a migration or an app constant is the whole point. **In queue-driven batch mode it does not apply.** An approved request is answered from:

1. **the request itself** — the words the person wrote, cited `customer-provided` / `customer-confirmed, <name>, <date>`;
2. **the estate's own facts** — the snapshot (`get_table`), the machine sibling, and existing KB docs, which is reading the knowledge base rather than sourcing from outside it.

**Nothing else.** No application source, no repositories, no files elsewhere on the machine, and **no fishing for corroboration or contradiction**. Where the request is not specific enough to draft from, the skill **asks** — of the human in the session if there is one, and otherwise by handing the item back with the question as its note. A question is a legitimate outcome of a batch; a doc grounded in something the estate cannot see is not.

**And a blocked target is deferred, never redirected.** If the doc that should carry the requested knowledge cannot be written — `status: contaminated` with a `refuse-unless-override` guidance is the case that produced this ruling — the skill does **not** put the content on some other doc that happens to be writable. It hands the item back saying which doc it is waiting for; the knowledge is added when that doc is repaired to `draft` or `verified`. The request stays open, which is the honest state: nobody has answered it yet.

*Cost of this rule, stated once (D-116.1) and not re-litigated:* request-driven docs land at the **weakest tier of the P4 ladder by construction**, even when better evidence exists a directory away — and a second source is also what catches a request that is *wrong*. The run that produced this ruling is the demonstration in both directions: reading the application's own pricing constants found a **nine-cent disagreement** with the confirmed figure that request-only drafting would have written down silently. The ruling's reasons stand against that: a KB claim sourced from a private codebase is invisible to every drift check this product has, and a demonstration that reaches outside the estate is not a demonstration of the estate. Discrepancies found outside the estate still belong in the **ledger** as filed gaps — that path is untouched.

**Amendment (D-116.7, 2026-08-07) — the skill provisions its own KB working copy (finding B1-F5).** S3–S5 assume a KB clone ("both commands from the KB clone root") and nothing ever put one there: a steward following the runbook into a fresh session had no working copy, no stated path, and no instruction to make one — so the drafting steps had nowhere to write and the self-check had nothing to validate. The skill now provisions it: **`~/cl-steward/kb`**, cloned from the `kb_remote` the compiled bundle names and `git pull --ff-only` on every later run. The path is fixed and outside the OS-protected user trees (`~/Desktop`, `~/Documents`), because a working copy a session cannot reach without a consent dialog is the same defect wearing a permissions costume. Git authentication is the operator's own credential helper; **the bundle still carries no credential** (PA-1). A dirty or diverged working copy **stops the skill** and is reported — resetting somebody's uncommitted work to make a batch run is not a repair.

**S1c contamination-triage work-list mode (amendment, D-119.2b, 2026-08-07; additive).** A third entry into the same state machine, and the product home the contaminated set has been waiting for. Where S1 selects a batch and S1b receives one from the steward's approved worklist, **S1c takes its batch from the KB's own contamination state**: docs whose front-matter reads `status: contaminated`, ordered by severity, re-grounded against the current snapshot, prepared as re-verification diffs. S2–S5 run as specified; what the mode adds is an input, an ordering, a three-way classification, and one rule about what a repair may touch.

**Input — the KB itself, read deterministically.** The skill's working copy (S0) is the source: `worklist.py --kb <clone>` (shipped in the skill bundle, stdlib-only, zero model calls) walks the tree and returns, per contaminated doc, the `contamination: {object, change, detail, path}` marker sync wrote, the contaminating object's *current* facts (schema hash, columns, and the `stats.checks` constraints where the snapshot carries them), the doc's `depends_on` resolution against that snapshot, whether it was ever `verified`, whether a golden expects it (KB §3.1), and which of the changed columns the doc's text actually speaks about. No new MCP tool: contamination status is front-matter, and the skill already holds the clone. The tool assembles evidence; **it classifies nothing** — that is judgment about prose against facts, and a regex must not make it.

**Ordering.** Unresolved dependencies first, then docs that were once `verified` (a certified claim now under doubt outranks a draft), then report-path docs, then the size of the group sharing one cause, then path. Batches are ≤10 (SP-3) and **keep docs sharing a contaminating cause together** — a batch is a pull request somebody reads end to end, so it should tell one story.

**Per doc, exactly one of three classifications, stated in the PR body:**

1. **`confirms-prose`** — the change is a fact the doc already states correctly, or says nothing about. The repair is the marker and the stamp: clear `contamination`, refresh `written_against_schema_hash`, leave the prose alone. **The diff is front-matter-only, and that is a checkable property** — if the body moved, the doc was not in this class.
2. **`needs-re-grounding`** — the change contradicts, narrows or extends what the doc says. The affected claims are rewritten *from the current snapshot*, the new evidence is cited at the tier it deserves (a DB `CHECK` is `app DDL`-grade ground truth, and outranks the customer-stated value set it may replace), and the disagreement itself is worth a sentence.
3. **`depends-on-missing-object`** — a `depends_on` FQN no longer resolves. No re-grounding repairs this: the doc is left contaminated, named in the PR body with the decision it needs (drop the dependency, or wait for the object), and — where a ledger issue is the right home for that decision — `flag_gap`. An honest untouched doc beats a repair that quietly deletes a dependency nobody agreed to drop.

**CP-E6 [A] — a repair re-grounds; it does not re-certify.** The skill clears `contamination`, refreshes the hash, and sets `status: draft`; it never writes `verified` and never sets `last_verified` (CP-E3, unchanged, and KB §5's transition table: `contaminated → verified` is human-only). **The certification act is the steward's**, performed on the branch under their own name before merging — solo-operator mode makes that merge the named act (D-116.3), and it is the same act at n=34 as at n=1. The PR body says so per doc, in the imperative, so the steward is not left guessing which docs they are being asked to put their name on.

**S2 evidence.** Per object: machine doc (facts), harvest results whose `mentions`/content cover it, usage evidence where present (join_pairs → evidence-grade join guidance), existing entity docs. Maturity-ladder discipline (HLR §8 P4): the evidence tier available dictates the `sources` grading — `customer doc: <uri>`, `observed in N queries`, or `inferred from column names`; never upgrade inference to observation.

**S3 drafting.** Canonical templates (KB §7), one human doc per object (or group doc edits for API kinds). **CP-E2 [A]:** every draft carries complete front-matter with `status: draft`, graded `sources`, and a `depends_on` list covering every FQN the body relies on (the K-2 declaration duty).

**CP-E4 [A] — purposes go in front-matter, not prose** *(added at CP-5, with the matching KB §7 amendment)*. Every drafted human doc carries `purpose`, and `column_purposes` covering the columns the evidence supports (`object_purposes` for group docs). These are the fields the generator merges into the machine sibling (KB §4.2, D-49), so a purpose written only into the body reaches no render and is invisible to every agent reading the machine doc. The body carries only what a one-line value cannot: enum decodings, JSON/JSONB structures, multi-condition join caveats, warning rationale. **The skill does not write a body section that restates a front-matter one-liner** — duplicated claims drift, and a drifted purpose is worse than an absent one because both copies look authoritative. A draft whose meaning is fully carried by its front-matter ships with an empty body; that is a complete doc, not a stub.

Purpose values obey the same grounding rules as everything else (K-GROUND, the S2 maturity ladder): a `column_purposes` entry is a claim about the estate and needs the evidence tier its `sources` grading declares. Guessing a one-liner because the slot would otherwise render `—` is the exact failure the gap-vs-guess rule forbids; an unpopulated slot is honest, and KB-10 warns on keys that do not resolve. **CP-E3 [E-adjacent]:** the skill never sets `verified` and never touches `*.schema.md` — violations are caught by KB CI checks KB-3/KB-7 at PR time, so the gate is enforced at merge even if the skill misbehaves.

**S4 self-check.** Run the KB CI validation locally (front-matter schemas, FQN resolution, links) before opening the PR; fix or drop failing drafts.

**S5 PR.** One PR per batch, under the session user's identity (K-IDENT), body summarizing per-doc evidence grades; ledger-originated items carry `CL-Resolves: <issue-id>` trailers so merge closes the loop (ledger spec §9). For a queue-driven batch (S1b) the body additionally lists the **request → doc mapping** — each request in the batch against the doc that answers it, and each returned-to-queue item against the reason it came back — and carries one `CL-Resolves` trailer per request the batch *actually satisfies*, so the merge resolves exactly those and no others. *Failure exits:* insufficient evidence for a scoped object → skip it and record `flag_gap(missing_doc)` noting what evidence would unblock it — an honest skip beats a fabricated draft.

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

**Additions at CP-5 (additive only; AS-1..AS-8 unchanged).** The scenarios above were written before the three skills were packaged; these cover what packaging made testable. AS-9..AS-11 are the CP-5 deliverable-7 tests.

| # | Scenario | Verifies |
|---|---|---|
| AS-9 | enrich: a scoped object whose definition the evidence cannot settle → the item appears in the PR body's gap list and in `flag_gap`, and **no prose about it appears in any drafted doc** | K-GROUND, gap-vs-guess, S5 failure exit |
| AS-10 | report: an entity doc in the resolution path carries a contamination marking → the warning is surfaced **in the report artifact itself**, not only in the session transcript | K-TRUST reaching the artifact |
| AS-11 | benchmark: a skill-emitted journey record is ingested by the CP-2 harness **byte-compatibly** with the CP-2 fixture records — same file-ingestion path, no harness change | §8 hand-off contract, R8 keying |
| AS-12 | enrich: drafts carry `purpose` and `column_purposes` in front-matter; no body section restates a front-matter one-liner; a fully-one-lined object ships an empty body | CP-E4 |
| AS-13 | report: a cross-source request follows the entity doc's stated resolution rule verbatim (blend vs fetch-and-combine); the artifact's `blend.keys[].entity_ref` resolves to the entity doc that decided it | S3, formats spec |
| AS-14 | benchmark: the journey prompt is byte-identical across all three conditions; only the served KB and the profile allowlist differ | R2 fairness |
| AS-15 | profile compilation: a compiled profile yields a Claude Code setup whose MCP config, skills bundle, and CLAUDE.md fragment match the profile's `tools.allow`, `skills`, and `context` — and **widening the compiled client config does not widen access** when replayed against the server | platform-architecture §5, M-3 |

AS-15's second clause is the one that matters: compiled configs are conveniences, and the scenario must demonstrate the enforcement boundary rather than assume it — a hand-edited config granting a tool the profile withholds still gets denied server-side.

**Additions with S8 (amendment, report-authoring spec §12.4 / D-91, 2026-07-29; additive only).**

| # | Scenario | Verifies |
|---|---|---|
| AS-16 | report/S8: fixture end-to-end — audit shows `publish_report` `deliver_model` then `attest` for the same artifact and revision, in that order, with the attested `definition_hash` matching the artifact's `layout.pbir_hash`; the terminal `pending_human_steps` is empty or `["open the report"]` | S8, report-authoring AT-9, D-91.1 |
| AS-17 | report/S8: authored definition references a field absent from the delivered schema → verify fails and **no attest call appears in audit** | CP-R8, report-authoring AT-4 |

**Additions with the knowledge-request queue (amendment, D-101.4, 2026-08-05; additive only).**

| # | Scenario | Verifies |
|---|---|---|
| AS-18 | enrich/S1b: fixture end-to-end — two approved `enrichment_request`s are delivered as one batch, one groundable no further than its proposal and one the skill cannot draft at all. Asserted: the batch is read through `list_gaps(status: "batched")` and no other channel (D-116.5); the drafted doc's `sources` reads `customer-provided, <name>, <date>` **taken from `filing.by`/`filing.at`** and **no requester text appears verbatim anywhere in the diff**; the PR body carries the request→doc mapping; exactly one `CL-Resolves` trailer, for the satisfied request; the undraftable one is named with its unblocking condition and appears in no trailer; merging the PR fires the ledger resolution and the filer's reply path; **no `verified` status is written by the skill** | S1b/CP-E5, CP-E3, D-101.1/.4, D-116.5, ledger L-5, UI-11 |

*Amended 2026-08-07 (D-116.5).* Two clauses changed shape, and the reason is a defect rather than a preference. The batch channel is now the MCP tool, so the scenario proves the mode is performable in a real session — the previous version handed the agent a bearer token the product does not give anyone (B1-F8) and therefore could not have caught the defect it was written to cover. And the returned item's **ledger state** (`batched → approved` with its note) is no longer asserted *of the skill*: that write has no session-reachable inlet (B1-F9), so the harness performs it and the skill is measured on what it can actually do — naming the item, its unblocking condition, and its absence from the trailers.

*Amended again 2026-08-07 (D-118.3) — the clause comes back, as the previous paragraph promised it would.* B1-F9 is closed by `return_request` (MCP §6.12), so the returned item's ledger state is asserted **of the skill** once more: after the run, the undraftable request is `approved` with `batch_id` cleared and its note recorded, and the harness performs no write on the skill's behalf. The scenario's profile must grant the tool; a run where it does not is measuring the words-only fallback, and the scenario says which it measured rather than scoring both alike.

Per D-78's layering, AS-18's conformance evidence is the **behavioral** run against the fixture deployment. A validator over staged PR bodies pins the citation and trailer rules cheaply and belongs in CI — but it cannot fail when the skill misbehaves, so it is a regression test and never the evidence.

**Addition with the contamination-triage mode (amendment, D-119.2b, 2026-08-07; additive only).**

| # | Scenario | Verifies |
|---|---|---|
| AS-19 | enrich/S1c: fixture end-to-end — a contaminated batch containing all three classes: one doc the new `CHECK` **confirms**, one it **contradicts**, and one whose `depends_on` names an object the snapshot no longer has. Asserted: each doc is classified in the PR body; the confirming doc's diff is **front-matter-only** (marker cleared, hash refreshed, prose byte-unchanged); the contradicted doc's prose is re-grounded against the constraint and cites it at DDL grade; the missing-object doc is **left contaminated** and named with the decision it needs; **no `status: verified` and no `last_verified` written anywhere** by the skill; and the PR body states the certification act as the steward's, per doc | S1c/CP-E6, CP-E3, KB §5 transition authority, D-116.3 |

The same layering applies, and for the same reason: the validators over staged diffs (front-matter-only property, classification coverage, no-certification) are CI regression tests, and **AS-19's evidence is the behavioral run**. A validator cannot fail because a skill re-grounded a doc against a constraint it never read.

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
| SP-6 | Per-profile skill version pinning | Out of v1: core version **is** skill version, one axis. Skills ship in the product at `core/skills/<name>/SKILL.md` and upgrade on the release path (D-75.1) | First customer needing to hold back a skill upgrade while taking a core release |

SP-6 is parked, not solved. It exists because §5's variance rule and the release-path packaging together mean a customer cannot take a core release without taking every skill change in it. That is the right default at one pilot — one axis, nothing to reconcile — and the wrong one the first time a customer has certified a workflow against a skill's current behavior. The trigger is that customer, not a schedule.
