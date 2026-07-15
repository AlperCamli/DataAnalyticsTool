---
doc_class: entity
status: draft
last_verified: null
aliases: [purchase, paid conversion, key event]
maps:
  - { object: "ga4.standard.purchase",           role: analytics-conversion-event,  keys: [] }
  - { object: "ga4.standard.keyEvents:purchase", role: analytics-conversion-metric, keys: [] }
  - { object: supabase.public.subscriptions,     role: transactional-record,        keys: [id] }
join_guidance: per-target
sources:
  - "machine doc: ga4.standard.purchase (is_key_event: true); ga4.standard.keyEvents:purchase"
  - "KB: systems/ga4/events.md (purchase population gap — app emits payment_completed, not purchase)"
  - "app code: CV_Builder/frontend/src/app/integration/analytics.ts (payment_completed carries checkout_session_id, plan_code, client-computed value/currency; purchase never emitted)"
  - "machine doc: supabase.public.subscriptions (no transaction_id / amount; keys provider_subscription_id, plan_code)"
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/subscriptions.md"
depends_on:
  - ga4.standard.purchase
  - ga4.standard.keyEvents:purchase
  - supabase.public.subscriptions
  - supabase.public.exports
  - supabase.public.tailored_cvs
  - supabase.public.users
contamination: null
---

# conversion

## What it is

A user completing a paid or otherwise valuable action — primarily a
**purchase** (paid plan). GA4 records the analytics conversion; Supabase
`subscriptions` is the billing system-of-record. Secondary valuable actions
(`cv_exported`, `tailored_cv_generated`) are recommended-but-not-registered key
events, not purchases.

## System map (routing table)

- `ga4.standard.purchase` (key event) / `ga4.standard.keyEvents:purchase`
  (count) — **analytics conversion signal**: how many conversions, revenue
  (`value`/`currency`, USD), by traffic source. **Population is ungrounded**
  (ga4 events): the app emits **`payment_completed`**, not `purchase`; whether
  `purchase` is produced server-side, via GTM, or by the payment provider is
  unknown.
- `supabase.public.subscriptions` — **transactional record (system-of-record)**
  of the paid relationship: which user, `plan_code`, `status`
  (`active`/`trialing`/…), provider ids. At most one active per user. **No
  `transaction_id`, no amount column** — revenue is not stored in Supabase.
- Secondary: `cv_exported` ↔ `supabase.public.exports`; `tailored_cv_generated`
  ↔ `supabase.public.tailored_cvs`.

Routing: conversion counts / revenue / attribution → GA4; who paid for what and
billing lifecycle → Supabase `subscriptions`.

## Keys & join paths

- Supabase: `subscriptions.id` (PK); owner `user_id → users.id`; provider
  reconcile `(provider, provider_subscription_id)`.
- GA4 purchase: event params `transaction_id`, `value`, `currency` (population
  unknown, per above).
- **No shared row-level key exists** between a GA4 conversion and a
  `subscriptions` row: GA4 carries no `user_id` (User-ID off — see
  `entities/user.md`), `subscriptions` does not store any GA4 id or
  `checkout_session_id`, and `purchase.transaction_id` has no documented equal
  in Supabase. `plan_code` appears on both the client `payment_completed`
  payload and `subscriptions`, but it names a plan class, not a transaction.
  **There is no documented blend key.**

## Cross-source resolution rule

Only **aggregate reconciliation** is supported — for both recurring and ad-hoc.
Compute GA4 `keyEvents:purchase` (count) and purchase `value` (revenue), and
independently the Supabase count of subscription rows entering a paid state,
over the **same date range**, then compare by magnitude. Do **not** blend or
join on a shared key — none exists, and the GA4 `purchase` population gap means
the two may not even count the same events. Row-level attribution (which GA4
conversion is which subscription) is an Ungrounded gap.

## Caveats

- **Purchase population gap** (ga4 events): reconcile GA4 `purchase` against
  `subscriptions` before treating them as one business event.
- **Revenue lives only in GA4 / the provider:** `subscriptions` has no amount;
  GA4 `value` is **client-computed** (`normalizePlanValue` in analytics.ts) and
  trials send `value: 0`.
- **Grain mismatch:** `subscriptions` is lifecycle state (≤1 active per user;
  renewals update in place), not a per-payment ledger — counting "conversions"
  needs a pinned rule (e.g. first paid `created_at`), and there is no
  subscription status-history table.
- **`status` is not a DB enum** (subscriptions doc) — pin the exact values you
  count.
- No GA4 user identity → no per-user conversion funnel across systems.
