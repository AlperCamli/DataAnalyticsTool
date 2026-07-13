---
doc_class: human-object
object: supabase.public.subscriptions
written_against_schema_hash: "sha256:aa2bf4a4a88ec655bbb5e0ff78af326ac6c5f20da62f6803cfaa4940fb8c5972"
status: draft
last_verified: null
purpose: "Billing subscription records linking a user to an external payment-provider plan and its lifecycle state."
column_purposes:
  id: "Internal subscription id."
  user_id: "Owning user (FK to users.id)."
  provider: "External billing provider name (e.g. Stripe)."
  provider_customer_id: "Customer id on the provider side."
  provider_subscription_id: "Subscription id on the provider side."
  plan_code: "Internal product plan code purchased."
  status: "Current lifecycle status; see body for grounding limits."
  current_period_start: "Start of the current billing period."
  current_period_end: "End of the current billing period."
  cancel_at_period_end: "Whether the subscription will cancel at period end."
  created_at: "When the subscription record was created."
  updated_at: "When the subscription record was last updated."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/subscriptions.md"
  - "app DDL: CV_Builder/backend/supabase/migrations/20260417121000_phase1_tables.sql (subscriptions_one_active_per_user_idx)"
  - "machine doc: supabase.public.subscriptions"
depends_on:
  - supabase.public.users
contamination: null
---

# `supabase.public.subscriptions`

## Grain

One row per subscription record for a user. A user can accumulate several over
time (renewals, plan changes, re-subscribes), but a partial unique index
enforces **at most one *active* subscription per user**
(`subscriptions_one_active_per_user_idx`: unique on `user_id` where
`status in ('active','trialing')`).

## Column meanings & enum decodings

- `status` — lifecycle state. **The DB does not CHECK-constrain this column**,
  so there is no closed enum to publish. Grounded values: **`active`** and
  **`trialing`** are the "active" states (from the partial unique index
  above); the customer model additionally lists **`canceled`** as an example.
  The complete provider-driven vocabulary (e.g. `past_due`, `incomplete`,
  `unpaid`) is **not grounded here** — a named gap; do not assume a fixed set.
- `provider` — free text; the customer model gives Stripe as the example. Not
  DB-enumerated.
- `plan_code` — internal product plan identifier. The set of valid codes is
  **not grounded** in the DB or the provided docs — gap.
- `provider_customer_id` / `provider_subscription_id` — the provider-side ids;
  both nullable and indexed *per provider* (`(provider, provider_*_id)` where
  not null), so uniqueness is scoped within a provider.
- `current_period_start` / `current_period_end` — nullable; absent for records
  with no established billing period yet.

## Join guidance

- Owner: `subscriptions.user_id` → `supabase.public.users.id`. There are no
  inbound FKs (nothing references `subscriptions`).
- To reconcile against the billing provider, match on
  `(provider, provider_subscription_id)`.

## Reporting notes

- "Currently paying / trialing users" = rows with `status in ('active',
  'trialing')` (one per user by the unique index). Do not `count(*)` all
  rows per user — historical rows inflate it.
- Churn signals: `cancel_at_period_end = true` flags a scheduled cancel that
  has not yet ended; a terminal `status` is a separate, already-ended state.

## Warnings

- `status` is **not** a DB enum — treat any set as open and provider-defined
  (gap above). Certified revenue/subscription metrics must pin the exact
  status values they count and cite the provider's own status vocabulary.
- No `is_deleted`/soft-delete here; lifecycle is expressed through `status`.
