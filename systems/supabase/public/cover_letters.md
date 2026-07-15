---
doc_class: human-object
object: supabase.public.cover_letters
written_against_schema_hash: "sha256:26b706a8ef1a9b3285da73e84f0bb741a8df3f659935ff82d893594b29e37a35"
status: draft
last_verified: null
purpose: "Cover letter content authored or generated for a specific tracked job, optionally linked to a tailored CV."
column_purposes:
  id: "Internal cover letter id."
  user_id: "Owning user (FK to users.id)."
  job_id: "Job this cover letter is written for (FK to jobs.id; unique — one per job)."
  tailored_cv_id: "Tailored CV associated with this cover letter, if any (FK)."
  title: "Human-readable title for the cover letter."
  content: "Full cover letter body text (plain text)."
  status: "Lifecycle stage of the cover letter; enum in body."
  last_exported_at: "When this cover letter was most recently exported."
  created_at: "When the cover letter was created."
  updated_at: "When the cover letter was last updated."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/cover_letters.md"
  - "app DDL: CV_Builder/backend/supabase/migrations (cover_letters_status_check)"
  - "machine doc: supabase.public.cover_letters"
depends_on:
  - supabase.public.users
  - supabase.public.jobs
  - supabase.public.tailored_cvs
  - supabase.public.cover_letter_exports
contamination: null
---

# `supabase.public.cover_letters`

## Grain

One row per cover letter. `job_id` is **unique**, so there is at most one
cover letter per job (the reciprocal of `supabase.public.jobs.cover_letter_id`,
which is also uniquely indexed). Unlike CV content, the body here is plain
`text`, not JSONB.

## Column meanings & enum decodings

- `status` — DB-constrained to **`draft` | `ready` | `archived`**
  (`cover_letters_status_check`), default `draft`. Note this set differs from
  `tailored_cvs.status` (no `exported` state — export progress lives in
  `cover_letter_exports` and `last_exported_at`).
- `content` — full body text, default `''` (empty until authored/generated).
- `last_exported_at` — set when an export completes; `null` means never
  exported.

## Join guidance

- Owner: `cover_letters.user_id` → `supabase.public.users.id`.
- Job: `cover_letters.job_id` → `supabase.public.jobs.id` (non-null, unique).
  The reciprocal `supabase.public.jobs.cover_letter_id` → `cover_letters.id`
  points back; prefer `cover_letters.job_id` as the canonical direction.
- CV: `cover_letters.tailored_cv_id` → `supabase.public.tailored_cvs.id`
  (nullable).
- Exports: `supabase.public.cover_letter_exports.cover_letter_id` →
  `cover_letters.id` records render jobs.

## Reporting notes

- Because `job_id` is unique, `cover_letters` joins 1:1 to `jobs` — safe to
  join without aggregation.
- Use `cover_letter_exports` (not `last_exported_at` alone) for export success
  and format breakdowns.

## Warnings

- No soft-delete column; `archived` status is the closest "hidden" signal.
- `content` may contain PII (candidate/company details) — treat as sensitive
  in shared slices.
