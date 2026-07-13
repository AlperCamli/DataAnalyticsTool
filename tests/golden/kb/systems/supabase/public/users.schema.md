---
doc_class: machine-object
object: supabase.public.users
kind: table
schema_hash: "sha256:6fa6f398726cb2d0a8d7c510c23e15068a567fab80a6bf144da2290c09ad3f54"
generated_at: 2026-07-11
source_mode: ddl-file
snapshot_version: "1"
status: machine
---

# `supabase.public.users`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.users` |
| Kind | table |
| Schema hash | `sha256:6fa6f398726cb2d0a8d7c510c23e15068a567fab80a6bf144da2290c09ad3f54` |

Registered accounts. Rows are soft-deleted via deleted_at.

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | — |
| 2 | `email` | `text` | false | — | Lowercased at the application layer; citext migration pending. | — |
| 3 | `full_name` | `text` | true | — | — | — |
| 4 | `created_at` | `timestamp with time zone` | false | `now()` | — | — |
| 5 | `deleted_at` | `timestamp with time zone` | true | — | Soft-delete marker; NULL means active. | — |

## Keys & indexes

Primary key: `id`

Foreign keys: —

Unique constraints:

- `email`

Indexes: —

## Row estimate & freshness

Row estimate: 5120

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

| Object | Via |
|---|---|
| [`supabase.public.orders`](orders.schema.md) | `user_id` |
