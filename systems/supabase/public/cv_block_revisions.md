---
doc_class: human-object
object: supabase.public.cv_block_revisions
written_against_schema_hash: "sha256:3a1278bd5ecfd1421d8e528690c056db43cf2a1beefe7af00752ac1858e98415"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/cv_block_revisions.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes)"
depends_on:
  - supabase.public.cv_block_revisions
  - supabase.public.users
  - supabase.public.master_cvs
  - supabase.public.tailored_cvs
  - supabase.public.ai_suggestions
---

# `supabase.public.cv_block_revisions` (human doc)

Per-block revision history for CV documents: each row snapshots one
block's content (`content_snapshot`, `jsonb` NOT NULL) at a numbered
revision, for either a master or a tailored CV. Structural facts are
from [cv_block_revisions.schema.md](cv_block_revisions.schema.md).

## Grain — fully attested by unique indexes

- Where `cv_kind = 'master'` (and `master_cv_id` set): one row per
  `(master_cv_id, block_id, revision_number)`
  (`cv_block_revisions_master_unique_revision_idx`).
- Where `cv_kind = 'tailored'` (and `tailored_cv_id` set): one row per
  `(tailored_cv_id, block_id, revision_number)`
  (`cv_block_revisions_tailored_unique_revision_idx`).

The index predicates also attest the two `cv_kind` values the schema
knows: `'master'` and `'tailored'` — a rare case where the enum is
decodable from machine facts alone.

## Columns with grounded notes

- `master_cv_id` and `tailored_cv_id` are both nullable FKs; the
  partial indexes pair each with its `cv_kind` value. No CHECK
  constraint enforces exactly-one-of — rows outside the two indexed
  shapes are not schema-impossible.
- `change_source` (`text`, NOT NULL): vocabulary undocumented (see PR
  gaps). `ai_suggestion_id` → `ai_suggestions.id` (nullable) links a
  revision to the suggestion that produced it, when set.
- `block_id` and `block_type` are `text`; the block model of
  `current_content` in the CV tables is undocumented.
- `created_by_user_id` is nullable, while `user_id` is NOT NULL; the
  distinction between the two is undocumented (owner vs. actor is a
  guess we are not making — see PR gaps).

## Join guidance (from FKs)

`user_id`/`created_by_user_id` → `users.id`; `master_cv_id` →
`master_cvs.id`; `tailored_cv_id` → `tailored_cvs.id`;
`ai_suggestion_id` → `ai_suggestions.id`.

## Warnings

- Latest revision per block = max `revision_number` within the
  applicable unique-index scope; the `(…, revision_number DESC)`
  partial indexes are built for exactly that read.
- Filter by `cv_kind` first; mixing kinds double-counts blocks whose
  `block_id` values coincide across master and tailored documents.
