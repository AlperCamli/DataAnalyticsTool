---
doc_class: human-object
object: supabase.public.cv_templates
written_against_schema_hash: "sha256:ed76990d537238d6556cb9e39d4764401203b4840b8e831ecce4a4c9156d327c"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/cv_templates.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, referenced-by)"
depends_on:
  - supabase.public.cv_templates
  - supabase.public.master_cvs
  - supabase.public.tailored_cvs
  - supabase.public.exports
---

# `supabase.public.cv_templates` (human doc)

Template catalog referenced by CV documents and exports. Not
user-scoped — there is no `user_id` column; templates are global rows.
Structural facts are from [cv_templates.schema.md](cv_templates.schema.md).

## Grain

One row per `id` (primary key, `uuid`); `slug` is unique and NOT NULL,
so also one row per slug. No row estimate recorded in the 2026-07-12
snapshot.

## Columns with grounded notes

- `status` (`text`, NOT NULL): no default, no constraint — vocabulary
  undocumented (see PR gaps). It is indexed (`cv_templates_status_idx`),
  so the application filters on it; which value means "available to
  users" is not derivable from the schema.
- `preview_config` / `export_config` (`jsonb`, nullable): shapes
  undocumented.
- `module_type` (`text`, NOT NULL, default `'standard'`): same
  column/default as on `master_cvs`, `tailored_cvs`, and `imports`.

## Join guidance (from FKs)

Referenced by `master_cvs.template_id`, `tailored_cvs.template_id`, and
`exports.template_id` — all **nullable**: documents and exports can
exist without a template.

## Warnings

- Template usage counts must LEFT JOIN from the referencing tables;
  inner joins silently drop template-less documents.
