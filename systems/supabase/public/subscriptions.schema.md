---
doc_class: machine-object
object: supabase.public.subscriptions
kind: table
schema_hash: "sha256:aa2bf4a4a88ec655bbb5e0ff78af326ac6c5f20da62f6803cfaa4940fb8c5972"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.subscriptions`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.subscriptions` |
| Kind | table |
| Schema hash | `sha256:aa2bf4a4a88ec655bbb5e0ff78af326ac6c5f20da62f6803cfaa4940fb8c5972` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | — |
| 2 | `user_id` | `uuid` | false | — | — | — |
| 3 | `provider` | `text` | false | — | — | — |
| 4 | `provider_customer_id` | `text` | true | — | — | — |
| 5 | `provider_subscription_id` | `text` | true | — | — | — |
| 6 | `plan_code` | `text` | false | — | — | — |
| 7 | `status` | `text` | false | — | — | — |
| 8 | `current_period_start` | `timestamp with time zone` | true | — | — | — |
| 9 | `current_period_end` | `timestamp with time zone` | true | — | — | — |
| 10 | `cancel_at_period_end` | `boolean` | false | `false` | — | — |
| 11 | `created_at` | `timestamp with time zone` | false | `now()` | — | — |
| 12 | `updated_at` | `timestamp with time zone` | false | `now()` | — | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints: —

Indexes:

- `CREATE INDEX subscriptions_provider_customer_id_idx ON public.subscriptions USING btree (provider, provider_customer_id) WHERE (provider_customer_id IS NOT NULL)`
- `CREATE INDEX subscriptions_provider_subscription_id_idx ON public.subscriptions USING btree (provider, provider_subscription_id) WHERE (provider_subscription_id IS NOT NULL)`
- `CREATE INDEX subscriptions_status_idx ON public.subscriptions USING btree (status)`
- `CREATE INDEX subscriptions_user_id_idx ON public.subscriptions USING btree (user_id)`
- `CREATE UNIQUE INDEX subscriptions_one_active_per_user_idx ON public.subscriptions USING btree (user_id) WHERE (status = ANY (ARRAY['active'::text, 'trialing'::text]))`

## Row estimate & freshness

Row estimate: —

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

—
