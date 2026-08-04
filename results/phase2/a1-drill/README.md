# A-1 live drill — the steward loop, rehearsed on the pilot estate

Playbook gate item 7, human half — **first-ever rehearsal** (D-98.3).
Staged breaking change → sync PR → steward runs review-sync → repair PR
→ re-verification, with the estate returned byte-identical. Evidence
extracted same-day per D-96.2. Every claim below has a pointer.

## The staged change

`reporting.v_user_signups_by_day.signup_day → signup_date` — one view,
one column, same type/ordinal (`deploy/a1-drill-rename.sql`), applied by
the operator as DBA (D-81: the session drafted, never ran DDL). Revert:
`deploy/a1-drill-revert.sql`, same discipline.

## Timeline (all times 2026-08-04Z unless noted)

| Act | Evidence |
|---|---|
| Baseline: SS-5 drift flushed — KB PR #34 merged 18:46 | `../a1-ss5-review/` (the same-day review-sync review of the real wave) |
| Operator applies the rename DDL (STOP-1) | operator act; visible in the next snapshot |
| `sync now supabase` → run `01KZ72A3…` → **PR #35**: `1 breaking, 1 additive`, the rename candidate with both interpretations, contamination = exactly the one enriched doc; KB CI green | `pr-35.json` / `pr-35.diff`; `doc-states/2-…` |
| **Deviation 1 (recorded):** operator merged #35 at 19:00, *before* the steward review — the merge-to-record-reality default exercised early; the review became a review of record | `pr-35.json` `mergedAt` |
| STOP-2: steward session on the **first-ever compiled steward bundle** runs review-sync per its own instructions; consults the deployment (audit: `get_table` ×3, `get_lineage`, `list_gaps` — zero execute/publish, zero flag_gap → no ledger events); prepares repair **PR #36** with the rename decision recorded as a graded source | `audit-window.tsv`; `pr-36.json` / `pr-36.diff`; `doc-states/3-…` |
| **Field lesson (fixed same day):** #36 shipped without regenerating the machine sibling → KB CI failed KB-8; regeneration pushed (validate 0/0, CI green); review-sync S4 now states the regeneration duty explicitly (platform `634c8c3`) | DECISIONS STOP-2 field notes |
| Operator merges #36 (22:32) and #37 (22:34 — their enrich test, which doubled as the first SS-5 re-verification-campaign item) | `pr-36.json` |
| **Deviation 2 (recorded):** the verification flip was NOT made before the revert — the doc landed repaired but `status: contaminated`, `last_verified: null`. Certifying `signup_date` after the estate reverted would have been dishonest; the flip moves to the closing reconciliation below | `doc-states/3-…` front-matter |
| STOP-3: operator applies the revert DDL (2026-08-05) | operator act; visible in the final snapshot |
| Final cycle: `sync now supabase` → run `01KZ7F1Z…` → **PR #38**: the mirror image (`signup_date → signup_day` rename candidate, same `v_mart_fact_daily` deparse ripple), doc correctly re-contaminated | `pr-38.json` |
| **The estate is byte-identical**: pre-drill pin (main@`d7b0218`) and PR #38's pin have the same canonical body hash `sha256:4ecf4951b540c00b…` (S-3 verified across apply+revert) | `byte-identical-check.txt` |

## Closing reconciliation (the remaining acts, operator's)

1. Merge **PR #38** (records the reverted reality).
2. The session opens the reconciliation repair PR: doc text back to
   `signup_day`, machine sibling regenerated (the S4 duty, this time by
   the amended skill text), contamination cleared, hash refreshed.
3. **The operator flips `status: verified` + `last_verified` with their
   own name on that PR and merges — the gate's certification act,
   performed against the true estate.** The A-1 gate item "doc
   re-verified, recorded" closes there, not before.

## What the drill proved, honestly

- The full loop ran on the live estate with the product's own tools:
  break → drift PR (correct shape, one-doc blast, both rename
  interpretations) → steward review with audited MCP consultation →
  repair PR → revert → byte-identical estate.
- Two operator-sequence deviations and one skill-text gap were found —
  which is what first rehearsals are for. All three are recorded here
  and in DECISIONS; the skill gap is already fixed and shipped.
- Boundaries held throughout: the session applied no DDL, merged
  nothing, and wrote no verified status; every merge and the pending
  certification are the human's, under their name.
