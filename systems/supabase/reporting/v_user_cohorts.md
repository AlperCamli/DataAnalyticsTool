---
doc_class: human-object
object: supabase.reporting.v_user_cohorts
written_against_schema_hash: "sha256:fd10b9487cd3fb8b73aed002d33d75bf007dcb08ae09d2eb89023d3e223273d1"
status: draft
last_verified: null
purpose: "Signup cohort sizes by month, locale and default CV language, with onboarding completion."
column_purposes:
  signup_month: "Calendar month the user record was created."
  locale: "User's locale setting."
  default_cv_language: "User's default CV language."
  user_count: "Users in this cohort."
  onboarded_count: "How many completed onboarding."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_user_cohorts"
  - "human doc: supabase.public.users"
depends_on:
  - supabase.public.users
contamination: null
---

# `supabase.reporting.v_user_cohorts`

## Grain

One row per (signup_month, locale, default_cv_language) combination.

## Reporting notes

- Acquisition shape over time, and the denominator for any per-user rate.
- `onboarded_count / user_count` is activation per cohort — the clearest early
  signal of whether a change to onboarding worked.
- `locale` against `default_cv_language` shows where users work in a language
  other than their interface language, which is a localisation signal.

## Warnings

- **These are aggregate views over row-level-security-protected tables.** The
  base tables (`public.*`) enforce per-user RLS, so the execution role reads
  **zero rows** from them directly. These views answer anyway because a view
  evaluates RLS as its *owner*, and they are owned by a role that bypasses it.
  That is a deliberate, narrow opening — and it is why every column here is an
  aggregate or a non-identifying dimension. Do not expect to drill from these
  numbers to a person: no view exposes `user_id`, an email, a name, or any free
  text a user wrote.
- **Small counts can still identify.** The estate is ~24 users. A group of size
  1–2 is potentially personal even though no column names anyone; treat such
  cells as sensitive rather than reportable.
- **This is the most granular view here.** Three dimensions over ~24 users means
  many cells of size 1. A cohort of one is a person, even without a name column.
  Aggregate further before sharing.
- Counts user *records*, not active users; there is no activity filter.
