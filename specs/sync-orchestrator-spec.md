# Contract Specification — Sync Orchestrator (v1)

Status: v1 draft for implementation. Fills the spec set's one deliberate gap (`spec-index.md` "Known gap"; JP-4): the process that ties trigger ingestion → snapshot acquisition → diff → severity → lineage re-derivation → contamination scan → regeneration → drift PR into one specified pipeline. Every edge it touches is already contracted: triggers enqueue jobs per the job protocol; diffs follow snapshot §7; the scan algorithm is KB §6 and its walk formats §3.4; PR conventions are KB §9; renders follow generator semantics plus the D-38 enrichment-merge invariant. This spec owns the *orchestration* — sequencing, atomicity, concurrency, failure semantics — and the operational surfaces around it (webhook endpoint, freshness monitoring, the drill fixture, vendored-wheel maintenance).

Closes **JP-4** (webhook ingestion, adopted as specified in §4.2). Converts **OB-3** into a build deliverable (§9). Ships the mechanism for **OD-3** (§8); the threshold value remains per-customer configuration.

---

## 1. Scope

**In scope:** the trigger model (scheduled, webhook, manual) and its ingestion endpoint; the drift-run pipeline as a state machine with normative stage ordering; run records, concurrency, and coalescing; failure semantics per stage; freshness monitoring; the staged drift drill fixture; the vendored-wheel update path; conformance tests.

**Out of scope (owned elsewhere, consumed here):** diff classifications and severity (snapshot §7), the contamination-scan algorithm (KB §6) and walk semantics (formats §3.4), generator template behavior and pruning, PR content conventions (KB §9), job transport mechanics (job protocol), and dashboard rendering of the health/freshness surfaces this spec feeds.

## 2. Design rulings

| # | Ruling | Rationale |
|---|---|---|
| SY-1 | A drift run is **atomic**: it either completes through PR authoring (or a recorded no-op) or fails loudly to health; it never leaves partial artifacts (no graph without a scan, no status flags without their PR, no PR without its renders). Re-running a failed run against the same inputs produces identical output | The pipeline is deterministic end to end; atomicity plus determinism makes failure recovery "just run it again" and makes every merged sync PR a complete, self-consistent statement |
| SY-2 | The webhook is a **trigger, not a data channel**: system identity comes from the URL path, authentication is a per-hook shared secret, and the request body is never parsed | Closes JP-4. Parsing CI payloads couples us to every CI vendor's format; the snapshot is the data channel and it is absolute, so the only information a hook can usefully carry is "re-snapshot now" |
| SY-3 | **Uniform supersede**: every sync PR states the complete currently-true drift and contamination picture versus merged KB HEAD; opening it auto-closes the orchestrator's own prior unmerged sync PRs (KB §9), including breaking ones | Snapshots are absolute states, so nothing is lost by restatement; the reviewer always faces exactly one PR that is exactly current, never an ordering puzzle across stale PRs |
| SY-4 | **No PR without a complete contamination scan.** If lineage re-derivation is required and fails (parse failure ⇒ no graph, per the 1.9 ruling), the run fails; the diff is never shipped scan-less | An unscanned breaking change merged out of habit is the exact silent-gap failure mode (D-2 polarity) the scan exists to prevent; a loud failed run is strictly safer than a quietly incomplete PR |
| SY-5 | Render inputs are pinned at run start: (latest accepted snapshot per system, KB merged HEAD) — and machine renders are computed against **HEAD enrichment front-matter** per the D-38.3 invariant | Makes the sync PR's renders byte-reproducible (KB-8 in run context) and states explicitly that the orchestrator inherits purpose-merge for free: HEAD machine files already reflect HEAD enrichment (enrich PRs carry their re-renders), so a drift run re-renders only diff-changed objects and their indexes |
| SY-6 | Runs are **single-flight** per deployment; triggers arriving mid-run coalesce into exactly one follow-up run covering every system with a pending trigger. Failure locality: a system whose snapshot *acquisition* fails is excluded from the run with a health event; any failure *after* acquisition (diff, lineage, scan, render, PR) fails the whole run | Acquisition failures are environmental (source down, credentials) and must not block healthy systems; post-acquisition failures are product-integrity failures and must never be papered over by shipping the systems that happened to work |
| SY-7 | Freshness is **snapshot age versus the per-system policy threshold, evaluated continuously and mode-independently** — a stale scheduled source warns exactly like a stale manual one | OD-3's warning was designed for manual mode, but a silently dead schedule produces the same staleness; one rule catches both, and the dashboard warning names the configured trigger so the fix is obvious |
| SY-8 | The staged drift drill is a **shipped product fixture** (test schema + scripted breaking change + expected contamination set + expected PR shape), runnable per deployment | Closes OB-3's question: playbook gate item 7 becomes the execution of an artifact, not per-customer improvisation — and the same fixture is this spec's own conformance evidence (SO-4) |

## 3. Actors and inputs

The orchestrator is a core component (platform-architecture §3). It consumes: `sync-policy.yaml` from KB HEAD (per-system trigger modes, intervals, freshness thresholds), the job API (as a producer of `snapshot` jobs — it never speaks the runner protocol), accepted snapshots in ops Postgres (validated per J-6; baseline = previous accepted snapshot per system, retained per JP-3), KB HEAD via the git provider (front-matter `depends_on` declarations, enrichment front-matter, current `lineage/graph.json`), and the generator + core SQL lineage parser as libraries. It produces: run records in ops Postgres, health events, drift PRs under the `contextlayer-sync` identity, and freshness warnings.

## 4. Trigger model

Three trigger kinds, all reduced to the same effect — enqueue a `snapshot` job for a system (job §4.1 `trigger.kind` records provenance) and mark the system trigger-pending for the next run:

### 4.1 Scheduled

Per-system intervals from `sync-policy.yaml` (current customer: `ga4: 3d`, `gsc: 3d`, `supabase: 30d`). The scheduler evaluates on a coarse tick (default hourly): any system whose last *accepted* snapshot is older than its interval is due. Editing the policy in the KB takes effect on the next tick after merge — no redeploy (mirrors ledger L-3's config-not-code stance).

### 4.2 Webhook (JP-4 adopted)

`POST /v1/hooks/{system}` on the core. Authentication: per-hook shared secret, generated at hook creation in the Connections module, presented in the `X-CL-Hook-Secret` header, compared constant-time. Responses: `202` (trigger accepted), `401` (bad/missing secret — nothing enqueued), `404` (unknown system — nothing enqueued, and per the M-4 spirit the body does not distinguish "unknown" from "not configured"). The request body is ignored unread (SY-2); a `Content-Length` cap (default 64 KB) guards the socket. Job-protocol dedupe (§8: one running + at most one queued per `(system, snapshot)`) absorbs CI storms without an orchestrator-side debounce (register SO-A).

### 4.3 Manual

Dashboard "sync now" per system or estate-wide; DDL re-submission in case-A sources lands here too (a new DDL handover is a manual trigger with the files as the connector's config input). Recorded `trigger.kind: manual` with the acting identity.

## 5. The drift-run pipeline (normative stage order)

A run begins when ≥1 system is trigger-pending and no run is in flight (SY-6). Stages:

1. **Pin.** Record run inputs: the set of pending systems and their coalesced triggers, `kb_ref` = merged HEAD commit, and per system the baseline (previous accepted snapshot ref). Branch name `sync/<run-id>` (run-id is a ULID).
2. **Acquire.** Await one accepted snapshot per pending system (the trigger already enqueued the jobs; acceptance = J-6 validation passed). Acquisition failure (job dead-lettered or timed out per run budget, default 2 h) excludes that system from the run with a health event (SY-6); if no system remains, the run records as `failed_acquisition` and stops.
3. **Diff.** Per system: new accepted snapshot vs baseline, classified per snapshot §7. All systems unchanged → run records `no-op`, no branch pushed, done.
4. **Provisional severity.** Apply the §7 sub-diff severity table, holding view/matview `definition` changes at *provisional breaking*.
5. **Lineage re-derivation.** Required iff any object with a hash-included `definition` changed, or any object participating in the current graph was added/removed. Re-parse per the 1.9 rules (sqlglot, parse failure = hard failure, no partial graph); merge per formats §3 (edge identity F-1, evidence merge F-2), regenerate `lineage/graph.json` deterministically. Failure here fails the run (SY-4); HEAD's existing `graph.json` is left untouched.
6. **Severity finalization.** Apply snapshot §7 note ³: a `definition` change whose re-derived output column set and mappings are unchanged downgrades to additive-with-note. Only now is the breaking set final.
7. **Contamination scan.** Exactly KB §6 steps 1–5 over the finalized classifications: `depends_on`/`maps` collection, downstream walk on the *newly derived* graph (unbounded depth, `contamination.path` recorded), additive→`stale` transitions, secondary token grep to the changelog's undeclared-references section.
8. **Regenerate.** Machine docs for diff-changed objects plus every affected index, rendered against HEAD enrichment (SY-5); pruning per generator semantics for removed objects (human siblings are never pruned — they were contaminated in stage 7); `generated_at` per D-33 rule B. Self-check: a second render must be byte-identical (KB-8 in-run) or the run fails.
9. **Write statuses.** Front-matter-only edits to human docs (`stale`, `contaminated` + `contamination:` detail) — nothing below the closing fence, ever (KB-4 is the CI backstop; this stage is the only writer).
10. **Author the PR.** Per KB §9: batched, severity-ranked changelog (breaking first with contaminated docs and lineage paths; rename candidates with both interpretations; additive-with-note items; undeclared possible references last), title `sync: <n> breaking, <m> additive across <systems>`, wheel-update commit when §10 applies, then supersede: auto-close prior unmerged sync PRs with a successor link (SY-3).
11. **Record.** Run record: `{run_id, triggers[], systems{included, excluded+reason}, kb_ref, snapshot_refs, classification counts, contaminated doc list, outcome, pr_url, duration}`. Health event on any non-`succeeded`/non-`no-op` outcome.

**HEAD movement race:** the run works against the stage-1 pinned `kb_ref`. If the push/PR fails non-fast-forward because HEAD moved (an enrich PR merged mid-run), the run records `retry_head_moved` and the coalescing mechanism immediately schedules a fresh run against the new HEAD — never a rebase of computed artifacts (determinism over cleverness).

## 6. Failure semantics (per stage)

| Stage | Failure | Outcome | Health surfacing |
|---|---|---|---|
| Acquire | Job dead-letter / timeout | System excluded (SY-6); run proceeds if others remain | Per job protocol + run record exclusion |
| Diff | Engine error | Run `failed` | Product-bug flag (deterministic code failed on validated inputs) |
| Lineage | Parse failure / merge error | Run `failed`, no PR, HEAD graph untouched | Named failing definition (the pre-argued libpg_query revisit trigger) |
| Scan | Any error | Run `failed`, no PR | Product-bug flag |
| Regenerate | Render error / KB-8 self-check miss | Run `failed`, no PR | Product-bug flag |
| PR | Git/API failure | Bounded retries (default 3, backoff), then `failed`; branch deleted | Git-provider health warning |
| PR | Non-fast-forward (HEAD moved) | `retry_head_moved` → immediate coalesced re-run | Informational |

A `failed` run leaves the estate exactly as it was: HEAD unchanged, prior sync PRs still open (supersede happens only on successful PR creation), snapshot accepted and available to the next run. Freshness (§8) keeps a persistently failing pipeline visible even if health events are ignored.

## 7. Concurrency and idempotency

Single-flight (SY-6) is deployment-global, not per-system, because a run writes one branch and one PR spanning systems. Coalescing: triggers landing mid-run set the pending flag; run completion (any outcome except `no-op` with pending flags clear) immediately evaluates for a follow-up. Net effect mirrors job §8: a storm yields the running run plus exactly one follow-up. Idempotency: because every stage is deterministic over pinned inputs, re-running any failed run reproduces its outputs byte-for-byte; combined with supersede, duplicate PRs are structurally impossible.

## 8. Freshness monitoring (OD-3 mechanism)

Evaluated on the scheduler tick, per system: `age = now − captured_at(latest accepted snapshot)`. `age > threshold` (per-system in `sync-policy.yaml`; shipped default 30 d; current customer: explicit per-system values) → dashboard warning naming the system, the age, the configured trigger mode, and — for manual-mode sources — the re-submission instruction; optional scheduled re-confirm reminders per policy. Warnings clear on the next accepted snapshot. `report_freshness` (MCP §6.9) serves the same computation; this section is the single definition both surfaces read.

## 9. Drill fixture (OB-3 deliverable)

Shipped with the product (SY-8): a fixture schema (DDL), a scripted breaking change (drop + rename-candidate + a view-definition change that does alter output columns), a seed KB fragment with `depends_on` declarations and one entity, and the expected outcome set (classifications, contaminated docs with paths, PR changelog shape). Running the drill against a deployment = playbook step-9 gate item 7; running it in platform CI = conformance SO-4. The fixture is versioned with the product and is the canonical regression net for the whole pipeline.

## 10. Vendored-wheel maintenance

The KB carries the validation library as a vendored wheel (`.github/vendor/` + provenance manifest — the recorded fence exception). When the platform release's wheel version differs from the KB's manifest, the orchestrator includes a **wheel-update commit** (new wheel + updated manifest: version, platform commit SHA) as the first commit of the next sync PR — so the PR's own KB CI run validates with the wheel that will govern after merge, keeping the update path exercised, auditable, and PR-reviewed like everything else. A manual "sync now" forces the carry when no drift is pending (the run is then wheel-only, changelog says so). No secrets, no other platform code — the exception's boundary is unchanged.

## 11. Conformance tests

| # | Test | Implements |
|---|---|---|
| SO-1 | Webhook: valid secret → `202` + enqueued job with `trigger.kind: webhook`; invalid secret → `401`, nothing enqueued; canary payload in the body never parsed or logged | SY-2, §4.2 |
| SO-2 | Policy edit merged to KB → next tick schedules per the new interval, no redeploy | §4.1 |
| SO-3 | N triggers during a running run → exactly one coalesced follow-up covering all pending systems | SY-6, §7 |
| SO-4 | Drill fixture end-to-end → exact expected classifications, contaminated set with correct `contamination.path`, front-matter-only writes (KB-4 green), changelog shape | SY-1, §5, §9 |
| SO-5 | Unchanged snapshots → `no-op` run record, no branch, no PR | §5.3 |
| SO-6 | Definition change with unparseable SQL → run `failed`, no PR, HEAD `graph.json` byte-unchanged, health names the definition | SY-4, §6 |
| SO-7 | Second run while a breaking PR is unmerged → new PR restates the still-true picture; prior PR auto-closed with successor link | SY-3 |
| SO-8 | Sync-PR renders byte-equal an independent fresh render of (pinned snapshot, pinned HEAD enrichment); purpose text present per D-38 | SY-5 |
| SO-9 | Snapshot age crossing threshold → warning with mode-appropriate guidance; next accepted snapshot clears it; a dead schedule (jobs failing) still warns | SY-7, §8 |
| SO-10 | Platform wheel version ≠ KB manifest → next sync PR leads with the wheel commit; KB CI in that PR runs the new wheel; provenance manifest fields correct | §10 |
| SO-11 | Acquisition failure on one of two systems → run ships the healthy system's drift, exclusion recorded; post-acquisition failure injected → whole run fails, no PR | SY-6 |
| SO-12 | Re-run of a failed run over identical pinned inputs → byte-identical branch content | SY-1, §7 |

## 12. Register actions and amendments (additive)

1. **Job protocol §11 JP-4:** **Closed** — webhook ingestion adopted as §4.2 of this spec (path identity, per-hook shared secret, body ignored). Master register updated.
2. **Playbook §14 OB-3:** **Closed** — drill fixture is a shipped artifact (§9), built as a CP-3 task. Master register updated.
3. **HLR §10 OD-3:** mechanism shipped (§8); item remains **Open** scoped to per-customer threshold values only.
4. **KB repository spec §9:** no change required; noted that supersede applies uniformly to breaking PRs (SY-3 makes explicit what §9 permitted).
5. **Spec index:** "Known gap" paragraph resolved; this document enters the map (governs: sync triggers, drift-run process, freshness, drill fixture; ruling prefix SY-1..8; unblocks CP-3).

## 13. Open decisions (spec-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| SO-A | Webhook debounce window beyond job dedupe + run coalescing | None — dedupe and single-flight already bound work to ≤2 runs per storm | If CI storms measurably churn snapshot jobs at a source with quota cost |
| SO-B | Auto-merge for additive-only sync PRs | Off; the PR carries a `sync:additive-only` label so customers can wire their own automation; product never merges | First customer drowning in trivially-mergeable PRs |
| SO-C | Webhook↔repo topology (monorepo emitting for several systems) | One hook per system; a monorepo's CI calls each relevant hook | First customer whose CI cannot target hooks per system |
| SO-D | Run acquisition budget | 2 h default, config in `sync-policy.yaml` | First estate whose snapshots legitimately exceed it |
| SO-E | Estate-wide re-render as a run mode (`regen-all`, pairs with KB-C) | Manual dashboard action producing a dedicated sync PR; never automatic | First template change requiring it in production |
