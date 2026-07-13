---
doc_class: human-object
object: supabase.public.master_cvs
written_against_schema_hash: "sha256:fedbafc33b7a23d0b1fb9c4f646ca486df3265d32a686385ccfbc2790c6de177"
status: draft
last_verified: null
purpose: "A user's authoritative master CV holding the canonical content that tailored variants are generated from."
column_purposes:
  id: "Internal master CV id."
  user_id: "Owning user (FK to users.id)."
  title: "Human-readable title for the master CV."
  language: "Language code of the CV content."
  template_id: "Template selected for previewing this CV (FK to cv_templates.id)."
  current_content: "Canonical structured CV content as JSONB; structure in body."
  summary_text: "Plain-text summary derived from content for search and AI context."
  source_type: "How the CV was created; enum decoded in body."
  is_deleted: "Soft-delete flag hiding this CV from active lists."
  created_at: "When the master CV was created."
  updated_at: "When the master CV was last updated."
  module_type: "CV module family (standard vs medical); enum decoded in body."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/master_cvs.md"
  - "app DDL: CV_Builder/backend/supabase/migrations/20260417133000_phase2_cv_domains.sql (master_cvs_source_type_check)"
  - "app DDL: CV_Builder/backend/supabase/migrations/20260611120000_phase13_cv_modules.sql (module_type)"
  - "app code: CV_Builder/backend/src/shared/cv-content/cv-content.types.ts (CvContent)"
  - "machine doc: supabase.public.master_cvs"
depends_on:
  - supabase.public.users
  - supabase.public.cv_templates
  - supabase.public.tailored_cvs
contamination: null
---

# `supabase.public.master_cvs`

## Grain

One row per master CV. A user may own several (`row_estimate` ≈ 106 across all
users). `is_deleted = true` rows are soft-deleted and must be filtered out of
active-CV counts (index `master_cvs_user_id_is_deleted_idx` backs that filter).

## Column meanings & enum decodings

- `source_type` — DB-constrained to **`scratch` | `import`**
  (`master_cvs_source_type_check`): built from blank vs seeded from an
  imported source CV (see `imports`).
- `module_type` — CV module family, default **`standard`**; the other known
  value is **`medical_uk`** (UK medical CV module). No DB CHECK constrains it,
  so treat the set as app-governed, not closed.
- `current_content` (`jsonb`, non-null) — the canonical CV document, typed
  `CvContent` in application code. Shape:
  ```json
  {
    "version": "v1",
    "language": "en",
    "metadata": {},
    "sections": [
      {
        "id": "…", "type": "…", "title": "…|null", "order": 0,
        "meta": {},
        "blocks": [
          { "id": "…", "type": "…", "order": 0,
            "visibility": "visible|hidden",
            "fields": {}, "meta": {} }
        ]
      }
    ]
  }
  ```
  `sections[]` hold ordered `blocks[]`; each block has a free-form `type`,
  a `fields` map, and `visibility` of `visible`/`hidden`. `metadata`,
  section `meta`, and block `fields`/`meta` are open JSON maps (block/section
  `type` vocabularies are app-defined — not enumerated here).

## Join guidance

- Owner: `master_cvs.user_id` → `supabase.public.users.id`.
- Template: `master_cvs.template_id` → `supabase.public.cv_templates.id`
  (nullable — a CV may have no template selected).
- Variants: `supabase.public.tailored_cvs.master_cv_id` → `master_cvs.id`
  (one master fans out to many tailored CVs).

## Reporting notes

- Always filter `is_deleted = false` for "active master CVs".
- Prefer `summary_text` over parsing `current_content` for lightweight
  text/search reporting.

## Warnings

- `current_content` block/section `type` values and `fields` keys are
  **app-defined and not grounded in the DB** — a named gap for any report
  that reaches inside the JSON.
- `language` here and inside `current_content.language` are stored
  independently; they can drift.
