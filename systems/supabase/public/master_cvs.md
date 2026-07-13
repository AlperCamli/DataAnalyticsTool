---
doc_class: human-object
object: supabase.public.master_cvs
written_against_schema_hash: "sha256:fedbafc33b7a23d0b1fb9c4f646ca486df3265d32a686385ccfbc2790c6de177"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/master_cvs.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, row estimate, referenced-by)"
depends_on:
  - supabase.public.master_cvs
  - supabase.public.users
  - supabase.public.cv_templates
  - supabase.public.tailored_cvs
  - supabase.public.ai_runs
  - supabase.public.ai_suggestions
  - supabase.public.cv_block_revisions
  - supabase.public.exports
  - supabase.public.imports
---

# `supabase.public.master_cvs` (human doc)

A user's base CV document: `current_content` (`jsonb`, NOT NULL) holds
the document body, with `title` and `language` required. Tailored CVs
derive from it (`tailored_cvs.master_cv_id` is NOT NULL). Structural
facts are from [master_cvs.schema.md](master_cvs.schema.md).

## Grain

One row per `id` (primary key, `uuid`). No unique constraint on
`(user_id, title)` — a user can hold several master CVs with the same
title. Snapshot row estimate: 106 (2026-07-12).

## Columns with grounded notes

- `source_type` (`text`, NOT NULL): value set entirely undocumented —
  no default, no constraint, no customer doc (see PR gaps).
- `module_type` (`text`, NOT NULL, default `'standard'`): only the
  default value is attested; the same column/default appears on
  `tailored_cvs`, `cv_templates`, and `imports`.
- `is_deleted` (`boolean`, NOT NULL, default `false`): the composite
  index `(user_id, is_deleted)` shows reads are expected to filter on
  it. Rows are retained with the flag set rather than removed — whether
  a report should include flagged rows is a business decision the schema
  does not answer.
- `template_id` → `cv_templates.id` is **nullable**: a master CV can
  exist with no template.

## Join guidance (from FKs)

- `user_id` → `users.id` (NOT NULL).
- `template_id` → `cv_templates.id` (nullable).
- Referenced by: `tailored_cvs.master_cv_id`, `exports.master_cv_id`,
  `imports.target_master_cv_id`, `ai_runs.master_cv_id`,
  `ai_suggestions.master_cv_id`, `cv_block_revisions.master_cv_id`.

## Warnings

- Counts of "a user's CVs" change materially with the `is_deleted`
  filter; always state which population you counted.
- `current_content` is opaque `jsonb`; its internal block structure is
  documented nowhere in the KB (block-level history lives in
  [cv_block_revisions.schema.md](cv_block_revisions.schema.md), whose
  `block_id` is `text`).
