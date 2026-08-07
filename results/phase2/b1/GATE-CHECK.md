# B-1 — gate check, clause by clause

**Verdict: the gate stays OPEN.** One clause fails, it is named below, and
it is the same clause that was open this morning — D-101.5's end-to-end
demonstration. Everything else in B-1's gate text is met on extracted
evidence.

Written 2026-08-07 after the D-116 fixes, act 9, AS-18 and the same-day
extraction. Sources: the plan's B-1 gate paragraph (`plans/phase2-development-plan-v1.md`
§4), D-101.5, and the evidence files beside this one.

---

## 1. The clause that fails

**D-101.5's end-to-end demonstration:** *a request submitted with a
proposal → the steward's verdict in the dashboard → batch delivered → the
enrich PR merged as R2 → the requester sees the resolution.*

| Step | State | Evidence |
|---|---|---|
| request submitted with a proposal | **done** | issue `3f04d202…`, filed by `reporter`, 2 filings |
| steward's verdict in the dashboard | **done** (approve only) | `dashboard.ledger.verdict` `allowed` / `alper`, 09:47:43Z |
| batch delivered | **done** | `dashboard.ledger.batch`, `batch-61e70bc8…`, count 1, 10:53:52Z |
| the enrich PR | **opened, then rejected on its content** | KB PR #42, CI green, **rejected by the owner — D-117** |
| merged as R2 | **not done** | there is nothing to merge |
| the requester sees the resolution | **not done** | it follows the merge |

**Why the PR was rejected, and why that is not a defect in the loop.** The
skill drafted a good document and grounded it partly in the customer's
application source. The owner ruled that out (**D-117**): a request-driven
doc is grounded in the request and the estate, and nowhere else — *"cheating
for a test like this"*, and a KB claim sourced from a private codebase is
invisible to every drift mechanism the product has. The loop's machinery
worked end to end; the **policy the loop must follow changed after the
drafting act**, which is what a first real run is for.

**And the request is now blocked rather than draftable.** Its natural home
is `systems/supabase/public/subscriptions.md`, which is
`status: contaminated` with `refuse-unless-override`. D-117 clause 3 says a
blocked target **defers** — the content is not redirected onto another doc.
So this batch produces no document until that contamination is repaired,
which is act 5b's work and not this loop's.

**What closes this clause, concretely — two paths, both short:**

1. **A request whose target doc is uncontaminated.** File one, approve it,
   deliver the batch, run act 9. Under D-117 the skill drafts from the
   request alone, the PR is one doc, and the merge closes the loop. `~20`
   minutes plus one model call.
2. **Repair `public.subscriptions` out of contamination first** (act 5b),
   then re-deliver the existing batch. Answers the request that was actually
   asked, and clears 1 of the 32 contaminated docs on the way.

## 2. The clause that is *tested but not demonstrated*

**Reject-with-reason, and the badge it fires.** The runbook asked for three
requests so that a rejection would be exercised; **one** was filed, and it
was approved. So on the live pilot:

- `verdict: reject` with a reason — **not exercised** (0 rejected issues in
  the ledger extract).
- The rejection half of F-10's badge — **not exercised live.**

Both are covered by test (`core/test/dashboard-b1.test.ts`: *"a rejection
reaches the filer with its reason, and only that filer"*; the reason is
scrubbed and stored; a re-verdict after a refiling fires the badge again).
**A passing test is not a demonstration** (D-78), and this file does not
report it as one. Two minutes in the browser closes it: file a request you
would genuinely decline, reject it with a reason, sign in as that filer,
read the reason in *What came back*.

## 3. Everything else in the gate text — met

| # | Clause | State | Evidence |
|---|---|---|---|
| 1 | Freshness map consuming SO-F's `sync_enabled`; the two-silent-days shape visible | **met** | act 2 (5 sources; ga4 17d / gsc 6.3d stale against threshold); DT-9 green in both states and agreeing with `/healthz` (D-114.3); `results/phase2/b1/kb-health.json` |
| 2 | Doc-status counts | **met** | act 2: 2 verified / 6 draft / 34 contaminated of 42; recomputed today in `kb-health.json` |
| 3 | Drift-PR queue routing to the git provider, **no merge button — asserted** | **met** | act 4 (`drift_prs: {available: true, prs: []}` — the empty-and-says-why state); no-merge asserted over the server sources *and* the shipped bundle, not over a rendering (D-114) |
| 4 | Triage queue ordered by occurrences / distinct_subjects | **met** | act 5.1 (14 issues in queue order); keyset cursor asserted by test |
| 5 | LED-R5 neutralization asserted by test **on the render path** | **met** | `dashboard-ledger.test.ts` (hostile payload served inert), `mcp-ledger.test.ts`; extended to `list_gaps`'s new `filing` fields by MT-15 today |
| 6 | Gap resolution surfaces to the filer (F-10) — dashboard badge, rejection reasons and batch-merge resolutions alike; in-session surfacing **unbuilt and named so** | **built; half demonstrated** | badge ships per UI-D with server-side seen state; resolution half awaits §1's merge, rejection half is §2. In-session surfacing is named unbuilt in the plan, the runbook and the skill spec |
| 7 | Knowledge Requests queue: submissions with optional proposal, approve / reject-with-reason, approved worklist, deliver-batch trigger | **built; reject not demonstrated (§2)** | acts 6–8 live; DT-11/DT-12 green |
| 8 | **DT-11** — verdicts steward-gated server-side; a reporter's verdict is 403; approve records identity + timestamp, makes **no git call**, writes **no KB content** | **met** | test asserts against the KB's actual refs and PR store; live: `dashboard.ledger.verdict` `denied`/`reporter` at 09:47:17Z, `allowed`/`alper` at 09:47:43Z — **26 seconds apart, the same issue, in the audit** |
| 9 | **DT-12** — proposal renders inert in the queue and appears **nowhere verbatim** in the batch PR's diff | **met** | test both sides; live: PR #42's diff carries the figures as a table, no sentence of the requester's prose (and AS-18 asserts it mechanically) |
| 10 | UI-11 governs: approve ≠ certify; the diff remains the review; the merge remains the act | **met** | the verdict panel says it in words; no code path from a verdict to git; act 9's session opened a PR and **handed it over unmerged**, saying so |

## 4. What D-116 added, and its evidence

| Ruling | State | Evidence |
|---|---|---|
| **D-116.3** solo-operator mode stated plainly | done | playbook §11.1 + register OB-6 + KB spec §9; the KB's own `conventions.md` in **KB PR #43** |
| **D-116.4** a merge needs a check that demonstrably ran | done, **live** | `enrich/ci_gate.py` + `tests/test_ci_gate.py` (7 tests: green / failed / pending / caused-once / never-reported / tooling failure / the skill states the rule). Live: PR #42's `pull_request` run started **3 s** after opening, and the gate reported it green on both heads (`31180051513`, `31180320435`) |
| **D-116.5** `list_gaps` widened (B1-F8) | done, **live** | MCP §6.11.1 + MT-15. Live: the batched request read over MCP with `filing.by=reporter`, `filing.at`, `value_flags=['number']`, values intact; a reporter's call `permission_denied`. **AS-18 PASS, 9/9, tool trail opening `list_gaps` — no token anywhere** |
| **D-116.6** filing inlets audited (B1-F7) | done, **verified** | dashboard §5.1 amendment + test. Verified through the governed audit API on the fixture: `dashboard.ledger.file.enrichment_request`, subject = the filer, `result_meta {issue_id, occurrences, value_flags}`, args digested, **no words** (`filing-audit-fixture.json`). Not yet exercised on the pilot — its filings predate the fix, and the session did not manufacture one under the operator's identity |
| **D-116.7** the skill provisions its working copy (B1-F5) | done, **live** | `compile.test.ts`; live: the compiled steward bundle's CLAUDE.md named the remote and `~/cl-steward/kb`, and act 9's session checked out `main` and `pull --ff-only`ed it as its first act |
| **D-116.8** the disposition sentence | done, **live** | `dashboard-b1.test.ts`; live: the API now returns *"somebody asked for knowledge the estate does not have…"* instead of *"this core has no disposition recorded for the kind"* |
| **D-117** request-driven scope | recorded, **unexercised** | skill spec §6 + the shipped skill. Its live evidence is the *next* act-9 run; AS-18's staged batch already draws only on the request and the estate, which is the shape the rule requires |

## 5. Findings this half of the runbook produced

`FINDINGS.md` B1-F5 … B1-F10, numbered and each with its fix or its
recommendation. Two are open:

- **B1-F9** — the `batched → approved` return has no session-reachable
  inlet. Filed with a recommendation (a steward-gated MCP
  `return_request`), **not fixed**, because it is outside D-116's
  authorizations.
  > **Superseded 2026-08-07 (D-118.3): fixed.** The recommended tool is
  > built and tested (MCP §6.12, MT-16). It is **not granted on the
  > pilot's steward profile** — that is a KB profile PR, deliberately
  > left until after the closure demo so the operator's bundle does not
  > go stale mid-run. See `FINDINGS.md` B1-F9.
- **B1-F10** — fixed, but worth reading as a class: the bundle's
  determinism claim was false on any machine that had run the test suite.

## 6. Suites at this commit

| Suite | At entry | After the fixes |
|---|---|---|
| core (vitest) | 362 passed / 4 skipped / 30 files | **370 passed / 4 skipped / 30 files** (+8: MT-15 ×4, B1-F7, D-116.8, D-116.7, the bundle-residue test) |
| python (pytest) | 792 passed / 14 skipped / **1 failed** | **799 passed / 14 skipped / 1 failed** (+7: `test_ci_gate.py`) |

The one failure is `test_no_contamination_in_current_kb` — **estate state**
(32 of 38 human docs carry the estate-wide `stat_changed: checks` marker
from `users`), not this code. It was failing at entry, it is documented in
the runbook's prerequisites, and it is now also the thing standing between
§1 and its path 2.
- AS-18: **PASS**, 9/9 (`results/phase2/b1-as18/scenarios.json`).
