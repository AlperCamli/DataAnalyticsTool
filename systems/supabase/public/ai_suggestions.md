---
doc_class: human-object
object: supabase.public.ai_suggestions
written_against_schema_hash: "sha256:c326f46f6e3edfd4eb7ab7a81bbc17869a290886d0c8d10fd5e52f32556c605d"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/ai_suggestions.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, row estimate, referenced-by)"
depends_on:
  - supabase.public.ai_suggestions
  - supabase.public.ai_runs
  - supabase.public.users
  - supabase.public.master_cvs
  - supabase.public.tailored_cvs
  - supabase.public.cv_block_revisions
---

# `supabase.public.ai_suggestions` (human doc)

Individual suggestions produced by AI runs: each row belongs to exactly
one run (`ai_run_id` NOT NULL) and carries `suggested_content` (`jsonb`,
NOT NULL), optional `before_content`, an `action_type`, and a `status`
with optional `applied_at`. Structural facts are from
[ai_suggestions.schema.md](ai_suggestions.schema.md).

## Grain

One row per `id` (primary key, `uuid`) — one suggestion; a run may have
many (no unique constraint on `ai_run_id`). Snapshot row estimate: 30
(2026-07-12).

## Columns with grounded notes

- `status` (`text`, NOT NULL, default `'pending'`): only `'pending'` is
  attested; the accepted/rejected-style vocabulary is undocumented (see
  PR gaps). `applied_at` (nullable) records a time, but which status
  values it accompanies is undocumented.
- `master_cv_id` and `tailored_cv_id` are both nullable; the partial
  indexes cover both shapes and no CHECK enforces exactly-one-of.
- `block_id` (`text`, nullable): same undocumented block model as
  `cv_block_revisions.block_id`; a NULL `block_id`'s meaning
  (document-level suggestion?) is undocumented.
- `option_group_key` (`text`, nullable, partial-indexed): grouping
  semantics undocumented — plausibly alternatives from one generation,
  but that is not attested (see PR gaps).
- `action_type` (`text`, NOT NULL): vocabulary undocumented; note
  `ai_prompt_configs.action_type` shares the name with no FK.

## Join guidance (from FKs)

`ai_run_id` → `ai_runs.id` (NOT NULL); `user_id` → `users.id`
(NOT NULL); `master_cv_id` → `master_cvs.id`; `tailored_cv_id` →
`tailored_cvs.id` (both nullable). Referenced by
`cv_block_revisions.ai_suggestion_id` (nullable there) — an applied
suggestion can be traced into revision history when that link is set.

## Warnings

- Acceptance-rate style metrics need the `status` vocabulary; with only
  `'pending'` attested, `applied_at IS NOT NULL` is the only
  schema-visible signal of application, and its exact semantics are
  unverified.
