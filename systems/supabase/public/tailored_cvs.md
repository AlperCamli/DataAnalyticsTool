---
doc_class: human-object
object: supabase.public.tailored_cvs
written_against_schema_hash: "sha256:401ae631f9f475a3cbc7c633a68fb3ff98ac5b2d57ab30dafebd271975e95945"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/tailored_cvs.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, row estimate, referenced-by)"
depends_on:
  - supabase.public.tailored_cvs
  - supabase.public.users
  - supabase.public.master_cvs
  - supabase.public.jobs
  - supabase.public.cv_templates
  - supabase.public.ai_runs
  - supabase.public.ai_suggestions
  - supabase.public.cover_letters
  - supabase.public.cv_block_revisions
  - supabase.public.exports
---

# `supabase.public.tailored_cvs` (human doc)

A CV derived from a master CV (`master_cv_id` NOT NULL), optionally
attached to a job. `current_content` (`jsonb`, NOT NULL) holds the
document body. Structural facts are from
[tailored_cvs.schema.md](tailored_cvs.schema.md).

## Grain

One row per `id` (primary key, `uuid`). Partial unique index
`tailored_cvs_unique_job_active_idx` (`job_id` unique WHERE `job_id IS
NOT NULL AND is_deleted = false`): **at most one non-deleted tailored CV
per job**. Deleted rows are exempt, so a job can have several
`is_deleted = true` tailored CVs plus one active. Snapshot row
estimate: 86 (2026-07-12).

## Status columns — what is actually decodable

- `status` (`text`, NOT NULL, default `'draft'`): only `'draft'` is
  attested by the schema; full vocabulary undocumented (see PR gaps).
- `ai_generation_status` (`text`, **nullable**, no default): vocabulary
  entirely undocumented; NULL's meaning (never generated? not
  applicable?) undocumented.
- `last_exported_at` (nullable timestamp): set/updated by an export
  path the schema does not describe; see
  [exports.schema.md](exports.schema.md) for the export job table.

## Join guidance (from FKs)

- `user_id` → `users.id` (NOT NULL); `master_cv_id` → `master_cvs.id`
  (NOT NULL); `job_id` → `jobs.id` (nullable); `template_id` →
  `cv_templates.id` (nullable).
- Referenced by: `jobs.tailored_cv_id`, `cover_letters.tailored_cv_id`,
  `exports.tailored_cv_id`, `ai_runs.tailored_cv_id`,
  `ai_suggestions.tailored_cv_id`, `cv_block_revisions.tailored_cv_id`.

## Warnings

- The job link exists in both directions (`tailored_cvs.job_id` and
  `jobs.tailored_cv_id`, each independently nullable and
  partial-unique); the schema does not state which is authoritative —
  see the same warning in [jobs.md](jobs.md).
- "Tailored CVs per job/user" counts depend on the `is_deleted` filter;
  the uniqueness guarantee above only holds for the non-deleted
  population.
