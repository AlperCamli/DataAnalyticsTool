---
doc_class: machine-object
object: supabase.public.jobs
kind: table
schema_hash: "sha256:36740df1f02513714bd57afb0300ba30312d43cc18c774d1ea5c39703a1f24aa"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.jobs`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.jobs` |
| Kind | table |
| Schema hash | `sha256:36740df1f02513714bd57afb0300ba30312d43cc18c774d1ea5c39703a1f24aa` |

## Columns

| # | Column | Type | Nullable | Default | Description |
|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — |
| 2 | `user_id` | `uuid` | false | — | — |
| 3 | `tailored_cv_id` | `uuid` | true | — | — |
| 4 | `company_name` | `text` | false | — | — |
| 5 | `job_title` | `text` | false | — | — |
| 6 | `job_description` | `text` | false | — | — |
| 7 | `job_posting_url` | `text` | true | — | — |
| 8 | `location_text` | `text` | true | — | — |
| 9 | `status` | `text` | false | `'saved'::text` | — |
| 10 | `notes` | `text` | true | — | — |
| 11 | `applied_at` | `timestamp with time zone` | true | — | — |
| 12 | `created_at` | `timestamp with time zone` | false | `now()` | — |
| 13 | `updated_at` | `timestamp with time zone` | false | `now()` | — |
| 14 | `cover_letter_id` | `uuid` | true | — | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `cover_letter_id` | [`public.cover_letters`](cover_letters.schema.md) | `id` |
| `tailored_cv_id` | [`public.tailored_cvs`](tailored_cvs.schema.md) | `id` |
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints: —

Indexes:

- `CREATE INDEX jobs_company_name_idx ON public.jobs USING btree (company_name)`
- `CREATE INDEX jobs_status_idx ON public.jobs USING btree (status)`
- `CREATE INDEX jobs_tailored_cv_id_idx ON public.jobs USING btree (tailored_cv_id)`
- `CREATE INDEX jobs_user_id_idx ON public.jobs USING btree (user_id)`
- `CREATE UNIQUE INDEX jobs_unique_cover_letter_idx ON public.jobs USING btree (cover_letter_id) WHERE (cover_letter_id IS NOT NULL)`
- `CREATE UNIQUE INDEX jobs_unique_tailored_cv_idx ON public.jobs USING btree (tailored_cv_id) WHERE (tailored_cv_id IS NOT NULL)`

## Row estimate & freshness

Row estimate: 79

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

| Object | Via |
|---|---|
| [`supabase.public.ai_runs`](ai_runs.schema.md) | `job_id` |
| [`supabase.public.cover_letters`](cover_letters.schema.md) | `job_id` |
| [`supabase.public.job_status_history`](job_status_history.schema.md) | `job_id` |
| [`supabase.public.tailored_cvs`](tailored_cvs.schema.md) | `job_id` |
