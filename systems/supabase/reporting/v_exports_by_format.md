---
doc_class: human-object
object: supabase.reporting.v_exports_by_format
written_against_schema_hash: "sha256:23ebec8a64c7bd850eebd3897530e3f5bcba383827dae25329453280bd1d4076"
status: draft
last_verified: null
purpose: "Export volume by output format and outcome."
column_purposes:
  format: "Export output format (e.g. pdf, docx)."
  status: "Export outcome status."
  export_count: "Exports matching this format/status."
  distinct_users: "Users with at least one such export."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_exports_by_format"
  - "human doc: supabase.public.exports"
depends_on:
  - supabase.public.exports
contamination: null
---

# `supabase.reporting.v_exports_by_format`

## Grain

One row per (format, status) pair observed.

## Reporting notes

- Which formats users actually take away, and whether any format is failing
  more than the others — a format with an unusual failure share points at that
  renderer rather than at the pipeline.

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
- Grouped by status, so sum across statuses before quoting a format's total.
- Counts exports *attempted*, not files successfully downloaded.
