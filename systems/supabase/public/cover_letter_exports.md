---
doc_class: human-object
object: supabase.public.cover_letter_exports
written_against_schema_hash: "sha256:4e9e86056fbd97f3a527042842d3e3389b39640933860719b21e914712d85408"
status: draft
last_verified: null
purpose: "Export job records for rendering a cover letter into a downloadable PDF or DOCX artifact."
column_purposes:
  id: "Internal cover letter export id."
  user_id: "Owning user that initiated the export (FK to users.id)."
  cover_letter_id: "Cover letter being exported (FK to cover_letters.id)."
  file_id: "Generated file artifact, populated when the export completes (FK to files.id)."
  format: "Output format; enum in body."
  status: "Export lifecycle stage; enum in body."
  error_message: "Error description recorded when the export fails."
  created_at: "When the export was requested."
  completed_at: "When the export reached a terminal state."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/cover_letter_exports.md"
  - "app DDL: CV_Builder/backend/supabase/migrations (cover_letter_exports_format_check, cover_letter_exports_status_check, lifecycle check)"
  - "machine doc: supabase.public.cover_letter_exports"
depends_on:
  - supabase.public.users
  - supabase.public.cover_letters
  - supabase.public.files
contamination: null
---

# `supabase.public.cover_letter_exports`

## Grain

One row per cover-letter export attempt (a job may be re-exported, producing
several rows over time). Ordered for reporting by `(status, created_at desc)`
and per cover letter by `(cover_letter_id, created_at desc)`.

## Column meanings & enum decodings

- `format` — DB-constrained to **`pdf` | `docx`** (`cover_letter_exports_format_check`).
- `status` — DB-constrained to **`processing` | `completed` | `failed`**
  (`cover_letter_exports_status_check`). A lifecycle CHECK ties `status` to the
  populated/empty state of `file_id`, `completed_at`, and `error_message`:
  a `completed` row has `file_id` and `completed_at` set; a `failed` row
  carries `error_message`; a `processing` row has none of the terminal fields.

## Join guidance

- Owner: `cover_letter_exports.user_id` → `supabase.public.users.id`.
- Source: `cover_letter_exports.cover_letter_id` →
  `supabase.public.cover_letters.id`.
- Artifact: `cover_letter_exports.file_id` → `supabase.public.files.id`
  (nullable until `completed`).

## Reporting notes

- Export success rate = `completed` / all attempts, grouped by `format`.
- This mirrors `supabase.public.exports` (which handles CV exports); keep the
  two apart — cover-letter exports never carry a `template_id` or CV scope.

## Warnings

- A single cover letter can have many export rows; deduplicate by
  `cover_letter_id` (e.g. latest `completed`) before counting "exported cover
  letters".
- `file_id` is `null` for non-completed rows — an inner join to `files`
  silently drops in-flight/failed exports.
