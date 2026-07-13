---
doc_class: human-object
object: supabase.public.users
written_against_schema_hash: "sha256:aefee2abaca5b3f73bf8062903148200a7e8c5df3240b632e65586a1324fdd58"
status: draft
last_verified: null
purpose: "Application user accounts mapped to Supabase auth identities; the ownership root every domain table references."
column_purposes:
  id: "Internal application user id; the FK target for every owned domain table."
  auth_user_id: "The Supabase auth user that owns this profile (unique)."
  email: "Primary email for login and notifications (PII)."
  full_name: "Display name shown across the product (PII)."
  locale: "UI locale preference; enum decoded in body."
  default_cv_language: "Language code used when seeding new CVs for this user."
  onboarding_completed: "Legacy paywall flag: whether onboarding was finished."
  created_at: "When the user record was created."
  updated_at: "When the user record was last updated."
  onboarding_state: "Guided-onboarding progress as JSONB; structure in body."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/users.md"
  - "app DDL: CV_Builder/backend/supabase/migrations/20260417121000_phase1_tables.sql (users_locale_check)"
  - "app code: CV_Builder/backend/supabase/migrations/20260708120000_onboarding_state.sql (onboarding_state shape)"
  - "machine doc: supabase.public.users"
depends_on:
  - supabase.public.master_cvs
  - supabase.public.tailored_cvs
  - supabase.public.jobs
  - supabase.public.subscriptions
contamination: null
---

# `supabase.public.users`

## Grain

One row per application user. `id` is the internal identifier that every
owned table joins to via its `user_id` column; `auth_user_id` is the
separate Supabase-auth identity (a `uuid`, unique) and is the seam to the
`auth.users` table, which is **not in this snapshot**. No soft-delete column
exists here — user rows are not hidden the way CVs are.

## Column meanings & enum decodings

- `locale` — UI language, DB-constrained to **`en` | `tr`** (`users_locale_check`).
- `default_cv_language` — a free-form language code used to seed new CVs; it
  is *not* constrained to the `locale` set.
- `onboarding_completed` vs `onboarding_state` — two distinct signals; do not
  conflate. `onboarding_completed` is the legacy boolean paywall flag;
  `onboarding_state` is the newer guided-tour progress record.
- `onboarding_state` (`jsonb`, default `'{}'`) — per the migration comment,
  shape is:
  ```json
  {
    "steps": { "<step_id>": "<ISO completion timestamp>" },
    "skipped_at": "<ISO>",
    "completed_at": "<ISO>"
  }
  ```
  `steps` maps a step id to its completion timestamp; `skipped_at` present
  ⇒ tour permanently dismissed; `completed_at` present ⇒ tour finished. The
  `'{}'` default means every user starts onboarding fresh.

## Join guidance

`users.id` is the fan-out hub: `master_cvs`, `tailored_cvs`, `jobs`,
`subscriptions` (and all other owned tables) carry a non-null `user_id` FK to
it. Join on `users.id = <table>.user_id`. To reach Supabase auth, join
`auth_user_id` to `auth.users.id` outside this estate.

## Reporting notes

- Deduplicate people by `users.id` (internal), not by `auth_user_id`.
- Active-user metrics should come from downstream activity tables, not from
  `onboarding_completed` alone.

## Warnings

- `email` and `full_name` are **PII** — exclude from shared reporting slices
  unless explicitly required.
- `onboarding_state` internal `steps` keys (the step-id vocabulary) are not
  enumerated in the DB — **gap**: step ids are defined in application code,
  not grounded here.
