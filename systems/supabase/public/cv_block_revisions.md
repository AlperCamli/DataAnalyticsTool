---
doc_class: human-object
object: supabase.public.cv_block_revisions
written_against_schema_hash: "sha256:3a1278bd5ecfd1421d8e528690c056db43cf2a1beefe7af00752ac1858e98415"
status: draft
last_verified: null
purpose: "Immutable per-block revision history for a master or tailored CV, ordered per block."
column_purposes:
  id: "Internal revision id."
  user_id: "Owning user whose CV this revision belongs to (FK to users.id)."
  cv_kind: "Which CV kind this revision is scoped to; enum in body."
  master_cv_id: "Master CV the revision belongs to when cv_kind='master' (FK)."
  tailored_cv_id: "Tailored CV the revision belongs to when cv_kind='tailored' (FK)."
  block_id: "Identifier of the CV block this revision captures."
  block_type: "Type of the block at revision time (e.g. experience, education)."
  revision_number: "Monotonic revision number per (cv, block_id); positive."
  content_snapshot: "Full block content snapshot as JSONB; structure in body."
  change_source: "What produced the revision; enum in body."
  ai_suggestion_id: "AI suggestion that originated this revision when change_source='ai' (FK)."
  created_at: "When the revision was recorded."
  created_by_user_id: "User who triggered the revision, when applicable (FK to users.id)."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/cv_block_revisions.md"
  - "app DDL: CV_Builder/backend/supabase/migrations (cv_block_revisions_cv_kind_check, change_source check, scope/revision checks)"
  - "app code: CV_Builder/backend/src/shared/cv-content/cv-content.types.ts (CvBlock)"
  - "machine doc: supabase.public.cv_block_revisions"
depends_on:
  - supabase.public.users
  - supabase.public.master_cvs
  - supabase.public.tailored_cvs
  - supabase.public.ai_suggestions
contamination: null
---

# `supabase.public.cv_block_revisions`

## Grain

One row per recorded revision of one CV block. Append-only: `revision_number`
increases monotonically per `(cv, block_id)`, enforced positive
(`revision_number > 0`) and uniquely indexed per scope (partial unique on
`(master_cv_id, block_id, revision_number)` and on
`(tailored_cv_id, block_id, revision_number)`). A scope CHECK enforces that
**exactly one** of `master_cv_id`/`tailored_cv_id` is set, matching `cv_kind`.

## Column meanings & enum decodings

- `cv_kind` — DB-constrained to **`master` | `tailored`** (`cv_block_revisions_cv_kind_check`).
- `change_source` — DB-constrained to **`manual` | `ai` | `import` |
  `restore` | `system`**. `ai_suggestion_id` is populated only when
  `change_source = 'ai'`.
- `content_snapshot` (`jsonb`, non-null) — the block content at this revision.
  It is a **`CvBlock`** snapshot (see `supabase.public.master_cvs` for the
  `CvContent`/`CvBlock` shape): `{ id, type, order, visibility, fields, meta }`.
  Stored as an open JSON object (`Record<string, unknown>` in code), so treat
  the `CvBlock` shape as the expected — not DB-enforced — structure.

## Join guidance

- Owner: `cv_block_revisions.user_id` → `supabase.public.users.id`;
  `created_by_user_id` → `supabase.public.users.id` (the actor, may differ /
  be null).
- Scoped CV: exactly one of `master_cv_id` → `supabase.public.master_cvs.id`
  or `tailored_cv_id` → `supabase.public.tailored_cvs.id`, per `cv_kind`.
- Provenance: `ai_suggestion_id` → `supabase.public.ai_suggestions.id` for
  AI-sourced revisions.

## Reporting notes

- The latest state of a block is `max(revision_number)` within its scope; use
  the per-scope block indexes (ordered `revision_number desc`).
- Filter by `cv_kind` before joining to the matching CV table to avoid null
  joins on the other scope column.

## Warnings

- `block_type` and the `content_snapshot` `type`/`fields` vocabularies are
  app-defined and **not grounded in the DB** (same gap as CV content).
- Do not assume `created_by_user_id = user_id`; `system`/`ai` revisions may
  leave the actor null.
