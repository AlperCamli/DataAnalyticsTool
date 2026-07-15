---
doc_class: human-object
object: supabase.public.tailored_cvs
written_against_schema_hash: "sha256:401ae631f9f475a3cbc7c633a68fb3ff98ac5b2d57ab30dafebd271975e95945"
status: draft
last_verified: null
purpose: "A job-specific variant of a master CV produced for a single tracked job application."
column_purposes:
  id: "Internal tailored CV id."
  user_id: "Owning user (FK to users.id)."
  master_cv_id: "Master CV this variant was derived from (FK to master_cvs.id)."
  job_id: "Job this variant targets, if linked (FK to jobs.id)."
  title: "Human-readable title for the tailored CV."
  language: "Language code of the tailored CV content."
  template_id: "Template selected for previewing this CV (FK to cv_templates.id)."
  current_content: "Canonical structured CV content as JSONB; structure in master_cvs body."
  status: "Lifecycle stage of the tailored CV; enum decoded in body."
  ai_generation_status: "Status of the most recent AI tailoring run; enum decoded in body."
  last_exported_at: "When this tailored CV was most recently exported."
  is_deleted: "Soft-delete flag hiding this CV from active lists."
  created_at: "When the tailored CV was created."
  updated_at: "When the tailored CV was last updated."
  module_type: "CV module family (standard vs medical); enum decoded in master_cvs body."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/tailored_cvs.md"
  - "app DDL: CV_Builder/backend/supabase/migrations/20260417133000_phase2_cv_domains.sql (tailored_cvs_status_check)"
  - "app code: CV_Builder/backend/src/modules/ai/ai.service.ts (ai_generation_status values)"
  - "app code: CV_Builder/backend/src/shared/cv-content/cv-content.types.ts (CvContent)"
  - "machine doc: supabase.public.tailored_cvs"
depends_on:
  - supabase.public.users
  - supabase.public.master_cvs
  - supabase.public.jobs
  - supabase.public.cv_templates
contamination: null
---

# `supabase.public.tailored_cvs`

## Grain

One row per tailored CV — a variant of one `master_cv` aimed at (at most) one
`job`. A partial unique index enforces **at most one active tailored CV per
job** (`tailored_cvs_unique_job_active_idx`: unique on `job_id` where
`job_id is not null and is_deleted = false`). `is_deleted = true` rows are
soft-deleted.

## Column meanings & enum decodings

- `status` — DB-constrained to **`draft` | `ready` | `exported` | `archived`**
  (`tailored_cvs_status_check`), default `draft`.
- `ai_generation_status` (nullable, **no DB CHECK**) — tracks the latest AI
  tailored-draft run; application code uses **`pending` | `completed` |
  `failed`**. Because it is unconstrained in the DB, treat that set as
  app-governed and possibly incomplete.
- `current_content` (`jsonb`, non-null) — same `CvContent` shape as
  `supabase.public.master_cvs` (`version`/`language`/`metadata`/`sections[]`
  → `blocks[]`); see that doc for the structure rather than repeating it.
- `module_type` — `standard` (default) or `medical_uk`, as in `master_cvs`.

## Join guidance

- Owner: `tailored_cvs.user_id` → `supabase.public.users.id`.
- Source CV: `tailored_cvs.master_cv_id` → `supabase.public.master_cvs.id`
  (non-null — every tailored CV has a master).
- Job: `tailored_cvs.job_id` → `supabase.public.jobs.id` (nullable). Note the
  **reciprocal** FK `supabase.public.jobs.tailored_cv_id` → `tailored_cvs.id`;
  the two tables reference each other (see `jobs` for how to avoid
  double-counting).
- Template: `tailored_cvs.template_id` → `supabase.public.cv_templates.id`.

## Reporting notes

- Filter `is_deleted = false` for active tailored CVs.
- "Tailoring funnel" work keys off `status` and `ai_generation_status`;
  `last_exported_at` marks CVs that reached export.

## Warnings

- `ai_generation_status` is nullable and unconstrained — `null` means no AI
  run has been recorded, distinct from a `failed` run.
- The `current_content` JSON `type`/`fields` vocabularies are app-defined and
  **not grounded in the DB** (same gap as `master_cvs`).
