---
doc_class: human-object
object: supabase.reporting.v_jobs_by_status
written_against_schema_hash: "sha256:8ba1db1fd08c5a3bd5432b0e6e8d9f57d654a01b31ddf3f53c124f4036f9ba80"
status: draft
last_verified: null
purpose: "Job-application pipeline size by status: how many tracked postings sit in each stage, over how many users, and the date range each stage spans."
column_purposes:
  status: "Application stage of the tracked job, verbatim from `public.jobs.status`."
  job_count: "Tracked job postings in this status."
  distinct_users: "Users with at least one job in this status (a count, not a list)."
  first_created: "Earliest `created_at` among jobs in this status."
  last_created: "Latest `created_at` among jobs in this status."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_jobs_by_status"
  - "human doc: supabase.public.jobs"
depends_on:
  - supabase.public.jobs
contamination: null
---

# `supabase.reporting.v_jobs_by_status`

## Grain

One row per distinct `status` value present in `public.jobs`. A status with no rows does not appear — absence means zero, not null.

## Reporting notes

- The funnel view: order by the business stage sequence rather than by
  `job_count` to read it as a pipeline.
- `distinct_users` against `job_count` gives jobs-per-user in that stage — a
  concentration signal (a large ratio means a few heavy users, not broad usage).
- `first_created`/`last_created` show whether a stage is active or stale: a
  `last_created` far in the past means nothing new has entered it.

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
- `status` is not constrained by a database CHECK, so new values can appear
  without warning. Do not hard-code the set; read it from this view.
- Counts are of *tracked postings*, not applications submitted. `applied_count`
  in `v_jobs_by_month` is the closer proxy for submissions.
