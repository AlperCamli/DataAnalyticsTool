---
doc_class: human-object
object: supabase.public.cover_letters
written_against_schema_hash: "sha256:26b706a8ef1a9b3285da73e84f0bb741a8df3f659935ff82d893594b29e37a35"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/cover_letters.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, row estimate, referenced-by)"
depends_on:
  - supabase.public.cover_letters
  - supabase.public.users
  - supabase.public.jobs
  - supabase.public.tailored_cvs
  - supabase.public.cover_letter_exports
---

# `supabase.public.cover_letters` (human doc)

A cover-letter document tied to exactly one job: `job_id` is NOT NULL
**and unique**, so the job → cover letter relationship is 1:1 at the
schema level. `content` is `text` (default `''`), not `jsonb` like the
CV tables. Structural facts are from
[cover_letters.schema.md](cover_letters.schema.md).

## Grain

One row per `id` (primary key, `uuid`); equivalently, at most one row
per `job_id` (unique constraint). Snapshot row estimate: 21
(2026-07-12) — compare 79 jobs: most jobs have no cover letter.

## Status column — what is actually decodable

`status` (`text`, NOT NULL) defaults to `'draft'` — the only value the
schema attests; full vocabulary undocumented (see PR gaps).
`last_exported_at` is nullable; export attempts live in
[cover_letter_exports.schema.md](cover_letter_exports.schema.md).

## Join guidance (from FKs)

- `job_id` → `jobs.id` (NOT NULL, unique).
- `user_id` → `users.id` (NOT NULL).
- `tailored_cv_id` → `tailored_cvs.id` (nullable): the CV the letter
  accompanies, when linked.
- Referenced by: `cover_letter_exports.cover_letter_id` and
  `jobs.cover_letter_id` (the reverse 1:1 link — see the
  double-link warning in [jobs.md](jobs.md)).

## Warnings

- No `is_deleted` flag here, unlike the CV tables — there is no
  schema-level soft-delete population to filter.
- Joining jobs→cover_letters via `cover_letters.job_id` is total over
  this table; via `jobs.cover_letter_id` it depends on that nullable
  column being maintained. State which path you used.
