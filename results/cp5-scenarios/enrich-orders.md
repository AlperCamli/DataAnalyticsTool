---
doc_class: human-object
object: shop.orders
status: draft
sources:
  - "customer doc: evidence/orders.md"
  - "machine sibling: systems/drill/shop/orders.schema.md (snapshot sha256:2af8bf2c…30cf0c)"
depends_on:
  - drill.shop.orders
  - drill.shop.customers
  - drill.shop.order_items
purpose: "One row per placed order; the commerce fact table every fulfilment and revenue number derives from."
column_purposes:
  id: "Surrogate primary key for the order."
  customer_id: "The account that placed the order; references shop.customers.id."
  status: "Fulfilment state; see Status values for the vocabulary and Warnings for its enforcement."
  net: "The order's net total after discounts, excluding tax; see Warnings for the units question."
  created_at: "When the order row was written."
---

## Status values

The application constrains `status` to four values:

- `new` — default for a newly written row (`'new'::text` is the column
  default in the snapshot).
- `paid`
- `shipped`
- `cancelled`

Source: customer doc `evidence/orders.md`. The customer doc states only
the value list, not per-value semantics, so no meaning beyond the label is
asserted here. See Warnings — this vocabulary is not enforced by the
database.

## Join guidance

`orders.customer_id` → `customers.id` is the one supported join to the
customer; it is backed by a foreign key in the snapshot as well as by the
customer doc.

There is no direct order → product join. Route through
`drill.shop.order_items`, which references this table via `order_id`.

## Warnings

- **`discount` is undocumented.** `discount` (`numeric(12,2)`, nullable)
  exists in the snapshot but the customer doc says nothing about it. Its
  meaning is unresolved: amount vs. rate, whether it is already deducted
  from `net`, and what NULL signifies. No purpose is asserted for it —
  filed as fault-ledger issue `d783f7e9-3fab-4c33-9082-527405c3f726`
  (`missing_doc`, routed to data-team). Unblocked by the DDL that
  introduced the column, checkout code computing order totals, or a
  customer-doc revision. Do not infer a value for it from `net`.

- **`status` is not a closed enum at the database level.** The column is
  plain `text` with no `CHECK` constraint in the snapshot; the four values
  above are an *application* constraint reported by the customer doc. No
  migration was available to confirm it. Treat out-of-vocabulary values as
  possible, and do not rely on the list being exhaustive for historical
  rows.

- **`net` units are in tension with the column type.** The customer doc
  says `net` is "in minor currency units", but the snapshot types it
  `numeric(12,2)` — two decimal places, which is how major units are
  normally stored. One of the two is wrong and the evidence does not
  settle which. Confirm against the DDL or checkout code before using
  `net` in any revenue figure.

- The currency of `net` is not documented, and no currency column exists
  on this table.
