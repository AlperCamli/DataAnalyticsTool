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

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | Internal template id (FK target for CVs and exports). |
| 2 | `name` | `text` | false | — | — | Human-readable template name shown in the gallery. |
| 3 | `slug` | `text` | false | — | — | URL- and code-safe unique identifier used to look up the template. |
| 4 | `status` | `text` | false | — | — | Template lifecycle status; see body for grounding limits. |
| 5 | `preview_config` | `jsonb` | true | — | — | Renderer config for in-app previews as JSONB; structure in body. |
| 6 | `export_config` | `jsonb` | true | — | — | Renderer config for PDF/DOCX exports as JSONB; structure in body. |
| 7 | `created_at` | `timestamp with time zone` | false | `now()` | — | When the template record was created. |
| 8 | `updated_at` | `timestamp with time zone` | false | `now()` | — | When the template record was last updated. |
| 9 | `module_type` | `text` | false | `'standard'::text` | — | CV module family this template serves (standard vs medical); enum in body. |

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
