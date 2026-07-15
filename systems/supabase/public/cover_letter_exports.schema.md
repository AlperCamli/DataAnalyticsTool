---
doc_class: machine-object
object: supabase.public.cover_letter_exports
kind: table
schema_hash: "sha256:4e9e86056fbd97f3a527042842d3e3389b39640933860719b21e914712d85408"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.cover_letter_exports`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.cover_letter_exports` |
| Kind | table |
| Schema hash | `sha256:4e9e86056fbd97f3a527042842d3e3389b39640933860719b21e914712d85408` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | Internal cover letter export id. |
| 2 | `user_id` | `uuid` | false | — | — | Owning user that initiated the export (FK to users.id). |
| 3 | `cover_letter_id` | `uuid` | false | — | — | Cover letter being exported (FK to cover_letters.id). |
| 4 | `file_id` | `uuid` | true | — | — | Generated file artifact, populated when the export completes (FK to files.id). |
| 5 | `format` | `text` | false | — | — | Output format; enum in body. |
| 6 | `status` | `text` | false | — | — | Export lifecycle stage; enum in body. |
| 7 | `error_message` | `text` | true | — | — | Error description recorded when the export fails. |
| 8 | `created_at` | `timestamp with time zone` | false | `now()` | — | When the export was requested. |
| 9 | `completed_at` | `timestamp with time zone` | true | — | — | When the export reached a terminal state. |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `cover_letter_id` | [`public.cover_letters`](cover_letters.schema.md) | `id` |
| `file_id` | [`public.files`](files.schema.md) | `id` |
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints: —

Indexes:

- `CREATE INDEX cover_letter_exports_cover_letter_id_created_at_idx ON public.cover_letter_exports USING btree (cover_letter_id, created_at DESC)`
- `CREATE INDEX cover_letter_exports_status_created_at_idx ON public.cover_letter_exports USING btree (status, created_at DESC)`
- `CREATE INDEX cover_letter_exports_user_id_created_at_idx ON public.cover_letter_exports USING btree (user_id, created_at DESC)`

## Row estimate & freshness

Row estimate: —

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

—
