---
doc_class: human-object
object: drill.shop.orders
written_against_schema_hash: "sha256:9285296560453134617aee00d956c35a593ebedd2a2e0f1912e2d175bf54f7b5"
status: draft
last_verified: null
sources:
  - "customer-provided, rene-reporter, 2026-08-07"
  - "machine sibling: systems/drill/shop/orders.schema.md (snapshot sha256:2af8bf2cafdc4791e15b3e397701c05c5f2bce0df8db01b08a86674bed30cf0c)"
  - "view definition: drill.reporting.v_order_totals (snapshot sha256:2af8bf2cafdc4791e15b3e397701c05c5f2bce0df8db01b08a86674bed30cf0c)"
depends_on:
  - drill.shop.customers
  - drill.shop.order_items
  - drill.reporting.v_order_totals
  - drill.reporting.v_net_sales
contamination: null
purpose: "One row per order; the header its `shop.order_items` lines hang from."
column_purposes:
  id: "Order identifier; primary key, referenced by `order_items.order_id`."
  customer_id: "The customer that placed the order; foreign key to `shop.customers.id`."
  net: "Order total in currency, with the `discount` deducted."
  discount: "A money amount, not a rate: what checkout removed from the order before `net` was stored."
  created_at: "Row insertion time; defaults to `now()`."
---

## Warnings

The `discount`/`net` relationship above is stated by the customer, not
enforced by the database. The snapshot records no check constraints on
this table, so nothing prevents a row whose `net` was stored before the
deduction, and nothing bounds `discount` to be non-negative or no larger
than the order total. Treat the deduction as a convention worth verifying
before a reconciliation depends on it, not as an invariant.

`discount` is nullable, and the evidence does not settle what a NULL
means here — "no discount applied" and "not recorded" are both consistent
with the column as it stands. Do not read NULL as zero without
confirming it.

`status` is `text` with a default of `'new'` and no check constraint in
the snapshot. Its value set is open and undocumented: `'new'` is the only
value any evidence supports. Do not treat it as a closed enum, and do not
infer the rest of the lifecycle from it.

## Reporting notes

The reporting rollups read neither of these columns.
`drill.reporting.v_order_totals` derives `items_total` as the sum of
`qty * price` over `drill.shop.order_items`, and
`drill.reporting.v_net_sales` aggregates that per customer; neither view
references `orders.net` or `orders.discount`. If the deduction convention
above holds, the reporting figure is therefore a pre-discount total, and
will exceed `sum(orders.net)` for any customer with a non-zero discount.
Pick the source that matches the question being asked, and reconcile the
two deliberately rather than assuming they agree.
