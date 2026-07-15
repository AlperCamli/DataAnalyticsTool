---
doc_class: machine-object
object: supabase.public.ai_suggestions
kind: table
schema_hash: "sha256:c326f46f6e3edfd4eb7ab7a81bbc17869a290886d0c8d10fd5e52f32556c605d"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.ai_suggestions`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.ai_suggestions` |
| Kind | table |
| Schema hash | `sha256:c326f46f6e3edfd4eb7ab7a81bbc17869a290886d0c8d10fd5e52f32556c605d` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | — |
| 2 | `ai_run_id` | `uuid` | false | — | — | — |
| 3 | `user_id` | `uuid` | false | — | — | — |
| 4 | `tailored_cv_id` | `uuid` | true | — | — | — |
| 5 | `block_id` | `text` | true | — | — | — |
| 6 | `action_type` | `text` | false | — | — | — |
| 7 | `before_content` | `jsonb` | true | — | — | — |
| 8 | `suggested_content` | `jsonb` | false | — | — | — |
| 9 | `option_group_key` | `text` | true | — | — | — |
| 10 | `status` | `text` | false | `'pending'::text` | — | — |
| 11 | `applied_at` | `timestamp with time zone` | true | — | — | — |
| 12 | `created_at` | `timestamp with time zone` | false | `now()` | — | — |
| 13 | `master_cv_id` | `uuid` | true | — | — | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `ai_run_id` | [`public.ai_runs`](ai_runs.schema.md) | `id` |
| `master_cv_id` | [`public.master_cvs`](master_cvs.schema.md) | `id` |
| `tailored_cv_id` | [`public.tailored_cvs`](tailored_cvs.schema.md) | `id` |
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints: —

Indexes:

- `CREATE INDEX ai_suggestions_ai_run_id_idx ON public.ai_suggestions USING btree (ai_run_id)`
- `CREATE INDEX ai_suggestions_master_block_status_idx ON public.ai_suggestions USING btree (master_cv_id, block_id, status, created_at DESC) WHERE ((master_cv_id IS NOT NULL) AND (block_id IS NOT NULL))`
- `CREATE INDEX ai_suggestions_master_status_idx ON public.ai_suggestions USING btree (master_cv_id, status, created_at DESC) WHERE (master_cv_id IS NOT NULL)`
- `CREATE INDEX ai_suggestions_option_group_idx ON public.ai_suggestions USING btree (option_group_key) WHERE (option_group_key IS NOT NULL)`
- `CREATE INDEX ai_suggestions_tailored_block_status_idx ON public.ai_suggestions USING btree (tailored_cv_id, block_id, status, created_at DESC) WHERE ((tailored_cv_id IS NOT NULL) AND (block_id IS NOT NULL))`
- `CREATE INDEX ai_suggestions_tailored_status_idx ON public.ai_suggestions USING btree (tailored_cv_id, status, created_at DESC)`
- `CREATE INDEX ai_suggestions_user_created_at_idx ON public.ai_suggestions USING btree (user_id, created_at DESC)`

## Row estimate & freshness

Row estimate: 30

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

| Object | Via |
|---|---|
| [`supabase.public.cv_block_revisions`](cv_block_revisions.schema.md) | `ai_suggestion_id` |
