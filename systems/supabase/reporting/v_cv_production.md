---
doc_class: human-object
object: supabase.reporting.v_cv_production
written_against_schema_hash: "sha256:228d079f208abe02ea559884b36e89a3a330abeaca3176a1fe215333344c08bd"
status: draft
last_verified: null
purpose: "Tailored-CV output per month and language, including how many of that cohort were later soft-deleted."
column_purposes:
  month: "Calendar month the tailored CV was created."
  language: "Language of the tailored CV, verbatim from the row."
  tailored_cv_count: "Tailored CVs created in that month/language, including soft-deleted ones."
  distinct_users: "Users who created at least one tailored CV in that month/language."
  deleted_count: "How many of those are now flagged `is_deleted`."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_cv_production"
  - "human doc: supabase.public.tailored_cvs"
depends_on:
  - supabase.public.tailored_cvs
contamination: null
---

# `supabase.reporting.v_cv_production`

## Grain

One row per (month, language) pair with at least one tailored CV.

## Reporting notes

- The core output metric of the product: CVs actually produced.
- `deleted_count / tailored_cv_count` is a discard rate — a quality signal worth
  watching per language, since a high rate may indicate poor generation quality
  for that locale.

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
- **Soft-delete handling is not uniform across this schema.** `v_files_by_type`
  and `v_master_cvs_by_language` exclude `is_deleted` rows; `v_cv_production`
  includes them and reports `deleted_count` alongside. Check the view definition
  before comparing counts across views.
- `deleted_count` reflects deletion status **now**, not deletions that happened
  in that month. A CV created in January and deleted in June appears in
  January's `deleted_count`. It is a cohort-quality measure, not a monthly
  deletion rate.
