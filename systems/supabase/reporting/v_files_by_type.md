---
doc_class: human-object
object: supabase.reporting.v_files_by_type
written_against_schema_hash: "sha256:77d8d34973b23250d395f62b03acaea822380965f51458723d76e4a3f6cc6ad2"
status: draft
last_verified: null
purpose: "Active file inventory and storage footprint by file type and MIME type."
column_purposes:
  file_type: "Application-level file classification."
  mime_type: "MIME type recorded at upload."
  file_count: "Active (not soft-deleted) files."
  distinct_users: "Users owning at least one such file."
  total_bytes: "Sum of `size_bytes` across those files."
  avg_bytes: "Mean file size, rounded."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_files_by_type"
  - "human doc: supabase.public.files"
depends_on:
  - supabase.public.files
contamination: null
---

# `supabase.reporting.v_files_by_type`

## Grain

One row per (file_type, mime_type) pair among **non-deleted** files.

## Reporting notes

- The storage-cost view, and the input to retention questions.
- `avg_bytes` per MIME type identifies which formats drive the footprint;
  `total_bytes` is what a storage bill tracks.

## Warnings

- **These are aggregate views over row-level-security-protected tables.** The
  base tables (`public.*`) enforce per-user RLS, so the execution role reads
  **zero rows** from them directly. These views answer anyway because a view
  evaluates RLS as its *owner*, and they are owned by a role that bypasses it.
  That is a deliberate, narrow opening — and it is why every column here is an
  aggregate or a non-identifying dimension. Do not expect to drill from these
  numbers to a person: no view exposes `user_id`, an email, a name, or any free
  text a user wrote.
- **Small counts can still identify.** The estate is ~24 users. A group of size
  1–2 is potentially personal even though no column names anyone; treat such
  cells as sensitive rather than reportable.
- Soft-deleted files are **excluded**, so this understates what the storage
  provider is actually billing if deleted objects are not purged. It measures
  the logical inventory, not the physical one.
- `size_bytes` is recorded at upload and is not re-verified against storage.
