---
doc_class: human-object
object: supabase.public.cv_templates
written_against_schema_hash: "sha256:ed76990d537238d6556cb9e39d4764401203b4840b8e831ecce4a4c9156d327c"
status: draft
last_verified: null
purpose: "Catalog of CV templates available for preview rendering and export, identified by slug."
column_purposes:
  id: "Internal template id (FK target for CVs and exports)."
  name: "Human-readable template name shown in the gallery."
  slug: "URL- and code-safe unique identifier used to look up the template."
  status: "Template lifecycle status; see body for grounding limits."
  preview_config: "Renderer config for in-app previews as JSONB; structure in body."
  export_config: "Renderer config for PDF/DOCX exports as JSONB; structure in body."
  created_at: "When the template record was created."
  updated_at: "When the template record was last updated."
  module_type: "CV module family this template serves (standard vs medical); enum in body."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/cv_templates.md"
  - "app DDL: CV_Builder/backend/supabase/migrations/20260611120000_phase13_cv_modules.sql (module_type)"
  - "app DDL/seed: CV_Builder/backend/supabase/migrations (cv_templates preview_config/export_config seed rows)"
  - "app code: CV_Builder/backend/src (preview_config/export_config typed Record<string, unknown> | null)"
  - "machine doc: supabase.public.cv_templates"
depends_on:
  - supabase.public.master_cvs
  - supabase.public.tailored_cvs
  - supabase.public.exports
contamination: null
---

# `supabase.public.cv_templates`

## Grain

One row per selectable CV template, keyed by a unique `slug`. This is a small
shared catalog (no `user_id`) referenced by CVs and exports — not user data.
Seeded slugs include `modern-clean`, `minimal-professional`,
`executive-timeline`, `creative-portfolio`, `academic-classic`,
`tech-compact`, and `two-column-modern`.

## Column meanings & enum decodings

- `status` — lifecycle state indexed by `cv_templates_status_idx`. **No DB
  CHECK constrains it**; the only grounded value is `active` (customer-doc
  example). Treat the set as open — a named gap, do not assume closed.
- `module_type` — `standard` (default) or `medical_uk`, as elsewhere; scopes
  which module gallery the template appears in.
- `preview_config` (`jsonb`, nullable) — renderer config for in-app previews,
  typed `Record<string, unknown> | null` in code (an **open map**). Observed
  seed shapes carry a `preview` version tag and optional `theme`, e.g.
  `{"preview":"v1"}` or `{"preview":"v2","theme":"light"}`.
- `export_config` (`jsonb`, nullable) — renderer config for exports, open map.
  Observed seed shape gates each output format, e.g.
  `{"pdf":{"enabled":true},"docx":{"enabled":false}}`.

## Join guidance

No outbound FKs. Inbound: `supabase.public.master_cvs.template_id`,
`supabase.public.tailored_cvs.template_id`, and
`supabase.public.exports.template_id` all → `cv_templates.id` (each nullable —
a CV/export may have no template). Join on those to resolve a template name or
slug for reporting.

## Reporting notes

- Group CV/export usage by `cv_templates.slug` (stable) rather than `name`
  (display copy that can change).
- `preview_config`/`export_config` keys beyond the observed `preview`/`theme`
  and per-format `enabled` are app-defined — do not assume a fixed schema.

## Warnings

- `status` is not a DB enum (gap above).
- The template catalog is global; there is no per-user ownership or
  soft-delete column here.
