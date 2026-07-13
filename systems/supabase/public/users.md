---
doc_class: human-object
object: supabase.public.users
written_against_schema_hash: "sha256:aefee2abaca5b3f73bf8062903148200a7e8c5df3240b632e65586a1324fdd58"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/users.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, referenced-by)"
depends_on:
  - supabase.public.users
  - supabase.public.ai_runs
  - supabase.public.ai_suggestions
  - supabase.public.cover_letter_exports
  - supabase.public.cover_letters
  - supabase.public.cv_block_revisions
  - supabase.public.exports
  - supabase.public.files
  - supabase.public.imports
  - supabase.public.job_status_history
  - supabase.public.jobs
  - supabase.public.master_cvs
  - supabase.public.subscriptions
  - supabase.public.tailored_cvs
  - supabase.public.usage_counters
---

# `supabase.public.users` (human doc)

The application-side user record, and the hub of the whole schema: 14 of
the other 16 tables carry a foreign key to `users.id` (machine doc,
Referenced-by). Structural facts below are from
[users.schema.md](users.schema.md); business meanings that the schema
does not carry are listed as ungrounded gaps in the enrich PR, not
guessed here.

## Grain

One row per `id` (primary key, `uuid`). `auth_user_id` is unique and
NOT NULL — at most one row per external auth identity. `email` is NOT
NULL but **not** unique at the schema level.

## Columns with grounded notes

- `auth_user_id` (`uuid`, unique): the join point to the auth identity;
  which auth system it refers to is not recorded in the schema
  (undocumented — see PR gaps).
- `locale` (`text`, default `'en'`), `onboarding_completed` (`boolean`,
  default `false`), `onboarding_state` (`jsonb`, default `'{}'`): value
  vocabularies beyond the defaults are undocumented.
- `created_at` / `updated_at`: `timestamp with time zone`, default
  `now()`.

## Join guidance (from FKs)

Every user-scoped table joins here via its `user_id` column →
`users.id`: `jobs`, `master_cvs`, `tailored_cvs`, `cover_letters`,
`cover_letter_exports`, `exports`, `imports`, `files`, `subscriptions`,
`usage_counters`, `ai_runs`, `ai_suggestions`, `cv_block_revisions`
(which also has `created_by_user_id`), and `job_status_history` (via
`changed_by_user_id`). All are listed in the machine doc's
Referenced-by table with their exact FK columns.

## Warnings

- Per-user counts should join on `users.id`, not `email`: `email` has no
  uniqueness guarantee.
- No row estimate is recorded for this table in the 2026-07-12 snapshot.
