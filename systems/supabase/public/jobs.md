---
doc_class: human-object
object: supabase.public.jobs
written_against_schema_hash: "sha256:36740df1f02513714bd57afb0300ba30312d43cc18c774d1ea5c39703a1f24aa"
status: draft
last_verified: null
purpose: "Saved job postings a user is tracking, with application status and links to the tailored CV and cover letter for that job."
column_purposes:
  id: "Internal job id."
  user_id: "Owning user who saved this job (FK to users.id)."
  tailored_cv_id: "Tailored CV currently associated with this job (FK to tailored_cvs.id)."
  company_name: "Company posting the job."
  job_title: "Title of the role being applied to."
  job_description: "Full job description text used for AI tailoring and analysis."
  job_posting_url: "URL of the original posting, if known."
  location_text: "Free-text location for the role."
  status: "Application pipeline stage; enum decoded in body."
  notes: "User's free-form notes about this job."
  applied_at: "When the user marked the job as applied."
  created_at: "When the job record was created."
  updated_at: "When the job record was last updated."
  cover_letter_id: "Cover letter currently associated with this job (FK to cover_letters.id)."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/jobs.md"
  - "app DDL: CV_Builder/backend/supabase/migrations/20260417133000_phase2_cv_domains.sql (original jobs_status_check)"
  - "app DDL: CV_Builder/backend/supabase/migrations/20260418123000_phase4a_jobs_dashboard_rendering.sql (status rename)"
  - "machine doc: supabase.public.jobs"
depends_on:
  - supabase.public.users
  - supabase.public.tailored_cvs
  - supabase.public.cover_letters
  - supabase.public.job_status_history
contamination: null
---

# `supabase.public.jobs`

## Grain

One row per tracked job posting for a user (the "job-specific CV" anchor).
`applied_at` is set only once the user marks it applied. Two partial unique
indexes cap the reciprocal links: **at most one job per tailored CV**
(`jobs_unique_tailored_cv_idx`) and **at most one job per cover letter**
(`jobs_unique_cover_letter_idx`).

## Column meanings & enum decodings

- `status` — application pipeline stage, DB-constrained (`jobs_status_check`)
  to the **current** set **`saved` | `applied` | `interview` | `offer` |
  `rejected` | `archived`**, default `saved`. Historically (phase 2) the set
  used `interviewing`/`offered`; phase 4A renamed those to `interview`/`offer`
  **and rewrote existing rows**, so live data carries only the current set —
  only pre-4A external extracts may still show the old spellings.
- `job_description` is stored verbatim and fed to AI tailoring; it can be
  large free text.

## Join guidance

- Owner: `jobs.user_id` → `supabase.public.users.id`.
- **Reciprocal CV link:** `jobs.tailored_cv_id` → `supabase.public.tailored_cvs.id`
  *and* `supabase.public.tailored_cvs.job_id` → `jobs.id`. The two point at
  each other; the customer model notes the reverse FK on `tailored_cv_id` is
  added after both tables exist. For "the CV for this job," prefer the active
  tailored CV (`tailored_cvs.job_id = jobs.id and is_deleted = false`, which is
  uniquely indexed) rather than trusting both directions to agree.
- Cover letter: `jobs.cover_letter_id` → `supabase.public.cover_letters.id`.
- Status trail: `supabase.public.job_status_history.job_id` → `jobs.id` is the
  append-only log of `status` transitions.

## Reporting notes

- Pipeline funnels group by `status`; per-stage timing comes from
  `job_status_history`, not from `jobs` alone (only `applied_at` lives here).

## Warnings

- Do **not** double-count the `jobs`↔`tailored_cvs` relationship — pick one
  direction (the uniquely-indexed active tailored CV) as canonical.
- Legacy `status` spellings (`interviewing`/`offered`) may appear in old
  external copies — see enum note above.
