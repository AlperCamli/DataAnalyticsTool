---
doc_class: human-object
object: supabase.public.files
written_against_schema_hash: "sha256:a3a1531959d76aab8a389c584aa353dc06718b96a8df3979de7e3b5ee36c4f7a"
status: draft
last_verified: null
purpose: "Metadata records for binary objects stored in Supabase storage buckets, owned by users."
column_purposes:
  id: "Internal file id (referenced by imports and exports)."
  user_id: "Owning user this file belongs to (FK to users.id)."
  file_type: "Domain role of the file; enum in body."
  storage_bucket: "Name of the storage bucket that holds the object."
  storage_path: "Path of the object inside the storage bucket."
  original_filename: "Original filename supplied at upload time."
  mime_type: "MIME type of the stored object."
  size_bytes: "Size of the stored object in bytes."
  checksum: "Optional content checksum for duplicate/corruption detection."
  is_deleted: "Soft-delete flag hiding the file from active listings."
  created_at: "When this file record was created."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/files.md"
  - "app DDL: CV_Builder/backend/supabase/migrations (files_file_type_check, files_size_bytes_check)"
  - "machine doc: supabase.public.files"
depends_on:
  - supabase.public.users
  - supabase.public.imports
  - supabase.public.exports
  - supabase.public.cover_letter_exports
contamination: null
---

# `supabase.public.files`

## Grain

One row per stored binary object (upload or generated artifact). A partial
unique index enforces one live object per storage location: unique on
`(storage_bucket, storage_path)` where `is_deleted = false`. `size_bytes` is
CHECK-constrained `>= 0`. This is the metadata row — the bytes live in Supabase
storage, not in this table.

## Column meanings & enum decodings

- `file_type` — DB-constrained (`files_file_type_check`) to **`source_upload`,
  `parsed_artifact`, `export_pdf`, `export_docx`, `avatar`, `other`**. It
  encodes the file's role: `source_upload` feeds `imports`; `export_pdf`/
  `export_docx` are produced by `exports`/`cover_letter_exports`.
- `checksum` (nullable) — optional; used to detect duplicate/corrupted uploads.
- `storage_bucket` + `storage_path` — the address inside Supabase storage.

## Join guidance

- Owner: `files.user_id` → `supabase.public.users.id`.
- Inbound (each nullable on their side): `supabase.public.imports.source_file_id`,
  `supabase.public.exports.file_id`, and
  `supabase.public.cover_letter_exports.file_id` all → `files.id`. There are no
  outbound FKs.

## Reporting notes

- Per-user storage = `sum(size_bytes)` where `is_deleted = false` grouped by
  `user_id`; this backs the `storage_bytes_used` figure summarized in
  `supabase.public.usage_counters`.
- Slice artifact production by `file_type` (`export_pdf` vs `export_docx` etc.).

## Warnings

- Soft-deleted rows (`is_deleted = true`) still carry `size_bytes` — exclude
  them from live-storage totals.
- `original_filename` may contain PII — treat as sensitive.
