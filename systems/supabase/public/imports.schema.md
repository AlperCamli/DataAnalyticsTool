---
doc_class: machine-object
object: supabase.public.imports
kind: table
schema_hash: "sha256:637c57a9477ce54183d6f23df56a09c439bdf16333457573c081240d565ac026"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.imports`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.imports` |
| Kind | table |
| Schema hash | `sha256:637c57a9477ce54183d6f23df56a09c439bdf16333457573c081240d565ac026` |

## Columns

| # | Column | Type | Nullable | Default | Description |
|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — |
| 2 | `user_id` | `uuid` | false | — | — |
| 3 | `source_file_id` | `uuid` | false | — | — |
| 4 | `target_master_cv_id` | `uuid` | true | — | — |
| 5 | `status` | `text` | false | — | — |
| 6 | `parser_name` | `text` | true | — | — |
| 7 | `raw_extracted_text` | `text` | true | — | — |
| 8 | `parsed_content` | `jsonb` | true | — | — |
| 9 | `error_message` | `text` | true | — | — |
| 10 | `created_at` | `timestamp with time zone` | false | `now()` | — |
| 11 | `updated_at` | `timestamp with time zone` | false | `now()` | — |
| 12 | `module_type` | `text` | false | `'standard'::text` | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `source_file_id` | [`public.files`](files.schema.md) | `id` |
| `target_master_cv_id` | [`public.master_cvs`](master_cvs.schema.md) | `id` |
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints: —

Indexes:

- `CREATE INDEX imports_source_file_id_idx ON public.imports USING btree (source_file_id)`
- `CREATE INDEX imports_target_master_cv_id_idx ON public.imports USING btree (target_master_cv_id)`
- `CREATE INDEX imports_user_id_status_idx ON public.imports USING btree (user_id, status)`

## Row estimate & freshness

Row estimate: 87

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

—
