---
doc_class: human-object
object: shop.orders
status: draft
sources:
  - "customer doc: evidence/orders.md"
  - "machine sibling: systems/drill/shop/orders.schema.md (snapshot sha256:2af8bf2cafdc4791e15b3e397701c05c5f2bce0df8db01b08a86674bed30cf0c)"
depends_on:
  - drill.shop.orders
  - drill.shop.customers
  - drill.shop.order_items
purpose: "One row per placed order; the commerce fact table every fulfilment and revenue number derives from."
column_purposes:
  id: "Surrogate primary key for the order."
  customer_id: "The account that placed the order."
  status: "Fulfilment state; see Warnings — application-constrained, not DB-enforced."
  net: "The order's net total after discounts, excluding tax; see Warnings on units."
  created_at: "When the order row was written."
---

## Enum decoding

`status` — fulfilment state, constrained by the application to:

- `new` — order placed, not yet paid (the column default, `'new'::text`).
- `paid`
- `shipped`
- `cancelled`

Source: `evidence/orders.md`. The database does not enforce this — see
Warnings.

## Join guidance

`orders.customer_id` → `customers.id` is the one supported join to the
customer. This is both a declared foreign key in the snapshot and the
join the customer doc endorses.

There is no direct order → product join. Route through
`drill.shop.order_items`, which references `orders.id` via `order_id`.

## Warnings

**`discount` has no grounded meaning — do not interpret it.** The column
exists in the snapshot (`numeric(12,2)`, nullable, no default), but the
staged evidence documents every other column and says nothing about this
one. Unresolved: whether it holds an absolute amount, a percentage, or a
rate; its currency units; whether it is already subtracted from `net`;
and what NULL means (no discount vs. unknown). Filed as
`flag_gap(missing_doc)`, issue `aca5b3d5-da32-4b1e-971b-a2539f493e85`,
routed to `data-team`. No `column_purposes` entry is written for it.

**`status` is not a closed enum at the database level.** The column is
plain `text` with default `'new'::text` and no CHECK constraint in the
snapshot. The four values above are grounded only in the customer doc as
an *application* constraint, so rows outside that set are possible.
Do not rely on it as an exhaustive set without a DDL constraint or
observed-value evidence.

**`net` units are in tension between the two sources.** The customer doc
states the value is "in minor currency units"; the snapshot types the
column `numeric(12,2)`, whose two decimal places are the conventional
shape for *major* units. Neither source settles it — the doc is not a DDL
constraint and the type is not a unit declaration. Confirm against the
pricing code or a migration before using `net` in any revenue figure.
