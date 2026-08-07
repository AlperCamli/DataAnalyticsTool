# A-5 — contamination triage plan for the pilot estate

Built 2026-08-07 from `worklist.py --kb ~/cl-steward/kb --batches` against
KB `6bea39d` and the accepted snapshot `supabase.json` (captured
2026-08-04T22:42:09Z). **33 contaminated docs**, four batches, and the
classification below is *provisional*: each steward session re-derives it
from the same evidence and is expected to disagree where it finds reason
to. A plan that could not be overruled by the person doing the work would
be a script, and the reading is the work.

## What actually happened to these docs

Every one of the 33 markers is the same event, and it is worth stating
plainly because it changes how the batches should be read:

> Sync run #34 (2026-08-04) was the first run after the platform started
> capturing `CHECK` constraints (SS-5, D-96.3d). Fifteen tables' `stats`
> changed — **`stat_changed: checks`** — and every human doc declaring a
> dependency on one of them was marked `contaminated`, plus everything
> the lineage graph carried it to.

Nothing was deleted, renamed, or retyped. The estate gained *more* facts
than it had before. So the expected shape of this backlog is not thirty
broken documents; it is thirty documents nobody has re-read since the
facts got sharper — and, as it turns out, **three that the sharper facts
contradict**. Those three are the reason this exercise is not a formality.

## Classification summary

| Class | Count | What the batch does |
|---|---|---|
| `confirms-prose` | **30** | front-matter only: marker cleared, `status: draft`, hash refreshed. Bodies byte-unchanged |
| `needs-re-grounding` | **3** | `ai_runs.md`, `ai_prompt_configs.md`, `v_jobs_by_status.md` — the constraint contradicts the prose |
| `depends-on-missing-object` | **0** | every `depends_on` in the contaminated set resolves against the current snapshot |

One doc in the 30 carries an **anomaly** rather than a clean confirm, and
it is called out in batch 4: `usage_counters.md` has **no contamination
marker at all** — PR #37 already re-grounded it and cleared the marker but
left `status: contaminated`, because at the time nothing said what status
a repaired doc lands in. S1c now does (`draft`), so that doc's repair is a
one-line status transition and a hash check.

### The three that need re-grounding — the whole reason to do this

1. **`systems/supabase/public/ai_runs.md`** — says `flow_type` is
   "DB-constrained to the **11-value set**". The constraint captured on
   2026-08-04 admits **13**: the doc's list is missing `skills_pool` and
   `professional_summary`. A report filtering flows on the documented set
   silently drops two of them.
2. **`systems/supabase/public/ai_prompt_configs.md`** — the same
   enumeration, written out in full, and missing the same two values. The
   two docs cross-reference each other ("Same set as
   `supabase.public.ai_runs.flow_type`"), so they are wrong together and
   must be repaired together. They are in the same batch for that reason.
3. **`systems/supabase/reporting/v_jobs_by_status.md`** — says
   "`status` is **not constrained by a database CHECK**, so new values can
   appear". `public.jobs` carries
   `CHECK (status IN ('saved','applied','interview','offer','rejected','archived'))`.
   The doc's warning is the opposite of the truth, and it is a warning a
   report author would act on.

None of these could be found by looking at a marker. All three were found
by reading the prose against the constraint, which is what the mode is
for.

## The batches

Grouped so each pull request tells one story. Report-path counts are
against the golden suite's `expected_objects` (KB §3.1) — now readable
from the KB itself.

### Batch 1 — the AI-run family (8 docs, 8 on the report path)

`ai_runs.md`⚠ · `ai_prompt_configs.md`⚠ · `ai_suggestions.md` ·
`cv_block_revisions.md` · `v_ai_runs_by_day.md` · `v_ai_runs_by_flow.md` ·
`v_ai_tokens_by_month.md` · `v_daily_activity.md`

⚠ = `needs-re-grounding`. The other six state the `status`
(`pending|completed|failed`) and `action_type` sets exactly as constrained,
or say nothing about the changed columns. **Do this batch first:** it
carries two of the three real defects, and `ai_runs` is RB-09's expected
object.

### Batch 2 — exports, files and imports (10 docs, 8 on the report path)

`exports.md` · `cover_letter_exports.md` · `cover_letters.md` ·
`files.md` · `cv_templates.md` · `imports.md` · `v_exports_by_format.md` ·
`v_files_by_type.md` · `v_imports_by_parser.md` ·
`v_activation_funnel_monthly.md`

All ten `confirms-prose`. The export docs enumerate
`processing|completed|failed` and `pdf|docx` exactly as the constraints do,
including the lifecycle CHECK tying `status` to `file_id`/`completed_at`/
`error_message`. `cv_templates.md`'s "no DB enum on `status`" claim is
still true — `cv_templates` has no CHECK — and must not be "corrected".

### Batch 3 — jobs, CVs and their views (10 docs, 8 on the report path)

`jobs.md` · `job_status_history.md` · `master_cvs.md` · `tailored_cvs.md` ·
`users.md` · `v_jobs_by_month.md` · `v_jobs_by_status.md`⚠ ·
`v_job_status_transitions.md` · `v_master_cvs_by_language.md` ·
`v_cv_production.md`

Nine confirm — `jobs.status`, `from_status`/`to_status` and
`source_type` are all documented exactly as constrained, and `jobs.md`'s
note about legacy `interviewing`/`offered` spellings is history the
constraint does not contradict. One (`v_jobs_by_status.md`) asserts the
absence of the constraint that exists.

### Batch 4 — entities, GA4 and the leftovers (5 docs, 5 on the report path)

`entities/conversion.md` · `entities/user.md` · `systems/ga4/dimensions.md` ·
`v_user_cohorts.md` · `usage_counters.md`†

The two entity docs and `v_user_cohorts.md` say nothing about the
constrained columns (`users.locale` is `en|tr`; neither doc claims a
locale vocabulary). `ga4/dimensions.md` states
`supabase.public.exports.status` values and states them correctly.
† `usage_counters.md` is the marker-less anomaly above.

**Batch 4 is also where the `public.subscriptions` question would have
lived, and it does not, because the repair already happened.** During the
B-1 closure run the operator merged KB PR #44 (marker cleared),
certified the doc by hand, and merged PR #45 (pro-plan pricing, which
lowered it back to `draft` pending re-certification). `subscriptions.md`
is therefore **not in this backlog at all**. What is still open is the
*pricing* question, and it is not a contamination question:

- ledger `4c4ecb3d` (`other`, **open**) — the Stripe verdict: read
  `unit_amount` behind `STRIPE_WEEKLY/MONTHLY/ANNUAL_PRICE_ID` and settle
  which side is right;
- ledger `3f04d202` (`enrichment_request`, **still `batched`**) — the
  second filing, carrying `99.99` where the merged doc records `99.00`
  as customer-confirmed.

**No batch waits on that verdict.** It touches a doc that is already
repaired and a number already recorded as customer-stated, with the
disagreement named in the doc's own sources line. When the verdict
arrives it is an ordinary enrichment PR against a `draft` doc, not a
triage repair.

## Running a batch (STOP-1 — the operator's)

Each batch is one steward session in `~/cl-steward`, per D-118.1: the
customer-shaped environment, never the dev workspace. Per batch:

1. `cd ~/cl-steward` and start Claude Code with the steward bundle.
2. Paste the batch's prompt (below).
3. Read the diff. The `confirms-prose` docs should be **front-matter-only**
   — if a body moved, ask why before merging.
4. **Certify the docs you accept**, on the branch, under your own name:
   set `status: verified` and `last_verified: "2026-08-07 (alper)"`, commit
   that as your own commit, then merge. That commit is the certification
   act (D-116.3); the skill cannot perform it and must not.
5. `python3 .claude/skills/enrich/ci_gate.py <pr>` before calling it ready
   — an absent check is not a pass (D-116.4).

Four batches, four PRs, four merges. Nothing here is merged by a session.

---

## Paste prompts

### Batch 1

```
Use the `enrich` skill in contamination-triage mode (S1c) on batch 1 of the
A-5 triage plan.

The batch, in this order:
  systems/supabase/public/ai_runs.md
  systems/supabase/public/ai_prompt_configs.md
  systems/supabase/public/ai_suggestions.md
  systems/supabase/public/cv_block_revisions.md
  systems/supabase/reporting/v_ai_runs_by_day.md
  systems/supabase/reporting/v_ai_runs_by_flow.md
  systems/supabase/reporting/v_ai_tokens_by_month.md
  systems/supabase/reporting/v_daily_activity.md

Follow S0 first (working copy at ~/cl-steward/kb, pulled, clean), then
S1c: build the work list with worklist.py, classify each doc yourself
against the snapshot's CHECK constraints, and repair per class. The plan's
provisional classification says two of these need re-grounding
(ai_runs.md and ai_prompt_configs.md both describe flow_type as an
11-value set) — check that against the constraint rather than taking my
word for it, and say so if you disagree with any classification.

Re-render and validate before opening the PR. One PR for the batch, with
the per-doc classification table and the certification block. Do not
certify anything yourself and do not merge.
```

### Batch 2

```
Use the `enrich` skill in contamination-triage mode (S1c) on batch 2 of the
A-5 triage plan.

The batch:
  systems/supabase/public/exports.md
  systems/supabase/public/cover_letter_exports.md
  systems/supabase/public/cover_letters.md
  systems/supabase/public/files.md
  systems/supabase/public/cv_templates.md
  systems/supabase/public/imports.md
  systems/supabase/reporting/v_exports_by_format.md
  systems/supabase/reporting/v_files_by_type.md
  systems/supabase/reporting/v_imports_by_parser.md
  systems/supabase/reporting/v_activation_funnel_monthly.md

S0, then S1c as written. The plan expects all ten to be confirms-prose —
which means ten front-matter-only diffs, and if you find yourself editing
a body, that doc was misclassified and you should say so rather than
quietly widen the repair. Note that cv_templates.status genuinely has no
CHECK constraint; the doc saying so is correct and stays.

Re-render, validate, one PR, certification left to me.
```

### Batch 3

```
Use the `enrich` skill in contamination-triage mode (S1c) on batch 3 of the
A-5 triage plan.

The batch:
  systems/supabase/public/jobs.md
  systems/supabase/public/job_status_history.md
  systems/supabase/public/master_cvs.md
  systems/supabase/public/tailored_cvs.md
  systems/supabase/public/users.md
  systems/supabase/reporting/v_jobs_by_month.md
  systems/supabase/reporting/v_jobs_by_status.md
  systems/supabase/reporting/v_job_status_transitions.md
  systems/supabase/reporting/v_master_cvs_by_language.md
  systems/supabase/reporting/v_cv_production.md

S0, then S1c. One of these (v_jobs_by_status.md) warns that public.jobs
has no CHECK on status, and the snapshot says it does — check it, and if
you agree, re-ground that warning from the constraint and say what the
doc got wrong. The rest are expected to confirm.

Re-render, validate, one PR, certification left to me.
```

### Batch 4

```
Use the `enrich` skill in contamination-triage mode (S1c) on batch 4 of the
A-5 triage plan — the last one.

The batch:
  entities/conversion.md
  entities/user.md
  systems/ga4/dimensions.md
  systems/supabase/reporting/v_user_cohorts.md
  systems/supabase/public/usage_counters.md

S0, then S1c. Two things specific to this batch:

- usage_counters.md has NO contamination marker but is still
  `status: contaminated` — PR #37 re-grounded it and cleared the marker
  without moving the status. Check its hash against the current snapshot
  and land it `draft` like any other repair; if the hash does not match,
  it is a real re-grounding and should be treated as one.
- entities/*.md are entity docs: their `maps:` block is the contamination
  contract, so check that every mapped object still resolves before you
  call either one confirmed.

Re-render, validate, one PR, certification left to me.
```
