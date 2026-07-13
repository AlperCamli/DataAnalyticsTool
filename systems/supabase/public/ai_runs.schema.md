---
doc_class: machine-object
object: supabase.public.ai_runs
kind: table
schema_hash: "sha256:1371cc0551146b3167888b67d16ddbf8c054f90222a4cb07b3312d9a18a89497"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.ai_runs`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.ai_runs` |
| Kind | table |
| Schema hash | `sha256:1371cc0551146b3167888b67d16ddbf8c054f90222a4cb07b3312d9a18a89497` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | — |
| 2 | `user_id` | `uuid` | false | — | — | — |
| 3 | `master_cv_id` | `uuid` | true | — | — | — |
| 4 | `tailored_cv_id` | `uuid` | true | — | — | — |
| 5 | `job_id` | `uuid` | true | — | — | — |
| 6 | `flow_type` | `text` | false | — | — | — |
| 7 | `provider` | `text` | false | — | — | — |
| 8 | `model_name` | `text` | false | — | — | — |
| 9 | `status` | `text` | false | — | — | — |
| 10 | `input_payload` | `jsonb` | false | — | — | — |
| 11 | `output_payload` | `jsonb` | true | — | — | — |
| 12 | `error_message` | `text` | true | — | — | — |
| 13 | `started_at` | `timestamp with time zone` | false | `now()` | — | — |
| 14 | `completed_at` | `timestamp with time zone` | true | — | — | — |
| 15 | `progress_stage` | `text` | false | `'queued'::text` | — | — |
| 16 | `debug_payload` | `jsonb` | true | — | — | — |
| 17 | `input_tokens` | `integer` | true | — | — | — |
| 18 | `output_tokens` | `integer` | true | — | — | — |
| 19 | `total_tokens` | `integer` | true | — | — | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `job_id` | [`public.jobs`](jobs.schema.md) | `id` |
| `master_cv_id` | [`public.master_cvs`](master_cvs.schema.md) | `id` |
| `tailored_cv_id` | [`public.tailored_cvs`](tailored_cvs.schema.md) | `id` |
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints: —

Indexes:

- `CREATE INDEX ai_runs_flow_type_status_idx ON public.ai_runs USING btree (flow_type, status)`
- `CREATE INDEX ai_runs_job_started_at_idx ON public.ai_runs USING btree (job_id, started_at DESC) WHERE (job_id IS NOT NULL)`
- `CREATE INDEX ai_runs_tailored_cv_started_at_idx ON public.ai_runs USING btree (tailored_cv_id, started_at DESC) WHERE (tailored_cv_id IS NOT NULL)`
- `CREATE INDEX ai_runs_user_started_at_idx ON public.ai_runs USING btree (user_id, started_at DESC)`
- `CREATE INDEX ai_runs_user_status_progress_idx ON public.ai_runs USING btree (user_id, status, progress_stage, started_at DESC)`

## Row estimate & freshness

Row estimate: 518

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

| Object | Via |
|---|---|
| [`supabase.public.ai_suggestions`](ai_suggestions.schema.md) | `ai_run_id` |
