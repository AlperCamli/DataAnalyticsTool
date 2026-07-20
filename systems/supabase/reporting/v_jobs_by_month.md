---
doc_class: human-object
object: supabase.reporting.v_jobs_by_month
written_against_schema_hash: "sha256:139aa747a5499b9fd846f72f6b2215d977521874d4f31b6138b021cb57c4ee48"
status: draft
last_verified: null
purpose: "Monthly job-tracking volume: postings created per month, how many users created them, and how many reached the applied stage."
column_purposes:
  month: "Calendar month of `created_at`, truncated to the first day."
  job_count: "Job postings created in the month."
  distinct_users: "Users who created at least one job that month."
  applied_count: "Jobs created that month with a non-null `applied_at`."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_jobs_by_month"
  - "human doc: supabase.public.jobs"
depends_on:
  - supabase.public.jobs
contamination: null
---

# `supabase.reporting.v_jobs_by_month`

## Grain

One row per calendar month in which at least one job was created. Months with no activity are absent — use `v_daily_activity` if you need a gap-free series.

## Reporting notes

- Growth over time, and the natural denominator for retention questions.
- `applied_count / job_count` is a conversion rate from *tracked* to *applied* —
  but see the warning: it is measured on the creation month, not the month the
  application happened.

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
- **`applied_count` is attributed to the month the job was created, not the
  month it was applied to.** A job created in January and applied to in March
  counts toward January. For true monthly application volume, aggregate
  `applied_at` directly rather than using this column.
- `applied_at` non-null is the only signal of application; a job moved to an
  applied-like `status` without `applied_at` set will not be counted.
