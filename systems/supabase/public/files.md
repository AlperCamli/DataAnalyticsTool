---
doc_class: human-object
object: supabase.public.files
written_against_schema_hash: "sha256:a3a1531959d76aab8a389c584aa353dc06718b96a8df3979de7e3b5ee36c4f7a"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/files.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, row estimate, referenced-by)"
depends_on:
  - supabase.public.files
  - supabase.public.users
  - supabase.public.cover_letter_exports
  - supabase.public.exports
  - supabase.public.imports
---

# `supabase.public.files` (human doc)

Registry of stored files: each row records a storage location
(`storage_bucket` + `storage_path`), the `original_filename`,
`mime_type`, and `size_bytes`, owned by one user. Structural facts are
from [files.schema.md](files.schema.md).

## Grain

One row per `id` (primary key, `uuid`). Partial unique index
`files_bucket_path_unique_idx` on `(storage_bucket, storage_path)`
WHERE `is_deleted = false`: **one non-deleted row per storage
location**; flagged (`is_deleted = true`) rows may share a location.
Snapshot row estimate: 234 (2026-07-12).

## Columns with grounded notes

- `file_type` (`text`, NOT NULL, indexed): vocabulary undocumented (see
  PR gaps) — note this is a separate axis from `mime_type`.
- `size_bytes` (`bigint`, NOT NULL): the unit is in the column name;
  how it relates to `usage_counters.storage_bytes_used` (also `bigint`)
  is undocumented.
- `checksum` (`text`, nullable): algorithm/format undocumented.
- `is_deleted` (`boolean`, NOT NULL, default `false`): flagged rows
  stay in the table; storage-size sums change materially with this
  filter.

## Join guidance (from FKs)

- `user_id` → `users.id` (NOT NULL).
- Referenced by: `exports.file_id`, `cover_letter_exports.file_id`
  (produced files), `imports.source_file_id` (uploaded sources) — all
  per the machine doc's Referenced-by table.

## Warnings

- Storage usage per user: sum `size_bytes` grouped by `user_id`, and
  state the `is_deleted` filter used; the flagged population still
  occupies rows (and possibly storage — the schema does not say whether
  flagged files are physically removed).
