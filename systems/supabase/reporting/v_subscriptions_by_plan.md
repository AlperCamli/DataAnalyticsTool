---
doc_class: human-object
object: supabase.reporting.v_subscriptions_by_plan
written_against_schema_hash: "sha256:1abbef8441881fd2ac21600b36be45426643c2b38c1609fe6d31fb9da753b853"
status: draft
last_verified: null
purpose: "Subscription mix by plan and status, with pending cancellations."
column_purposes:
  plan_code: "Plan identifier."
  status: "Subscription status."
  subscription_count: "Subscriptions matching this plan/status."
  cancelling_count: "How many are flagged to cancel at period end."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_subscriptions_by_plan"
  - "human doc: supabase.public.subscriptions"
depends_on:
  - supabase.public.subscriptions
contamination: null
---

# `supabase.reporting.v_subscriptions_by_plan`

## Grain

One row per (plan_code, status) pair observed.

## Reporting notes

- The revenue-mix view. `cancelling_count` against `subscription_count` on
  active rows is forward-looking churn — these have not cancelled yet, so it is
  the number worth acting on.

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
- **No provider identifiers are exposed here** (no customer or subscription
  ids) — deliberately, since they are personal. This view cannot be joined back
  to an individual account.
- Counts subscriptions, not distinct payers; one user with two subscriptions
  counts twice.
- Carries no monetary amount — pair `plan_code` with pricing held elsewhere.
