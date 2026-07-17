---
doc_class: metric
status: verified
last_verified: "2026-07-14 (drill)"
owner: "drill fixture"
depends_on:
  - drill.reporting.v_net_sales
contamination: null
---

## Definition

Net sales per customer, summed from line items.

## Implementations

`SELECT customer_id, net_total FROM reporting.v_net_sales` against
`drill.reporting.v_net_sales`.
