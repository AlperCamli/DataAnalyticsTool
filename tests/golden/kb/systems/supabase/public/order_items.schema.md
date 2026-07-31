---
doc_class: machine-object
object: supabase.public.order_items
kind: table
schema_hash: "sha256:4bcf12644d7a6d42343d414f593118930d3f31c5adeb1e5039142d7230d8d988"
generated_at: 2026-07-11
source_mode: ddl-file
snapshot_version: "1"
status: machine
---

# `supabase.public.order_items`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.order_items` |
| Kind | table |
| Schema hash | `sha256:4bcf12644d7a6d42343d414f593118930d3f31c5adeb1e5039142d7230d8d988` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `bigint` | false | `nextval('order_items_id_seq'::regclass)` | — | — |
| 2 | `order_id` | `bigint` | false | — | — | — |
| 3 | `product_id` | `bigint` | false | — | — | — |
| 4 | `quantity` | `integer` | false | `1` | — | — |
| 5 | `unit_price_cents` | `integer` | false | — | Price at time of purchase; the product price may change later. | — |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `order_id` | [`public.orders`](orders.schema.md) | `id` |
| `product_id` | [`public.products`](products.schema.md) | `id` |

Unique constraints:

- `order_id`, `product_id`

Indexes: —

Check constraints: —

## Row estimate & freshness

Row estimate: 8240

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

—
