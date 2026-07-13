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

17 objects · 5 with human docs.

| Object | Kind | Machine doc | Human doc | Status | Purpose |
|---|---|---|---|---|---|
| `ai_prompt_configs` | table | [ai_prompt_configs.schema.md](ai_prompt_configs.schema.md) | — | — | — |
| `ai_runs` | table | [ai_runs.schema.md](ai_runs.schema.md) | — | — | — |
| `ai_suggestions` | table | [ai_suggestions.schema.md](ai_suggestions.schema.md) | — | — | — |
| `cover_letter_exports` | table | [cover_letter_exports.schema.md](cover_letter_exports.schema.md) | — | — | — |
| `cover_letters` | table | [cover_letters.schema.md](cover_letters.schema.md) | — | — | — |
| `cv_block_revisions` | table | [cv_block_revisions.schema.md](cv_block_revisions.schema.md) | — | — | — |
| `cv_templates` | table | [cv_templates.schema.md](cv_templates.schema.md) | — | — | — |
| `exports` | table | [exports.schema.md](exports.schema.md) | — | — | — |
| `files` | table | [files.schema.md](files.schema.md) | — | — | — |
| `imports` | table | [imports.schema.md](imports.schema.md) | — | — | — |
| `job_status_history` | table | [job_status_history.schema.md](job_status_history.schema.md) | — | — | — |
| `jobs` | table | [jobs.schema.md](jobs.schema.md) | [jobs.md](jobs.md) | draft | Saved job postings a user is tracking, with application status and links to the tailored CV and cover letter for that job. |
| `master_cvs` | table | [master_cvs.schema.md](master_cvs.schema.md) | [master_cvs.md](master_cvs.md) | draft | A user's authoritative master CV holding the canonical content that tailored variants are generated from. |
| `subscriptions` | table | [subscriptions.schema.md](subscriptions.schema.md) | [subscriptions.md](subscriptions.md) | draft | Billing subscription records linking a user to an external payment-provider plan and its lifecycle state. |
| `tailored_cvs` | table | [tailored_cvs.schema.md](tailored_cvs.schema.md) | [tailored_cvs.md](tailored_cvs.md) | draft | A job-specific variant of a master CV produced for a single tracked job application. |
| `usage_counters` | table | [usage_counters.schema.md](usage_counters.schema.md) | — | — | — |
| `users` | table | [users.schema.md](users.schema.md) | [users.md](users.md) | draft | Application user accounts mapped to Supabase auth identities; the ownership root every domain table references. |
