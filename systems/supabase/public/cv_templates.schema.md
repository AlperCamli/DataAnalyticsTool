---
doc_class: machine-object
object: supabase.public.cv_templates
kind: table
schema_hash: "sha256:ed76990d537238d6556cb9e39d4764401203b4840b8e831ecce4a4c9156d327c"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.cv_templates`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.cv_templates` |
| Kind | table |
| Schema hash | `sha256:ed76990d537238d6556cb9e39d4764401203b4840b8e831ecce4a4c9156d327c` |

## Columns

| # | Column | Type | Nullable | Default | Description |
|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — |
| 2 | `name` | `text` | false | — | — |
| 3 | `slug` | `text` | false | — | — |
| 4 | `status` | `text` | false | — | — |
| 5 | `preview_config` | `jsonb` | true | — | — |
| 6 | `export_config` | `jsonb` | true | — | — |
| 7 | `created_at` | `timestamp with time zone` | false | `now()` | — |
| 8 | `updated_at` | `timestamp with time zone` | false | `now()` | — |
| 9 | `module_type` | `text` | false | `'standard'::text` | — |

## Keys & indexes

Primary key: `id`

Foreign keys: —

Unique constraints:

- `slug`

Indexes:

- `CREATE INDEX cv_templates_status_idx ON public.cv_templates USING btree (status)`

## Row estimate & freshness

Row estimate: —

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

| Object | Via |
|---|---|
| [`supabase.public.exports`](exports.schema.md) | `template_id` |
| [`supabase.public.master_cvs`](master_cvs.schema.md) | `template_id` |
| [`supabase.public.tailored_cvs`](tailored_cvs.schema.md) | `template_id` |
