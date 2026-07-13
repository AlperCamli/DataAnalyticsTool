---
doc_class: machine-object
object: supabase.public.job_status_history
kind: table
schema_hash: "sha256:797056ddeef9e10c86890f5cf5a04d894fb0ed069b01b8bbfeb0332d230a8d5a"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.job_status_history`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.job_status_history` |
| Kind | table |
| Schema hash | `sha256:797056ddeef9e10c86890f5cf5a04d894fb0ed069b01b8bbfeb0332d230a8d5a` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | — |
| 2 | `job_id` | `uuid` | false | — | — | — |
| 3 | `from_status` | `text` | true | — | — | — |
| 4 | `to_status` | `text` | false | — | — | — |
| 5 | `changed_at` | `timestamp with time zone` | false | `now()` | — | — |
| 6 | `changed_by_user_id` | `uuid` | false | — | — | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `changed_by_user_id` | [`public.users`](users.schema.md) | `id` |
| `job_id` | [`public.jobs`](jobs.schema.md) | `id` |

Unique constraints: —

Indexes:

- `CREATE INDEX job_status_history_changed_by_user_id_idx ON public.job_status_history USING btree (changed_by_user_id, changed_at DESC)`
- `CREATE INDEX job_status_history_job_id_changed_at_idx ON public.job_status_history USING btree (job_id, changed_at DESC)`

## Row estimate & freshness

Row estimate: —

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

—
