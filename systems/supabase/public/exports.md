---
doc_class: human-object
object: supabase.public.exports
written_against_schema_hash: "sha256:ab7194cd6d3a1ed8af4c692f1183b3246f1f07c9e115f968bef9cb843f8a5290"
status: draft
last_verified: null
purpose: "Export job records for rendering a tailored CV or master CV into a downloadable PDF or DOCX artifact."
column_purposes:
  id: "Internal export id."
  user_id: "User that initiated the export (FK to users.id)."
  tailored_cv_id: "Tailored CV being exported, when scope is tailored (FK)."
  file_id: "Generated file artifact, populated when the export completes (FK to files.id)."
  format: "Output format; enum in body."
  status: "Export lifecycle stage; enum in body."
  template_id: "Template used to render this export (FK to cv_templates.id)."
  error_message: "Error description recorded when the export fails."
  created_at: "When the export was requested."
  completed_at: "When the export reached a terminal state."
  master_cv_id: "Master CV being exported, when scope is master (FK)."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/exports.md"
  - "app DDL: CV_Builder/backend/supabase/migrations (exports_format_check, exports_status_check, scope + lifecycle checks)"
  - "machine doc: supabase.public.exports"
depends_on:
  - supabase.public.users
  - supabase.public.tailored_cvs
  - supabase.public.master_cvs
  - supabase.public.files
  - supabase.public.cv_templates
contamination: null
---

# `supabase.public.exports`

## Grain

One row per CV export attempt. A scope CHECK enforces **exactly one** of
`tailored_cv_id`/`master_cv_id` is set (this table covers both CV kinds; cover
letters use `supabase.public.cover_letter_exports`). Re-exports add rows.

## Column meanings & enum decodings

- `format` — DB-constrained to **`pdf` | `docx`** (`exports_format_check`).
- `status` — DB-constrained to **`processing` | `completed` | `failed`**
  (`exports_status_check`). A lifecycle CHECK ties `status` to the
  populated/empty state of `file_id`, `completed_at`, and `error_message`:
  `completed` ⇒ `file_id` + `completed_at` set; `failed` ⇒ `error_message` set;
  `processing` ⇒ none of the terminal fields.

## Join guidance

- Owner: `exports.user_id` → `supabase.public.users.id`.
- Source (exactly one): `tailored_cv_id` → `supabase.public.tailored_cvs.id`
  or `master_cv_id` → `supabase.public.master_cvs.id`.
- Artifact: `exports.file_id` → `supabase.public.files.id` (null until
  `completed`).
- Template: `exports.template_id` → `supabase.public.cv_templates.id`
  (nullable).

## Reporting notes

- Export volume/success by `format` and `status`; the "time to first export"
  metric keys off the earliest `completed` export per user.
- Split CV vs master exports via which scope column is set; combine with
  `supabase.public.cover_letter_exports` for total artifact volume.

## Warnings

- `file_id` is null for non-`completed` rows — an inner join to `files` drops
  in-flight/failed exports.
- Many export rows can exist per CV — deduplicate before counting "exported
  CVs".
