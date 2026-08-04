---
doc_class: human-object
object: supabase.reporting.v_user_signups_by_day
written_against_schema_hash: "sha256:cba88302f11c160a969970b5b4717baa13862a2ca7098bfcdfc504066d0a1da6"
status: contaminated
last_verified: null
purpose: "New user accounts per UTC calendar day — the signup trend series."
column_purposes:
  signup_day: "UTC calendar date the accounts were created (`users.created_at` converted to UTC, then truncated)."
  new_users: "Accounts created on that date."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-7 task 7.0 / D-81)"
  - "machine doc: supabase.reporting.v_user_signups_by_day"
  - "human doc: supabase.public.users"
depends_on:
  - supabase.public.users
contamination: {object: "supabase.reporting.v_user_signups_by_day", change: "column_removed+definition_changed", detail: "column_removed: signup_day; definition_changed"}
---

# `supabase.reporting.v_user_signups_by_day`

## Grain

One row per UTC date on which at least one account was created. `users` has
no soft-delete column, so every account ever created is counted on its
signup date and nothing later removes it from the series.

## Reporting notes

- The bucket pins UTC in the view text (`(created_at AT TIME ZONE 'UTC')::date`)
  rather than inheriting the server's `TimeZone`, so the series does not move
  if that setting changes.
- **Days with no signups are absent, not zero.** The view groups over rows
  that exist; there is no calendar spine. A continuous axis has to be filled
  in by the consumer, and a naive line chart will otherwise join across gaps
  and imply activity that did not happen.

## Warnings

- **This is an aggregate view over a row-level-security-protected table.**
  `public.users` enforces per-user RLS, so the execution role reads zero rows
  from it directly; this view answers because it evaluates RLS as its owner.
  That is a deliberate, narrow opening, which is why the only columns here
  are a date and a count — there is no drill path from a number back to a
  person, and none should be inferred.
- **Small counts can still identify.** The estate is roughly two dozen users,
  so a day's count is often 1. A single-signup day plus any external
  knowledge of who joined when is identifying, even though no column names
  anyone. Treat low cells as sensitive rather than reportable.
