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
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | Internal tailored CV id. |
| 2 | `user_id` | `uuid` | false | — | — | Owning user (FK to users.id). |
| 3 | `master_cv_id` | `uuid` | false | — | — | Master CV this variant was derived from (FK to master_cvs.id). |
| 4 | `job_id` | `uuid` | true | — | — | Job this variant targets, if linked (FK to jobs.id). |
| 5 | `title` | `text` | false | — | — | Human-readable title for the tailored CV. |
| 6 | `language` | `text` | false | — | — | Language code of the tailored CV content. |
| 7 | `template_id` | `uuid` | true | — | — | Template selected for previewing this CV (FK to cv_templates.id). |
| 8 | `current_content` | `jsonb` | false | — | — | Canonical structured CV content as JSONB; structure in master_cvs body. |
| 9 | `status` | `text` | false | `'draft'::text` | — | Lifecycle stage of the tailored CV; enum decoded in body. |
| 10 | `ai_generation_status` | `text` | true | — | — | Status of the most recent AI tailoring run; enum decoded in body. |
| 11 | `last_exported_at` | `timestamp with time zone` | true | — | — | When this tailored CV was most recently exported. |
| 12 | `is_deleted` | `boolean` | false | `false` | — | Soft-delete flag hiding this CV from active lists. |
| 13 | `created_at` | `timestamp with time zone` | false | `now()` | — | When the tailored CV was created. |
| 14 | `updated_at` | `timestamp with time zone` | false | `now()` | — | When the tailored CV was last updated. |
| 15 | `module_type` | `text` | false | `'standard'::text` | — | CV module family (standard vs medical); enum decoded in master_cvs body. |

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
