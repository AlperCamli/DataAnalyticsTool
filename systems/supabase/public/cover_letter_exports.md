---
doc_class: human-object
object: supabase.public.cover_letter_exports
written_against_schema_hash: "sha256:4e9e86056fbd97f3a527042842d3e3389b39640933860719b21e914712d85408"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/cover_letter_exports.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes)"
depends_on:
  - supabase.public.cover_letter_exports
  - supabase.public.cover_letters
  - supabase.public.files
  - supabase.public.users
---

# `supabase.public.cover_letter_exports` (human doc)

Export records for cover letters: each row ties one cover letter to a
`format`, a `status`, an optional produced file, and
`created_at`/`completed_at` timestamps — the same structural shape as
[exports.schema.md](exports.schema.md) has for CVs. Structural facts
are from
[cover_letter_exports.schema.md](cover_letter_exports.schema.md).

## Grain

One row per `id` (primary key, `uuid`). No unique constraint beyond the
PK — multiple rows per cover letter are allowed (and the
`(cover_letter_id, created_at DESC)` index is built for reading them
newest-first). No row estimate recorded in the 2026-07-12 snapshot.

## Columns with grounded notes

- `format` (`text`, NOT NULL): no default, no constraint — value set
  undocumented (see PR gaps).
- `status` (`text`, NOT NULL): no default here (unlike most status
  columns in this schema) — not even one value is attested; fully
  undocumented (see PR gaps). `error_message` (nullable) exists for
  failure detail.
- `file_id` → `files.id` is **nullable**: rows can exist without a
  produced file; whether that corresponds to pending/failed status
  values is undocumented.
- `completed_at` is nullable; `created_at` defaults to `now()`.

## Join guidance (from FKs)

- `cover_letter_id` → `cover_letters.id` (NOT NULL).
- `user_id` → `users.id` (NOT NULL).
- `file_id` → `files.id` (nullable).

## Warnings

- "Latest export per cover letter" needs an explicit
  `ORDER BY created_at DESC LIMIT 1` (or window) per cover letter —
  nothing marks a row as current.
- Do not treat rows here as successful exports; without the status
  vocabulary, filter semantics are undefined. Ground a success filter
  in a customer source before certifying any export metric.
