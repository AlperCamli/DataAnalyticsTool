---
doc_class: machine-object
object: supabase.public.exports
kind: table
schema_hash: "sha256:ab7194cd6d3a1ed8af4c692f1183b3246f1f07c9e115f968bef9cb843f8a5290"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.exports`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.exports` |
| Kind | table |
| Schema hash | `sha256:ab7194cd6d3a1ed8af4c692f1183b3246f1f07c9e115f968bef9cb843f8a5290` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | — |
| 2 | `user_id` | `uuid` | false | — | — | — |
| 3 | `tailored_cv_id` | `uuid` | true | — | — | — |
| 4 | `file_id` | `uuid` | true | — | — | — |
| 5 | `format` | `text` | false | — | — | — |
| 6 | `status` | `text` | false | — | — | — |
| 7 | `template_id` | `uuid` | true | — | — | — |
| 8 | `error_message` | `text` | true | — | — | — |
| 9 | `created_at` | `timestamp with time zone` | false | `now()` | — | — |
| 10 | `completed_at` | `timestamp with time zone` | true | — | — | — |
| 11 | `master_cv_id` | `uuid` | true | — | — | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `file_id` | [`public.files`](files.schema.md) | `id` |
| `master_cv_id` | [`public.master_cvs`](master_cvs.schema.md) | `id` |
| `tailored_cv_id` | [`public.tailored_cvs`](tailored_cvs.schema.md) | `id` |
| `template_id` | [`public.cv_templates`](cv_templates.schema.md) | `id` |
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints: —

Indexes:

- `CREATE INDEX exports_master_cv_id_created_at_idx ON public.exports USING btree (master_cv_id, created_at DESC) WHERE (master_cv_id IS NOT NULL)`
- `CREATE INDEX exports_status_created_at_idx ON public.exports USING btree (status, created_at DESC)`
- `CREATE INDEX exports_tailored_cv_id_created_at_idx ON public.exports USING btree (tailored_cv_id, created_at DESC)`
- `CREATE INDEX exports_user_id_created_at_idx ON public.exports USING btree (user_id, created_at DESC)`

## Row estimate & freshness

Row estimate: 177

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

—
