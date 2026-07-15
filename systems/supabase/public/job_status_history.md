---
doc_class: human-object
object: supabase.public.job_status_history
written_against_schema_hash: "sha256:797056ddeef9e10c86890f5cf5a04d894fb0ed069b01b8bbfeb0332d230a8d5a"
status: draft
last_verified: null
purpose: "Append-only log of status transitions for a job application, attributing each change to a user."
column_purposes:
  id: "Internal status-history entry id."
  job_id: "Job whose status transition is recorded (FK to jobs.id)."
  from_status: "Previous status before the transition, or null for the first entry; enum in body."
  to_status: "New status after the transition; enum in body."
  changed_at: "When the transition was recorded."
  changed_by_user_id: "User who performed the transition (FK to users.id)."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/job_status_history.md"
  - "app DDL: CV_Builder/backend/supabase/migrations/20260418123000_phase4a_jobs_dashboard_rendering.sql (from_status/to_status checks)"
  - "machine doc: supabase.public.job_status_history"
depends_on:
  - supabase.public.jobs
  - supabase.public.users
contamination: null
---

# `supabase.public.job_status_history`

## Grain

One row per recorded status transition of a job — an append-only audit trail
(no update/delete in normal use). The initial entry for a job has
`from_status = null`. Ordered per job by `(job_id, changed_at desc)`.

## Column meanings & enum decodings

- `from_status` — the prior stage, `null` for the first transition; otherwise
  one of **`saved` | `applied` | `interview` | `offer` | `rejected` |
  `archived`** (`job_status_history_from_status_check`).
- `to_status` — the new stage, DB-constrained to the same set
  (`job_status_history_to_status_check`). This vocabulary matches the current
  `supabase.public.jobs.status` set; it was introduced with the phase-4A
  `interview`/`offer` naming, so this table never contained the legacy
  `interviewing`/`offered` spellings.

## Join guidance

- Job: `job_status_history.job_id` → `supabase.public.jobs.id` (on delete
  cascade — history disappears with its job).
- Actor: `job_status_history.changed_by_user_id` → `supabase.public.users.id`
  (non-null; every transition is attributed).

## Reporting notes

- This is the source for per-stage timing (e.g. time-to-applied, time-in-stage)
  — `supabase.public.jobs` only stores the current `status` and `applied_at`.
- Compute dwell time as the gap between successive `changed_at` values for a
  `job_id`.

## Warnings

- Cascade delete means history is not retained after a job is deleted — it is
  not a durable ledger independent of `jobs`.
- Rows are per-transition, not per-state; count transitions, not distinct jobs,
  unless you aggregate by `job_id`.
