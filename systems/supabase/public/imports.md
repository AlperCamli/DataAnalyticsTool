---
doc_class: human-object
object: supabase.public.imports
written_against_schema_hash: "sha256:637c57a9477ce54183d6f23df56a09c439bdf16333457573c081240d565ac026"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/imports.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, row estimate)"
depends_on:
  - supabase.public.imports
  - supabase.public.users
  - supabase.public.files
  - supabase.public.master_cvs
---

# `supabase.public.imports` (human doc)

Import records: each row starts from an uploaded file
(`source_file_id`, NOT NULL) and optionally targets a master CV
(`target_master_cv_id`, nullable), carrying parser output
(`raw_extracted_text`, `parsed_content`) and a `status`. Structural
facts are from [imports.schema.md](imports.schema.md).

## Grain

One row per `id` (primary key, `uuid`). No unique constraint on
`source_file_id` — the same file may be imported more than once.
Snapshot row estimate: 87 (2026-07-12).

## Columns with grounded notes

- `status` (`text`, NOT NULL): no default, no constraint — vocabulary
  undocumented (see PR gaps). Indexed as `(user_id, status)`.
- `parser_name` (`text`, nullable): value set undocumented.
- `parsed_content` (`jsonb`, nullable): shape undocumented; whether it
  matches the CV tables' `current_content` shape is not stated
  anywhere.
- `target_master_cv_id` nullable: what a NULL target means (failed
  parse? not yet applied?) is undocumented.
- `module_type` (`text`, NOT NULL, default `'standard'`): same
  column/default as on the CV tables and `cv_templates`.

## Join guidance (from FKs)

`user_id` → `users.id` (NOT NULL); `source_file_id` → `files.id`
(NOT NULL); `target_master_cv_id` → `master_cvs.id` (nullable).

## Warnings

- Import success/failure cannot be derived without the `status`
  vocabulary; `error_message` being non-null is evidence of a recorded
  error but its exact relationship to `status` is undocumented.
