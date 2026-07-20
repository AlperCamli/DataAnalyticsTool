---
doc_class: human-object
object: supabase.reporting.v_ai_tokens_by_month
written_against_schema_hash: "sha256:0bd767c407e3273723c4e62a1f96d03fe0d846ba5c8b211ab519010d00535706"
status: draft
last_verified: null
purpose: "Monthly AI token spend by provider, with a count of runs that did not complete."
column_purposes:
  month: "Calendar month of `started_at`."
  provider: "AI provider that served the runs."
  total_tokens: "Sum of billed tokens for the month/provider."
  run_count: "Runs started in that month."
  non_completed_count: "Runs whose status is anything other than `completed`."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_ai_tokens_by_month"
  - "human doc: supabase.public.ai_runs"
depends_on:
  - supabase.public.ai_runs
contamination: null
---

# `supabase.reporting.v_ai_tokens_by_month`

## Grain

One row per (month, provider) pair with at least one run started.

## Reporting notes

- The month-over-month cost trend, and the view to use for budget questions.
- `total_tokens / run_count` is average cost per invocation — a rise means
  prompts or outputs are growing, which is usually a product change rather than
  a usage change.
- `non_completed_count` includes both `pending` and `failed`; a persistently
  high figure alongside rising tokens means paying for work that is not
  landing.

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
- Attributed by **`started_at`**, so a run spanning a month boundary counts in
  the month it began.
- `non_completed_count` conflates *still running* with *failed*. Use
  `v_ai_runs_by_flow`, which splits by `status`, to tell them apart.
