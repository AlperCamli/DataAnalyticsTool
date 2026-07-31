---
doc_class: machine-object
object: supabase.public.orders
kind: table
schema_hash: "sha256:6335fe5052d178367ba3f8647035f827791721a7d080efe2816c8a4605027e69"
generated_at: 2026-07-11
source_mode: ddl-file
snapshot_version: "1"
status: machine
---

# `supabase.public.orders`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.orders` |
| Kind | table |
| Schema hash | `sha256:6335fe5052d178367ba3f8647035f827791721a7d080efe2816c8a4605027e69` |

One row per checkout; immutable after payment settles.

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `bigint` | false | `nextval('orders_id_seq'::regclass)` | — | — |
| 2 | `user_id` | `uuid` | false | — | — | — |
| 3 | `status` | `text` | false | `'pending'::text` | pending \| paid \| cancelled \| refunded | — |
| 4 | `total_cents` | `integer` | false | — | Grand total in cents, tax included. | — |
| 5 | `notes` | `text` | true | — | — | — |
| 6 | `created_at` | `timestamp with time zone` | false | `now()` | — | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints: —

Indexes: —

Check constraints: —

## Row estimate & freshness

Row estimate: 1250

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

| Object | Via |
|---|---|
| [`supabase.public.order_items`](order_items.schema.md) | `order_id` |
