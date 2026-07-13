---
doc_class: machine-object
object: supabase.public.tailored_cvs
kind: table
schema_hash: "sha256:401ae631f9f475a3cbc7c633a68fb3ff98ac5b2d57ab30dafebd271975e95945"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.tailored_cvs`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.tailored_cvs` |
| Kind | table |
| Schema hash | `sha256:401ae631f9f475a3cbc7c633a68fb3ff98ac5b2d57ab30dafebd271975e95945` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | — |
| 2 | `user_id` | `uuid` | false | — | — | — |
| 3 | `master_cv_id` | `uuid` | false | — | — | — |
| 4 | `job_id` | `uuid` | true | — | — | — |
| 5 | `title` | `text` | false | — | — | — |
| 6 | `language` | `text` | false | — | — | — |
| 7 | `template_id` | `uuid` | true | — | — | — |
| 8 | `current_content` | `jsonb` | false | — | — | — |
| 9 | `status` | `text` | false | `'draft'::text` | — | — |
| 10 | `ai_generation_status` | `text` | true | — | — | — |
| 11 | `last_exported_at` | `timestamp with time zone` | true | — | — | — |
| 12 | `is_deleted` | `boolean` | false | `false` | — | — |
| 13 | `created_at` | `timestamp with time zone` | false | `now()` | — | — |
| 14 | `updated_at` | `timestamp with time zone` | false | `now()` | — | — |
| 15 | `module_type` | `text` | false | `'standard'::text` | — | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `job_id` | [`public.jobs`](jobs.schema.md) | `id` |
| `master_cv_id` | [`public.master_cvs`](master_cvs.schema.md) | `id` |
| `template_id` | [`public.cv_templates`](cv_templates.schema.md) | `id` |
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints: —

Indexes:

- `CREATE INDEX tailored_cvs_job_id_idx ON public.tailored_cvs USING btree (job_id)`
- `CREATE INDEX tailored_cvs_master_cv_id_idx ON public.tailored_cvs USING btree (master_cv_id)`
- `CREATE INDEX tailored_cvs_status_idx ON public.tailored_cvs USING btree (status)`
- `CREATE INDEX tailored_cvs_user_id_is_deleted_idx ON public.tailored_cvs USING btree (user_id, is_deleted)`
- `CREATE UNIQUE INDEX tailored_cvs_unique_job_active_idx ON public.tailored_cvs USING btree (job_id) WHERE ((job_id IS NOT NULL) AND (is_deleted = false))`

## Row estimate & freshness

Row estimate: 86

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

| Object | Via |
|---|---|
| [`supabase.public.ai_runs`](ai_runs.schema.md) | `tailored_cv_id` |
| [`supabase.public.ai_suggestions`](ai_suggestions.schema.md) | `tailored_cv_id` |
| [`supabase.public.cover_letters`](cover_letters.schema.md) | `tailored_cv_id` |
| [`supabase.public.cv_block_revisions`](cv_block_revisions.schema.md) | `tailored_cv_id` |
| [`supabase.public.exports`](exports.schema.md) | `tailored_cv_id` |
| [`supabase.public.jobs`](jobs.schema.md) | `tailored_cv_id` |
