---
doc_class: human-object
object: supabase.public.subscriptions
written_against_schema_hash: "sha256:aa2bf4a4a88ec655bbb5e0ff78af326ac6c5f20da62f6803cfaa4940fb8c5972"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/subscriptions.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes)"
depends_on:
  - supabase.public.subscriptions
  - supabase.public.users
---

# `supabase.public.subscriptions` (human doc)

Billing subscriptions mirrored from an external provider: rows carry
`provider`, provider-side customer/subscription ids, a `plan_code`, a
`status`, and the current period bounds. Structural facts are from
[subscriptions.schema.md](subscriptions.schema.md).

## Grain

One row per `id` (primary key, `uuid`). Partial unique index
`subscriptions_one_active_per_user_idx` (`user_id` unique WHERE
`status = ANY (ARRAY['active','trialing'])`): **at most one
subscription per user in status `'active'` or `'trialing'`**. A user
may have any number of rows in other statuses. No row estimate in the
2026-07-12 snapshot.

## Status column — what is actually decodable

The partial-unique predicate attests two values: `'active'` and
`'trialing'` — and attests that the schema treats exactly these two as
the "current subscription" states. The rest of the vocabulary
(canceled? past_due? …) is undocumented (see PR gaps), as are
`provider` and `plan_code` value sets. `cancel_at_period_end`
(`boolean`, default `false`) and the nullable
`current_period_start`/`current_period_end` are provider-shaped fields
whose update semantics the schema does not describe.

## Join guidance (from FKs and indexes)

- `user_id` → `users.id` (NOT NULL). "Current subscription of a user" =
  the row (at most one) with `status IN ('active','trialing')`.
- Provider-side lookups are indexed: `(provider, provider_customer_id)`
  and `(provider, provider_subscription_id)`, each WHERE the id IS NOT
  NULL. Both provider ids are nullable.

## Warnings

- Subscriber counts: `COUNT(DISTINCT user_id) WHERE status IN
  ('active','trialing')` is the only schema-guaranteed-deduplicated
  form; counting rows without the status filter mixes historical rows
  in.
- Plan-level revenue cannot be computed from this table: there is no
  amount/price column; `plan_code` meanings and prices need a customer
  source.
