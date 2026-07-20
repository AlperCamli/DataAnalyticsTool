---
doc_class: human-object
object: supabase.reporting.v_master_cvs_by_language
written_against_schema_hash: "sha256:a79db79fd110a4c74212cf4ff0738568a509e37f588c776d694787f1efe2baf7"
status: draft
last_verified: null
purpose: "Active master-CV inventory by language and how it was created (uploaded, built, imported)."
column_purposes:
  language: "Language of the master CV."
  source_type: "How the master CV originated, verbatim from the row."
  master_cv_count: "Active (not soft-deleted) master CVs."
  distinct_users: "Users holding at least one such master CV."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_master_cvs_by_language"
  - "human doc: supabase.public.master_cvs"
depends_on:
  - supabase.public.master_cvs
contamination: null
---

# `supabase.reporting.v_master_cvs_by_language`

## Grain

One row per (language, source_type) pair among **non-deleted** master CVs.

## Reporting notes

- Inventory, not flow: this is the current stock of source documents users
  build from.
- `source_type` splits acquisition channels — a large import share suggests
  users arrive with an existing CV rather than starting fresh.

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
- Soft-deleted rows are **excluded** entirely, so this view cannot tell you
  anything about churn. Compare against `v_cv_production` carefully — that one
  includes deleted rows.
