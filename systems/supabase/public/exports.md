---
doc_class: human-object
object: supabase.public.exports
written_against_schema_hash: "sha256:ab7194cd6d3a1ed8af4c692f1183b3246f1f07c9e115f968bef9cb843f8a5290"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/exports.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, row estimate)"
depends_on:
  - supabase.public.exports
  - supabase.public.users
  - supabase.public.tailored_cvs
  - supabase.public.master_cvs
  - supabase.public.files
  - supabase.public.cv_templates
---

# `supabase.public.exports` (human doc)

Export records for CV documents: each row carries a `format`, a
`status`, an optional produced file, an optional template, and
`created_at`/`completed_at`. Both `tailored_cv_id` and `master_cv_id`
are nullable — an export row can point at either kind of CV (or,
schema-wise, neither). Structural facts are from
[exports.schema.md](exports.schema.md).

## Grain

One row per `id` (primary key, `uuid`). No unique constraints beyond
the PK — many exports per document are allowed, and the
`(tailored_cv_id, created_at DESC)` / partial
`(master_cv_id, created_at DESC)` indexes are built for newest-first
reads. Snapshot row estimate: 177 (2026-07-12).

## Columns with grounded notes

- `format` (`text`, NOT NULL) and `status` (`text`, NOT NULL): no
  defaults, no constraints — both vocabularies undocumented (see PR
  gaps). `error_message` (nullable) exists for failure detail.
- `file_id` → `files.id` (nullable): rows can exist without a produced
  file; the status values that correspond to that state are
  undocumented.
- No CHECK enforces exactly-one-of `tailored_cv_id`/`master_cv_id`;
  which one is set per row is only observable in data.

## Join guidance (from FKs)

`user_id` → `users.id` (NOT NULL); `tailored_cv_id` →
`tailored_cvs.id`; `master_cv_id` → `master_cvs.id`; `file_id` →
`files.id`; `template_id` → `cv_templates.id` (all four nullable).

## Warnings

- Do not equate a row with a successful export: without the `status`
  vocabulary, success filters are undefined. Ground the filter in a
  customer source before certifying any export count
  (`usage_counters.exports_count` exists but its increment rule is
  likewise undocumented — see
  [usage_counters.schema.md](usage_counters.schema.md)).
- Cover letters export through a separate table
  ([cover_letter_exports.schema.md](cover_letter_exports.schema.md));
  "all exports" requires UNIONing the two and saying so.
