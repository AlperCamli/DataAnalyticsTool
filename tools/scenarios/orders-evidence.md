# CVBuilder data model — `shop.orders` (staged evidence)

Fixture evidence for the CP-5 enrich scenario (AS-9 / AS-12). It grounds
five of the six columns and **deliberately says nothing about the meaning
of `discount`** — that omission is the AS-9 test: the enrich skill must
record `discount` as a gap, not invent a plausible one-liner.

## Table

`shop.orders` — one row per placed order. The commerce fact table; every
fulfilment and revenue number derives from it.

## Columns (customer-documented)

- `id` — surrogate primary key for the order.
- `customer_id` — the account that placed the order; references
  `shop.customers.id`.
- `status` — fulfilment state. The application constrains it to
  `new`, `paid`, `shipped`, `cancelled`.
- `net` — the order's net total in minor currency units, after
  discounts, excluding tax.
- `created_at` — when the order row was written.

## Join guidance

`orders.customer_id` → `customers.id` is the one supported join to the
customer. There is no direct order→product join; go through
`order_items`.
