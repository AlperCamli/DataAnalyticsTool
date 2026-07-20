---
doc_class: machine-object
object: supabase.public.usage_counters
kind: table
schema_hash: "sha256:a4d5722f8765986984bc078fbbc2c86f5d61231eed158555f8036067509b7eee"
generated_at: 2026-07-20
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

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | Internal counter-row id. |
| 2 | `user_id` | `uuid` | false | — | — | User whose usage is tracked (FK to users.id). |
| 3 | `period_month` | `date` | false | — | — | First day of the calendar month this row covers. |
| 4 | `tailored_cv_generations_count` | `integer` | false | `0` | — | Tailored CV generations consumed in the period. |
| 5 | `exports_count` | `integer` | false | `0` | — | Export jobs completed in the period. |
| 6 | `ai_actions_count` | `integer` | false | `0` | — | AI block actions invoked in the period. |
| 7 | `storage_bytes_used` | `bigint` | false | `0` | — | Total bytes of files stored as of this period. |
| 8 | `updated_at` | `timestamp with time zone` | false | `now()` | — | When this counter was last incremented. |

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

Row estimate: 34

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

—
