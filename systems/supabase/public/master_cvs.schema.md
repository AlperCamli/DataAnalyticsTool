---
doc_class: machine-object
object: supabase.public.master_cvs
kind: table
schema_hash: "sha256:fedbafc33b7a23d0b1fb9c4f646ca486df3265d32a686385ccfbc2790c6de177"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.master_cvs`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.master_cvs` |
| Kind | table |
| Schema hash | `sha256:fedbafc33b7a23d0b1fb9c4f646ca486df3265d32a686385ccfbc2790c6de177` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | Internal master CV id. |
| 2 | `user_id` | `uuid` | false | — | — | Owning user (FK to users.id). |
| 3 | `title` | `text` | false | — | — | Human-readable title for the master CV. |
| 4 | `language` | `text` | false | — | — | Language code of the CV content. |
| 5 | `template_id` | `uuid` | true | — | — | Template selected for previewing this CV (FK to cv_templates.id). |
| 6 | `current_content` | `jsonb` | false | — | — | Canonical structured CV content as JSONB; structure in body. |
| 7 | `summary_text` | `text` | true | — | — | Plain-text summary derived from content for search and AI context. |
| 8 | `source_type` | `text` | false | — | — | How the CV was created; enum decoded in body. |
| 9 | `is_deleted` | `boolean` | false | `false` | — | Soft-delete flag hiding this CV from active lists. |
| 10 | `created_at` | `timestamp with time zone` | false | `now()` | — | When the master CV was created. |
| 11 | `updated_at` | `timestamp with time zone` | false | `now()` | — | When the master CV was last updated. |
| 12 | `module_type` | `text` | false | `'standard'::text` | — | CV module family (standard vs medical); enum decoded in body. |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `template_id` | [`public.cv_templates`](cv_templates.schema.md) | `id` |
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints: —

Indexes:

- `CREATE INDEX master_cvs_template_id_idx ON public.master_cvs USING btree (template_id)`
- `CREATE INDEX master_cvs_updated_at_idx ON public.master_cvs USING btree (updated_at DESC)`
- `CREATE INDEX master_cvs_user_id_is_deleted_idx ON public.master_cvs USING btree (user_id, is_deleted)`

## Row estimate & freshness

Row estimate: 106

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

| Object | Via |
|---|---|
| [`supabase.public.ai_runs`](ai_runs.schema.md) | `master_cv_id` |
| [`supabase.public.ai_suggestions`](ai_suggestions.schema.md) | `master_cv_id` |
| [`supabase.public.cv_block_revisions`](cv_block_revisions.schema.md) | `master_cv_id` |
| [`supabase.public.exports`](exports.schema.md) | `master_cv_id` |
| [`supabase.public.imports`](imports.schema.md) | `target_master_cv_id` |
| [`supabase.public.tailored_cvs`](tailored_cvs.schema.md) | `master_cv_id` |
