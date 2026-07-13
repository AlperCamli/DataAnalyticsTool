---
doc_class: machine-object
object: supabase.public.cover_letters
kind: table
schema_hash: "sha256:26b706a8ef1a9b3285da73e84f0bb741a8df3f659935ff82d893594b29e37a35"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.cover_letters`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.cover_letters` |
| Kind | table |
| Schema hash | `sha256:26b706a8ef1a9b3285da73e84f0bb741a8df3f659935ff82d893594b29e37a35` |

## Columns

| # | Column | Type | Nullable | Default | Description |
|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — |
| 2 | `user_id` | `uuid` | false | — | — |
| 3 | `job_id` | `uuid` | false | — | — |
| 4 | `tailored_cv_id` | `uuid` | true | — | — |
| 5 | `title` | `text` | false | — | — |
| 6 | `content` | `text` | false | `''::text` | — |
| 7 | `status` | `text` | false | `'draft'::text` | — |
| 8 | `last_exported_at` | `timestamp with time zone` | true | — | — |
| 9 | `created_at` | `timestamp with time zone` | false | `now()` | — |
| 10 | `updated_at` | `timestamp with time zone` | false | `now()` | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `job_id` | [`public.jobs`](jobs.schema.md) | `id` |
| `tailored_cv_id` | [`public.tailored_cvs`](tailored_cvs.schema.md) | `id` |
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints:

- `job_id`

Indexes:

- `CREATE INDEX cover_letters_tailored_cv_id_idx ON public.cover_letters USING btree (tailored_cv_id)`
- `CREATE INDEX cover_letters_user_id_updated_at_idx ON public.cover_letters USING btree (user_id, updated_at DESC)`

## Row estimate & freshness

Row estimate: 21

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

| Object | Via |
|---|---|
| [`supabase.public.cover_letter_exports`](cover_letter_exports.schema.md) | `cover_letter_id` |
| [`supabase.public.jobs`](jobs.schema.md) | `cover_letter_id` |
