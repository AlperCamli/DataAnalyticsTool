---
doc_class: human-object
object: supabase.public.job_status_history
written_against_schema_hash: "sha256:797056ddeef9e10c86890f5cf5a04d894fb0ed069b01b8bbfeb0332d230a8d5a"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/job_status_history.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes)"
depends_on:
  - supabase.public.job_status_history
  - supabase.public.jobs
  - supabase.public.users
---

# `supabase.public.job_status_history` (human doc)

Recorded status transitions of `jobs` rows: each row captures a single
`from_status` → `to_status` change for one job, with `changed_at`
(default `now()`) and the acting user. Structural facts are from
[job_status_history.schema.md](job_status_history.schema.md).

## Grain

One row per `id` (primary key, `uuid`) — structurally, one recorded
transition. `from_status` is nullable, `to_status` is NOT NULL; what a
NULL `from_status` denotes (e.g. an initial state) is undocumented —
see PR gaps.

## Join guidance (from FKs)

- `job_id` → `jobs.id` (NOT NULL): the job whose status changed.
- `changed_by_user_id` → `users.id` (NOT NULL): the user recorded as
  making the change.

Both time-ordered access paths are indexed:
`(job_id, changed_at DESC)` and `(changed_by_user_id, changed_at DESC)`.

## Warnings

- Nothing in the schema guarantees completeness (that every `jobs.status`
  change produced a row here) or append-only behavior; treat derived
  funnels as best-effort until a customer source confirms the write path
  (undocumented — see PR gaps).
- `to_status` values are the same undocumented vocabulary as
  `jobs.status`; the schema attests only `'saved'` (that column's
  default) anywhere.
