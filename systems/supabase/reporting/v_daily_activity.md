---
doc_class: human-object
object: supabase.reporting.v_daily_activity
written_against_schema_hash: "sha256:93fefebe723a600426cb0ecce19d62404db664bb97e50ddc3fd6b7844790ed5e"
status: draft
last_verified: null
purpose: "Gap-free daily activity across the four main actions: jobs tracked, CVs tailored, exports, and AI runs."
column_purposes:
  day: "Calendar day."
  jobs_created: "Jobs created that day."
  cvs_tailored: "Tailored CVs created that day."
  exports_created: "Exports created that day."
  ai_runs_started: "AI runs started that day."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_daily_activity"
  - "human doc: supabase.public.jobs"
  - "human doc: supabase.public.tailored_cvs"
  - "human doc: supabase.public.exports"
  - "human doc: supabase.public.ai_runs"
depends_on:
  - supabase.public.jobs
  - supabase.public.tailored_cvs
  - supabase.public.exports
  - supabase.public.ai_runs
contamination: null
---

# `supabase.reporting.v_daily_activity`

## Grain

One row per calendar day from the earliest job in `public.jobs` through today — **including days with no activity**, which appear as zeros. The only view here with a continuous series.

## Reporting notes

- Use this for trends, charts and week-over-week comparisons: the other views
  omit empty periods, which silently distorts a time series.
- The four columns side by side show whether the funnel moves together — AI runs
  rising while exports stay flat means work started and did not finish.
- Deliberately carries **no user dimension**, so it is the safest view to share
  broadly.

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
- The series starts at the first *job*, so activity in the other three tables
  predating that is not shown.
- Each column counts independently: rows are not causally linked, and a CV
  tailored today may belong to a job tracked weeks ago.
- Computed with per-day subqueries over four tables; over a long history it is
  the most expensive view here. Bound it with a `day` range.
