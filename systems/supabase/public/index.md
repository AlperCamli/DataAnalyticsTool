---
doc_class: machine-index
system: supabase
scope: schema
schema: public
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# supabase — schema `public`

17 objects · 17 with human docs.

| Object | Kind | Machine doc | Human doc | Status | Purpose |
|---|---|---|---|---|---|
| `ai_prompt_configs` | table | [ai_prompt_configs.schema.md](ai_prompt_configs.schema.md) | [ai_prompt_configs.md](ai_prompt_configs.md) | draft | Configurable prompt records resolved at runtime to supply system/user templates for AI flows by profile, provider, and action. |
| `ai_runs` | table | [ai_runs.schema.md](ai_runs.schema.md) | [ai_runs.md](ai_runs.md) | draft | A single AI model invocation capturing the flow, provider, payloads, token usage, and progress of a generation request. |
| `ai_suggestions` | table | [ai_suggestions.schema.md](ai_suggestions.schema.md) | [ai_suggestions.md](ai_suggestions.md) | draft | Block-level AI suggestions produced by an AI run, scoped to a master or tailored CV and pending review/apply. |
| `cover_letter_exports` | table | [cover_letter_exports.schema.md](cover_letter_exports.schema.md) | [cover_letter_exports.md](cover_letter_exports.md) | draft | Export job records for rendering a cover letter into a downloadable PDF or DOCX artifact. |
| `cover_letters` | table | [cover_letters.schema.md](cover_letters.schema.md) | [cover_letters.md](cover_letters.md) | draft | Cover letter content authored or generated for a specific tracked job, optionally linked to a tailored CV. |
| `cv_block_revisions` | table | [cv_block_revisions.schema.md](cv_block_revisions.schema.md) | [cv_block_revisions.md](cv_block_revisions.md) | draft | Immutable per-block revision history for a master or tailored CV, ordered per block. |
| `cv_templates` | table | [cv_templates.schema.md](cv_templates.schema.md) | [cv_templates.md](cv_templates.md) | draft | Catalog of CV templates available for preview rendering and export, identified by slug. |
| `exports` | table | [exports.schema.md](exports.schema.md) | [exports.md](exports.md) | draft | Export job records for rendering a tailored CV or master CV into a downloadable PDF or DOCX artifact. |
| `files` | table | [files.schema.md](files.schema.md) | [files.md](files.md) | draft | Metadata records for binary objects stored in Supabase storage buckets, owned by users. |
| `imports` | table | [imports.schema.md](imports.schema.md) | [imports.md](imports.md) | draft | Pipeline records tracking the parse of an uploaded source CV file into structured content for a master CV. |
| `job_status_history` | table | [job_status_history.schema.md](job_status_history.schema.md) | [job_status_history.md](job_status_history.md) | draft | Append-only log of status transitions for a job application, attributing each change to a user. |
| `jobs` | table | [jobs.schema.md](jobs.schema.md) | [jobs.md](jobs.md) | draft | Saved job postings a user is tracking, with application status and links to the tailored CV and cover letter for that job. |
| `master_cvs` | table | [master_cvs.schema.md](master_cvs.schema.md) | [master_cvs.md](master_cvs.md) | draft | A user's authoritative master CV holding the canonical content that tailored variants are generated from. |
| `subscriptions` | table | [subscriptions.schema.md](subscriptions.schema.md) | [subscriptions.md](subscriptions.md) | draft | Billing subscription records linking a user to an external payment-provider plan and its lifecycle state. |
| `tailored_cvs` | table | [tailored_cvs.schema.md](tailored_cvs.schema.md) | [tailored_cvs.md](tailored_cvs.md) | draft | A job-specific variant of a master CV produced for a single tracked job application. |
| `usage_counters` | table | [usage_counters.schema.md](usage_counters.schema.md) | [usage_counters.md](usage_counters.md) | draft | Per-user monthly counters tracking AI, generation, export, and storage consumption against plan entitlements. |
| `users` | table | [users.schema.md](users.schema.md) | [users.md](users.md) | draft | Application user accounts mapped to Supabase auth identities; the ownership root every domain table references. |
