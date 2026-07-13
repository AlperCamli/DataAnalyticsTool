---
doc_class: human-object
object: supabase.public.ai_suggestions
written_against_schema_hash: "sha256:c326f46f6e3edfd4eb7ab7a81bbc17869a290886d0c8d10fd5e52f32556c605d"
status: draft
last_verified: null
purpose: "Block-level AI suggestions produced by an AI run, scoped to a master or tailored CV and pending review/apply."
column_purposes:
  id: "Internal suggestion id."
  ai_run_id: "AI run that produced this suggestion (FK to ai_runs.id)."
  user_id: "User the suggestion is offered to (FK to users.id)."
  tailored_cv_id: "Tailored CV this suggestion targets, when scope is tailored (FK)."
  block_id: "Identifier of the CV block the suggestion applies to, if block-scoped."
  action_type: "Kind of edit suggested; enum in body."
  before_content: "Snapshot of block content before the change as JSONB; structure in body."
  suggested_content: "Proposed block content as JSONB; structure in body."
  option_group_key: "Grouping key linking sibling suggestions offered as alternatives."
  status: "Review state of the suggestion; enum in body."
  applied_at: "When the suggestion was applied to the target CV."
  created_at: "When the suggestion was created."
  master_cv_id: "Master CV this suggestion targets, when scope is master (FK)."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/ai_suggestions.md"
  - "app DDL: CV_Builder/backend/supabase/migrations (ai_suggestions_action_type_check, ai_suggestions_status_check, scope + applied-consistency checks)"
  - "app code: CV_Builder/backend/src (suggested_content built from a CvBlock)"
  - "machine doc: supabase.public.ai_suggestions"
depends_on:
  - supabase.public.ai_runs
  - supabase.public.users
  - supabase.public.tailored_cvs
  - supabase.public.master_cvs
  - supabase.public.cv_block_revisions
contamination: null
---

# `supabase.public.ai_suggestions`

## Grain

One row per proposed block edit. A scope CHECK enforces **exactly one** of
`tailored_cv_id`/`master_cv_id` is set per row. An applied-consistency CHECK
ties `status = 'applied'` to `applied_at` being non-null (and the non-applied
states to `applied_at` being null).

## Column meanings & enum decodings

- `action_type` — DB-constrained to **`rewrite`, `summarize`, `improve`,
  `ats_optimize`, `options`, `expand`, `shorten`** (same set as
  `supabase.public.ai_prompt_configs.action_type`).
- `status` — DB-constrained to **`pending` | `applied` | `rejected` |
  `expired`** (default `pending`).
- `option_group_key` (nullable) — when a flow returns several alternatives
  (`action_type = 'options'`/`multi_option`), siblings share this key.
- `before_content` (nullable) and `suggested_content` (non-null) — `jsonb`
  **`CvBlock`** snapshots (see `supabase.public.master_cvs` for the shape):
  `suggested_content` is built from a replacement `CvBlock` in code;
  `before_content` is the prior block, null when there was none. Stored as open
  maps (`Record<string, unknown>`), so `CvBlock` is the expected — not
  DB-enforced — structure.

## Join guidance

- Provenance: `ai_suggestions.ai_run_id` → `supabase.public.ai_runs.id`.
- Owner: `user_id` → `supabase.public.users.id`.
- Target (exactly one): `tailored_cv_id` → `supabase.public.tailored_cvs.id`
  or `master_cv_id` → `supabase.public.master_cvs.id`.
- Applied result: `supabase.public.cv_block_revisions.ai_suggestion_id` →
  `ai_suggestions.id` records revisions an accepted suggestion created.

## Reporting notes

- Acceptance rate = `applied` / all, by `action_type`.
- Filter on the set scope column before joining to the matching CV table to
  avoid null joins.

## Warnings

- `before_content`/`suggested_content` `type`/`fields` vocabularies are
  app-defined, **not DB-grounded** (same gap as CV content).
- `expired` suggestions were never acted on — exclude them from
  accept/reject-rate denominators if you want a decision rate.
