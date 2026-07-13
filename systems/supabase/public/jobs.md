---
doc_class: human-object
object: supabase.public.jobs
written_against_schema_hash: "sha256:36740df1f02513714bd57afb0300ba30312d43cc18c774d1ea5c39703a1f24aa"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/jobs.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, row estimate, referenced-by)"
depends_on:
  - supabase.public.jobs
  - supabase.public.users
  - supabase.public.cover_letters
  - supabase.public.tailored_cvs
  - supabase.public.ai_runs
  - supabase.public.job_status_history
---

# `supabase.public.jobs` (human doc)

A user-scoped record of a job posting the user is tracking
(`company_name`, `job_title`, `job_description` are all NOT NULL), with
links to at most one tailored CV and at most one cover letter.
Structural facts are from [jobs.schema.md](jobs.schema.md); untracked
business semantics are listed as gaps in the enrich PR.

## Grain

One row per `id` (primary key, `uuid`). Snapshot row estimate: 79
(2026-07-12).

## Status column — what is actually decodable

`status` (`text`, NOT NULL) defaults to `'saved'` — the only value the
schema itself attests. The **full value set and each value's meaning are
undocumented** (no CHECK constraint, no column comment, no customer
doc); transitions are observable per job in
[job_status_history.schema.md](job_status_history.schema.md)
(`from_status` → `to_status`). `applied_at` is nullable; its
relationship to any particular `status` value is undocumented.

## Join guidance (from FKs and unique indexes)

- `user_id` → `users.id` (NOT NULL): every job belongs to exactly one
  user.
- `tailored_cv_id` → `tailored_cvs.id` (nullable), and unique where not
  null (`jobs_unique_tailored_cv_idx`): a tailored CV is attached to at
  most one job row.
- `cover_letter_id` → `cover_letters.id` (nullable), unique where not
  null (`jobs_unique_cover_letter_idx`): a cover letter is attached to
  at most one job row. Note the reverse link also exists —
  `cover_letters.job_id` is NOT NULL and unique — so the job ↔ cover
  letter relationship is 1:1 from both sides.
- Referenced by `ai_runs.job_id`, `job_status_history.job_id`,
  `cover_letters.job_id`, `tailored_cvs.job_id`.

## Warnings

- `jobs.tailored_cv_id` and `tailored_cvs.job_id` are two independent
  nullable links between the same pair of tables; the schema does not
  state which one is authoritative or whether they are kept mutually
  consistent (undocumented — see PR gaps). Pick one direction per query
  and say which you used.
- `status` is indexed (`jobs_status_idx`) — filtering on it is cheap;
  but do not enumerate "all statuses" from a query result and treat that
  as the closed set.
