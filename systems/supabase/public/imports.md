---
doc_class: human-object
object: supabase.public.imports
written_against_schema_hash: "sha256:637c57a9477ce54183d6f23df56a09c439bdf16333457573c081240d565ac026"
status: draft
last_verified: null
purpose: "Pipeline records tracking the parse of an uploaded source CV file into structured content for a master CV."
column_purposes:
  id: "Internal import id."
  user_id: "User who initiated the import (FK to users.id)."
  source_file_id: "Uploaded file being parsed (FK to files.id)."
  target_master_cv_id: "Master CV the parsed content was converted into, if any (FK)."
  status: "Import lifecycle stage; enum in body."
  parser_name: "Name of the parser implementation that processed the file."
  raw_extracted_text: "Raw text extracted from the file before structured parsing."
  parsed_content: "Structured CV content produced by parsing as JSONB; structure in body."
  error_message: "Error description recorded when the import fails."
  created_at: "When this import was created."
  updated_at: "When this import was last updated."
  module_type: "CV module family of the import (standard vs medical); enum in body."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/imports.md"
  - "app DDL: CV_Builder/backend/supabase/migrations (imports_status_check)"
  - "app DDL: CV_Builder/backend/supabase/migrations/20260611120000_phase13_cv_modules.sql (module_type)"
  - "app code: CV_Builder/backend/src (parsed_content normalized to CvContent)"
  - "machine doc: supabase.public.imports"
depends_on:
  - supabase.public.users
  - supabase.public.files
  - supabase.public.master_cvs
contamination: null
---

# `supabase.public.imports`

## Grain

One row per import attempt of a source file. It advances through the `status`
stages below; `target_master_cv_id` is populated only once the parse is
converted into a master CV. Indexed by `(user_id, status)` for pipeline views.

## Column meanings & enum decodings

- `status` — DB-constrained to **`uploaded` | `parsing` | `parsed` |
  `reviewed` | `converted` | `failed`** (`imports_status_check`). `converted`
  is the success terminal (a master CV exists); `failed` is the error terminal.
- `module_type` — `standard` (default) or `medical_uk`, as elsewhere.
- `raw_extracted_text` — pre-structure plain text (nullable until extracted).
- `parsed_content` (`jsonb`, nullable) — the structured parse output,
  normalized to **`CvContent`** in code (the same shape as
  `supabase.public.master_cvs.current_content`: `version`/`language`/
  `metadata`/`sections[]`→`blocks[]`). Null until parsing produces content.

## Join guidance

- Owner: `imports.user_id` → `supabase.public.users.id`.
- Source: `imports.source_file_id` → `supabase.public.files.id` (non-null —
  every import has an uploaded file).
- Result: `imports.target_master_cv_id` → `supabase.public.master_cvs.id`
  (nullable; set at `converted`).

## Reporting notes

- Import funnel = counts by `status` (`uploaded` → … → `converted`), sliced by
  `parser_name` for parser success comparisons.
- Time-to-convert = `updated_at` − `created_at` for `converted` rows (there is
  no per-stage timestamp table here).

## Warnings

- `parsed_content` block/section `type`/`fields` vocabularies are app-defined,
  **not DB-grounded** (same gap as CV content).
- A `converted` import does not guarantee `target_master_cv_id` still resolves
  if the master CV was later soft-deleted — check `master_cvs.is_deleted`.
