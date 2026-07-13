---
doc_class: machine-object
object: supabase.public.users
kind: table
schema_hash: "sha256:aefee2abaca5b3f73bf8062903148200a7e8c5df3240b632e65586a1324fdd58"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.users`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.users` |
| Kind | table |
| Schema hash | `sha256:aefee2abaca5b3f73bf8062903148200a7e8c5df3240b632e65586a1324fdd58` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | — |
| 2 | `auth_user_id` | `uuid` | false | — | — | — |
| 3 | `email` | `text` | false | — | — | — |
| 4 | `full_name` | `text` | true | — | — | — |
| 5 | `locale` | `text` | false | `'en'::text` | — | — |
| 6 | `default_cv_language` | `text` | true | — | — | — |
| 7 | `onboarding_completed` | `boolean` | false | `false` | — | — |
| 8 | `created_at` | `timestamp with time zone` | false | `now()` | — | — |
| 9 | `updated_at` | `timestamp with time zone` | false | `now()` | — | — |
| 10 | `onboarding_state` | `jsonb` | false | `'{}'::jsonb` | — | — |

## Keys & indexes

Primary key: `id`

Foreign keys: —

Unique constraints:

- `auth_user_id`

Indexes: —

## Row estimate & freshness

Row estimate: —

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

| Object | Via |
|---|---|
| [`supabase.public.ai_runs`](ai_runs.schema.md) | `user_id` |
| [`supabase.public.ai_suggestions`](ai_suggestions.schema.md) | `user_id` |
| [`supabase.public.cover_letter_exports`](cover_letter_exports.schema.md) | `user_id` |
| [`supabase.public.cover_letters`](cover_letters.schema.md) | `user_id` |
| [`supabase.public.cv_block_revisions`](cv_block_revisions.schema.md) | `created_by_user_id` |
| [`supabase.public.cv_block_revisions`](cv_block_revisions.schema.md) | `user_id` |
| [`supabase.public.exports`](exports.schema.md) | `user_id` |
| [`supabase.public.files`](files.schema.md) | `user_id` |
| [`supabase.public.imports`](imports.schema.md) | `user_id` |
| [`supabase.public.job_status_history`](job_status_history.schema.md) | `changed_by_user_id` |
| [`supabase.public.jobs`](jobs.schema.md) | `user_id` |
| [`supabase.public.master_cvs`](master_cvs.schema.md) | `user_id` |
| [`supabase.public.subscriptions`](subscriptions.schema.md) | `user_id` |
| [`supabase.public.tailored_cvs`](tailored_cvs.schema.md) | `user_id` |
| [`supabase.public.usage_counters`](usage_counters.schema.md) | `user_id` |
