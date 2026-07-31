---
doc_class: machine-object
object: supabase.public.products
kind: table
schema_hash: "sha256:24998437263dcece62b6e2d32773cf27f08589be15297ccf232471c1a6b6a32f"
generated_at: 2026-07-11
source_mode: ddl-file
snapshot_version: "1"
status: machine
---

# `supabase.public.products`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.products` |
| Kind | table |
| Schema hash | `sha256:24998437263dcece62b6e2d32773cf27f08589be15297ccf232471c1a6b6a32f` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `bigint` | false | `nextval('products_id_seq'::regclass)` | — | — |
| 2 | `sku` | `text` | false | — | — | — |
| 3 | `name` | `text` | false | — | — | — |
| 4 | `price_cents` | `integer` | false | — | Current list price in cents. | — |
| 5 | `discontinued_at` | `timestamp with time zone` | true | — | — | — |

## Keys & indexes

Primary key: `id`

Foreign keys: —

Unique constraints:

- `sku`

Indexes: —

Check constraints: —

## Row estimate & freshness

Row estimate: 342

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

| Object | Via |
|---|---|
| [`supabase.public.order_items`](order_items.schema.md) | `product_id` |
