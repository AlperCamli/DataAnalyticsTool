# Status after D-96 — what closed, what is open, what is yours

Written 2026-07-31 at the end of the D-96 application session. Task 4 of
the ruling's work order: the C-conditions that remain open, and the two
operator re-runs. Nothing here restates a claim without a pointer.

---

## The six REAL-blocking C-conditions

| # | Condition | State | Where it goes |
|---|---|---|---|
| **C-1** | Land the runner-config Power BI line | **CLOSED** | commit `9463e61`. CP-7 is no longer closed over unlanded work |
| **C-6** | Extract the gate evidence; carry F-4 nodes into the KB | **CLOSED to the point the session can take it** | `066e916` (five dump files + reading), `8bcadf4` (KB PR #30). CP-7 exit item 2 is **evidenced, not closed** — it closes on the post-merge `get_lineage` call |
| **C-2** | Ship `review-sync`, or record its removal | **OPEN — Phase-2 Track A-1** | D-96.3c ruled BUILD, not despecify. Now *visibly* open: since F-7, `compile steward` fails rather than shipping a bundle without it |
| **C-3** | Supported bundle delivery **and** bundle freshness | **OPEN — Phase-2 Track A-2** | PA-1 + PA-2. Untouched by this session; it is a product surface, not a chore |
| **C-4** | Certified metrics + human-verified report-path docs | **OPEN — Phase-2 Track A-5** | Still 41 draft / 1 verified on `origin/main`, still no `metrics/` directory. Onboarding work on a example estate, not engineering |
| **C-5** | Benchmark wired into KB CI | **OPEN — Phase-2 Track A-5** | `kb-ci.yml` still runs `generator.validate` and nothing else. Note PR #32 rewrites that file's install step — the benchmark job is a separate, later edit |

**Two closed, four open.** All four open ones are Track A by D-96.1's
adoption of the two-track shape, and none was in this session's scope.

### The unassisted-onboarding conditions (U-1…U-5)

All five remain open; none was in scope. For the record, one moved
indirectly: **U-4** (OB-4 instrumentation) was ruled BUILD by D-96.3g and
placed in Track A-6, so it is no longer in the "cannot close" state the
review objected to — but nothing has been built.

---

## The two operator re-runs (D-96.2)

Both are gate acts reclassified **NOT DEMONSTRATED** once the rows were
read. Neither can be fixed by re-reading; the evidence was never written.

**Act 2 — cross-source on certified entity keys.** All 12
`validate_sql`/`execute_sql` rows in the gate window carry
`system: supabase`. No `ga4`/`gsc` execution exists under the reporter
identity anywhere in the window. Prerequisites *were* in place (KB PR #29
merged 10:48; `entities/page.md` `status: verified`), so this reads as an
act not run, not one blocked.

**Act 3b — undocumented-blend refusal.** Both ledger events in the window
are `capability_gap`. No `missing_join_path` event exists, which is the
ledger half RA-9/D-83.5 requires of this refusal.

Both re-run under **Track A-0**, and under D-96.2's standing rule:
**extract the same day, before the session ends** (now written into
`results/cp7-gate/RUNBOOK.md` §9). Act 1 is confirmed and over-evidenced;
Act 3a passes under D-94.4's either-shape and is not re-run.

---

## What is waiting on you

### 1. Three KB pull requests — all CI-green, all mergeable, one ordering

The session opens PRs and never merges (SO-B).

| PR | What | Constraint |
|---|---|---|
| [#32](https://github.com/AlperCamli/DataAnalyticsTool/pull/32) | `ci:` wheel pin → `VENDOR-MANIFEST.yaml` (R-6b) | **Merge before the drift run** — see below |
| [#30](https://github.com/AlperCamli/DataAnalyticsTool/pull/30) | `sync:` F-4 report nodes → `lineage/graph.json` | independent |
| [#31](https://github.com/AlperCamli/DataAnalyticsTool/pull/31) | `docs(index):` public-by-choice note (R-1) | independent |

**#30's mislabel is fixed** (ruling D-97.1). It originally read `sync: 0
breaking, 0 additive across ` with the body *"Wheel-only run…"* — there
is no wheel in it. `changelog.ts` now has a graph-only case, and the PR's
title and body were rewritten to exactly what the fixed code emits for
that run's inputs, rendered from the code rather than hand-written. **No
commit, file, or byte of its content changed**; a note on the PR records
the correction.

**The ops half of that mislabel is still open.** `detail.wheel_only` is
set on any run with `changed.length === 0`
([pipeline.ts:666](../../core/src/pipeline.ts#L666)), so run
`01KYVXMQ8Q0BAHTKC8WM5WBK5S` is stored in `runs` as wheel-only when no
wheel was involved. D-97.1 authorized the `changelog.ts` case only; this
is a different field with a different consumer (the `runs` table, read by
ops and by the dashboard's future U-10 view), so it stays flagged.
Recommended for the same Track A-0 chore: `{ wheel_only: !!wheelCarry,
graph_only: gatewayPending }`.

### 2. The SS-5 drift PR — deliberately not opened

Full reasoning and the exact command sequence:
[`ss5-capture-verification.md`](ss5-capture-verification.md). In short:
the 0.6.0 wheel carry deletes the 0.5.0 wheel file, `origin/main`'s
`kb-ci.yml` still hardcodes that filename, and since R-6(b) the carry no
longer edits workflow files — so a drift PR opened today would install a
wheel its own branch deleted and fail loudly. **Merge #32, then:**

```bash
docker compose exec core node dist/cli.js sync now supabase
```

Expect a wheel commit first, then the re-rendered docs: Check-constraints
sections across ~15 tables **including `public.ai_runs`' status
vocabulary** — the finding that started SS-5 — plus the estate's own
34 → 38 object drift since 2026-07-27.

### 3. Drop `workflow` write from the sync PAT — R-6 closes on this

PR #32 only makes the narrowing possible. Exact steps, including the
verification step, are in that PR's body. **Until it is done the risk is
still carried**, and #32 is a no-op for it.

### 4. After merging #30 — close CP-7 exit item 2

As the reporter, against the live server:

```
get_lineage(object: "powerbi.report.bae55769-0cb3-41ba-877a-e9cd77a964d8")
```

Expect the three reporting views at hop 1. The walk is already verified
against the PR's graph (15 nodes / 17 edges at depth 3); what is missing
is that the server's workspace is still pinned pre-merge.

---

## Two things found while working, neither in scope

1. **`compile steward` now fails — and this is correct.** Ruled so by
   **D-97.2**, recorded so nobody "fixes" it. The shipped steward profile
   names `review-sync`, F-7 makes a missing skill fatal, and D-96.3c
   ruled BUILD rather than despecify. Server-side steward access is
   unaffected — only the compiled bundle is blocked, until Track A-1. If
   a steward bundle is needed before then, that is a conversation, not a
   quiet re-loosening of the compile.
2. **Your `~/Desktop/kb` working tree has three uncommitted files** —
   `systems/supabase/index.md`, `systems/supabase/reporting/index.md`,
   `systems/supabase/reporting/v_ai_runs_by_day.schema.md` — reformatted
   by an editor into padded markdown tables. These are **machine docs**;
   committing them would break KB-8 render consistency in CI. Left
   untouched (they are not this session's to discard). Recommend
   `git checkout --` on those three before the drift PR lands, or the
   next render will fight them.

---

## Register state after this session

**Closed:** SS-5 (by capture, D-96.3d) · OB-3, JP-4 (bookkeeping
reconcile — both had been declared Closed by the sync spec while the
master row still said Open) · R-1, R-2, R-3 (in `DECISIONS.md`).
**Added:** the SO-A…SO-G section, absent from the master register since
the sync spec was written.

**Ruled by D-96.3 but NOT applied here**, because D-96.4's bookkeeping
batch does not name them and the task list did not either — they are
Phase-2 planning inputs, listed so they are not lost:

- **RA-F** — re-date the decision to 2027-01-31 / first
  `push_limit_exceeded` / second Power BI customer (D-96.3e), plus the
  80 %-of-limit publisher warning as a Track-A chore.
- **SUPPRESS-1** — tighten the trigger and name the home (profile
  `limits.min_cell_count` for enforcement, artifact for disclosure).
- **PA-1 / PA-2** → Track A-2 · **SO-F** → Track B-1 · **OB-4** → Track
  A-6 · **R-5 / R-6 / R-8** row updates · **BASELINE-1**'s restated gate.
- **`review-sync` unbuilt** is still not a register item at all; it is a
  CP-8 finding with a ruling (D-96.3c) and no row.

D-96.5's standing constraint — **no quantitative KB-value claim in any
customer or demo material until BASELINE-1 lands** — is carried in
`DECISIONS.md`; D-96.6 requires it verbatim in the Phase-2 plan, which is
the planning session's document, not this one's.

---

## Suites at this commit

- Python: **732 passed / 14 skipped**, including 25/25 container-backed
  postgres conformance (C-1/C-2/C-3/C-4/C-8 re-run against the changed
  connector).
- Core: **191 passed** (188 at the JC-4 verification, +3 for D-97.1's
  graph-only cases). The JC-4 standard — three consecutive full runs
  under deliberate load — was met at 188
  ([`jc4-verification/`](jc4-verification/)); the three tests added since
  are pure string assembly with no lease or container involvement, so
  that verification is not re-opened by them.
- Live example estate: two consecutive supabase pulls, canonical body
  `bef2fa14c60a3520…` byte-identical with `stats.checks` in it.
