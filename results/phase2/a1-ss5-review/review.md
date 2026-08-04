# Sync review: sync: 15 breaking, 4 additive across supabase (KB PR #34)

Verdict: BREAKING — repair before merge
Fifteen tables gained hash-included CHECK capture (the SS-5 first-capture
wave, expected per D-99.4 — checks *appearing*, not schemas moving) and
the fan-out contaminates 35 human docs, including two entity docs; this
PR must merge to record reality, and the repair is a re-verification
campaign, not a rewrite.

## Breaking (ranked by blast radius)

All routes below are **declared dependencies** — no contamination in this
PR arrived through a lineage path. Fan-out is the changelog's per-object
lists (authoritative); `triage.py` over the branch counts the same **35
distinct contaminated docs** (each multiply-hit doc records one primary
object in its front-matter). Every change is `stat_changed: checks`.

1. `supabase.public.users` — blast radius: 20 docs
   - contaminates `entities/conversion.md`, `entities/user.md`, and 18
     `systems/supabase/**` docs (16 public tables' docs + `v_activation_funnel_monthly.md`,
     `v_user_cohorts.md`, `v_user_signups_by_day.md`) — all declared dependency
2. `supabase.public.tailored_cvs` — blast radius: 14 docs
   - contaminates `entities/conversion.md` + 13 `systems/supabase/**` docs
     (declared dependency)
3. `supabase.public.master_cvs` — blast radius: 11 docs
   - contaminates 11 `systems/supabase/**` docs (declared dependency)
4. `supabase.public.jobs` — blast radius: 9 docs
   - contaminates `jobs.md`, `users.md`, `ai_runs.md`, `cover_letters.md`,
     `job_status_history.md`, `tailored_cvs.md`, `v_daily_activity.md`,
     `v_jobs_by_month.md`, `v_jobs_by_status.md` (declared dependency)
5. `supabase.public.exports` — blast radius: 8 docs
   - contaminates `entities/conversion.md`, **`systems/ga4/dimensions.md`**
     (the cross-system hit that exposed D-99), `cv_templates.md`,
     `exports.md`, `files.md`, `v_activation_funnel_monthly.md`,
     `v_daily_activity.md`, `v_exports_by_format.md` (declared dependency)
6. `supabase.public.ai_runs` — blast radius: 7 docs
   - contaminates `ai_prompt_configs.md`, `ai_runs.md`, `ai_suggestions.md`,
     `v_ai_runs_by_day.md`, `v_ai_runs_by_flow.md`, `v_ai_tokens_by_month.md`,
     `v_daily_activity.md` (declared dependency) — includes the `ai_runs.status`
     vocabulary that started SS-5 (D-86.3b)
7. `supabase.public.files` — blast radius: 5 docs (declared dependency)
8. `supabase.public.ai_suggestions` — blast radius: 3 docs (declared dependency)
9. `supabase.public.cover_letter_exports` — blast radius: 3 docs (declared dependency)
10. `supabase.public.cover_letters` — blast radius: 3 docs (declared dependency)
11. `supabase.public.imports` — blast radius: 3 docs (declared dependency)
12. `supabase.public.job_status_history` — blast radius: 3 docs (declared dependency)
13. `supabase.public.cv_block_revisions` — blast radius: 2 docs (declared dependency)
14. `supabase.public.ai_prompt_configs` — blast radius: 1 doc (declared dependency)
15. `supabase.public.usage_counters` — blast radius: 1 doc (declared dependency)

**Not contaminated, worth stating:** `entities/page.md` — the estate's one
certified doc — is untouched (its `maps` are gsc/ga4 objects, none of the
fifteen tables). The certification survives this wave intact.

## Rename candidates (human decision required)

None in this PR — every breaking item is `stat_changed: checks`; no
column moved, appeared, or disappeared.

## Additive

- `supabase.reporting.v_mart_dim_ai_flow` — added (view)
- `supabase.reporting.v_mart_dim_breakouts` — added (view)
- `supabase.reporting.v_mart_fact_daily` — added (view)
- `supabase.reporting.v_mart_fact_monthly` — added (view)

Four new undocumented views (the estate's own 34→38 drift). No doc
depends on them, so nothing went stale; they are an **enrichment
candidate batch** once this wave settles, not a repair item.

## Docs marked stale

None — the additive objects are new, so no verified doc depends on them.

## Undeclared references (non-authoritative)

Body-text mentions of changed objects in docs that do not declare them —
surfaced for reviewer attention only; the scan does not flag them and
neither does this review:

- `cover_letter_exports.md` mentions `supabase.public.exports`
- `exports.md` mentions `supabase.public.cover_letter_exports`
- `files.md` mentions `supabase.public.usage_counters`
- `usage_counters.md` mentions `ai_runs`, `ai_suggestions`, `exports`, `files`

These read like real cross-references; at repair time the steward may
choose to promote them to declared `depends_on` entries — a judgment
call, not a scan finding.

## Branch discipline (checked, not assumed)

Two commits, in the §10 order: the wheel commit first
(`vendored validation wheel 0.6.0 (platform 468fe87…)`) staging
`.github/vendor/**` only — manifest rewritten, 0.5.0 wheel removed,
0.6.0 added, **no workflow file touched** (R-6b holding); then the sync
commit: front-matter status writes on human docs + machine re-renders
only. KB CI **green** on the branch — including
`systems/ga4/index.md`, re-rendered this run by the D-99 fix and now
agreeing with its contaminated `dimensions.md` (the exact file that
failed superseded PR #33). PR #33 closed by SY-3 supersession with the
successor link.

## Served trust state (present)

The deployed workspace (`/healthz` `kb_ref 462421c`) **is** current
`origin/main`, so what agents are served today is the pre-merge state:
all 35 docs still `verified`/`draft` with `use-freely`/`warn` guidance,
while the estate's CHECK constraints are already live facts. The gap is
the urgency: every day unmerged is a day agents trust vocabulary claims
the source now states machine-readably. *(Method note: this review ran
without a steward MCP session; served state is derived from the deployed
`kb_ref` equalling `main`'s head, which makes the main checkout the
served state by identity. A steward-session re-check via `get_table`
trust blocks would add nothing here but is the normal S1 path.)*

## Recommendation

Breaking PR — **merge to record reality, then repair as a campaign.**
The markings are accurate (verified against the changelog, the branch
tree, and triage), and landing them converts silent drift into visible
`contaminated` status. Holding the PR for repairs would keep 35 wrong-ish
docs served as trustworthy meanwhile.

This wave is **first-capture semantics** (D-99.4): the source did not
change meaning — the snapshot started carrying meaning it always had. So
the expected repair per doc is *re-verification*, not rewriting:

1. Compare each doc's vocabulary/enum claims against the captured
   `stats.checks` text in its machine sibling (now in the branch).
2. Where they agree — the likely majority, since these docs were
   enriched from the app's own DDL migrations — the human clears
   `contamination`, refreshes `written_against_schema_hash`, and sets
   `last_verified`: a certification act, batched.
3. Where a CHECK **contradicts** the doc (the D-86.3b class — the reason
   SS-5 exists), fix the text first, then certify.

Suggested batches (≤10 docs each, SP-3 discipline), by unblock order:

- **Batch 1 — the entity + AI chain** (highest leverage: 2 entity docs
  route reporters; the AI docs sit under the M3 report path):
  `entities/user.md`, `entities/conversion.md`, `ai_runs.md`,
  `ai_suggestions.md`, `ai_prompt_configs.md`, `v_ai_runs_by_day.md`,
  `v_ai_runs_by_flow.md`, `v_ai_tokens_by_month.md`, `v_daily_activity.md`.
- **Batch 2 — users/jobs/CV core**: `users.md`, `jobs.md`,
  `job_status_history.md`, `master_cvs.md`, `tailored_cvs.md`,
  `cv_block_revisions.md`, `cv_templates.md`, + `v_jobs_by_*`, `v_user_*`.
- **Batch 3 — files/exports/imports + remaining reporting views**, and
  the undeclared-reference promotions decided along the way.

Each batch is a separate repair PR against `main` under the steward's
identity; this review merges nothing and edits no sync-PR ref —
certification is the human merging with their name (KB-7).
