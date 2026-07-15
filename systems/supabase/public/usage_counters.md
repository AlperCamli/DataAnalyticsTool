---
doc_class: human-object
object: supabase.public.usage_counters
written_against_schema_hash: "sha256:a4d5722f8765986984bc078fbbc2c86f5d61231eed158555f8036067509b7eee"
status: draft
last_verified: null
purpose: "Per-user monthly counters tracking AI, generation, export, and storage consumption against plan entitlements."
column_purposes:
  id: "Internal counter-row id."
  user_id: "User whose usage is tracked (FK to users.id)."
  period_month: "First day of the calendar month this row covers."
  tailored_cv_generations_count: "Tailored CV generations consumed in the period."
  exports_count: "Export jobs completed in the period."
  ai_actions_count: "AI block actions invoked in the period."
  storage_bytes_used: "Total bytes of files stored as of this period."
  updated_at: "When this counter was last incremented."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/usage_counters.md"
  - "app DDL: CV_Builder/backend/supabase/migrations (usage_counters unique (user_id, period_month), non-negative + month-truncation checks, increment_usage_counters function)"
  - "machine doc: supabase.public.usage_counters"
depends_on:
  - supabase.public.users
contamination: null
---

# `supabase.public.usage_counters`

## Grain

One row **per user per calendar month** (unique on `(user_id, period_month)`).
A CHECK enforces `period_month = date_trunc('month', period_month)` — it is
always the first day of the month. All four counters are CHECK-constrained
`>= 0`. Rows are upserted and incremented atomically via the
`public.increment_usage_counters` SECURITY DEFINER function, which clamps to
non-negative.

## Column meanings & enum decodings

No enums. The counters are running monthly totals of billable activity:

- `tailored_cv_generations_count` — AI tailored-draft generations (relates to
  `supabase.public.ai_runs` of the tailoring flows).
- `exports_count` — completed export jobs (relates to
  `supabase.public.exports`).
- `ai_actions_count` — AI block actions (relates to
  `supabase.public.ai_suggestions`/`ai_runs`).
- `storage_bytes_used` — a **point-in-time** snapshot of stored bytes "as of
  this period" (see `supabase.public.files`), not a monthly delta like the
  other three.

## Join guidance

- Owner: `usage_counters.user_id` → `supabase.public.users.id`. No other FKs.
- These are pre-aggregated summaries; the underlying events live in `ai_runs`,
  `exports`, and `files`. Prefer these counters for entitlement checks and the
  source tables for exact audits.

## Reporting notes

- To compare consumption against plan limits, join `user_id` to the user's
  active `supabase.public.subscriptions` row and its `plan_code`.
- Filter by `period_month` for a given month; a missing row means zero
  recorded activity that month (rows are created on first increment).

## Warnings

- `storage_bytes_used` is a snapshot, **not additive** across months — do not
  sum it over `period_month`.
- The counters are maintained by application increments, so they can drift from
  a live recount of `ai_runs`/`exports`/`files`; treat them as entitlement
  bookkeeping, not a certified event count.
