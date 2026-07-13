---
doc_class: machine-object
object: supabase.public.usage_counters
kind: table
schema_hash: "sha256:a4d5722f8765986984bc078fbbc2c86f5d61231eed158555f8036067509b7eee"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.usage_counters`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.usage_counters` |
| Kind | table |
| Schema hash | `sha256:a4d5722f8765986984bc078fbbc2c86f5d61231eed158555f8036067509b7eee` |

## Columns

| # | Column | Type | Nullable | Default | Description |
|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — |
| 2 | `user_id` | `uuid` | false | — | — |
| 3 | `period_month` | `date` | false | — | — |
| 4 | `tailored_cv_generations_count` | `integer` | false | `0` | — |
| 5 | `exports_count` | `integer` | false | `0` | — |
| 6 | `ai_actions_count` | `integer` | false | `0` | — |
| 7 | `storage_bytes_used` | `bigint` | false | `0` | — |
| 8 | `updated_at` | `timestamp with time zone` | false | `now()` | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints:

- `user_id`, `period_month`

Indexes:

- `CREATE INDEX usage_counters_period_month_idx ON public.usage_counters USING btree (period_month)`
- `CREATE INDEX usage_counters_user_id_idx ON public.usage_counters USING btree (user_id)`

## Row estimate & freshness

Row estimate: 33

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

—
