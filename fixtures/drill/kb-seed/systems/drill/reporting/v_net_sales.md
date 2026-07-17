---
doc_class: human-object
object: drill.reporting.v_net_sales
written_against_schema_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
status: verified
last_verified: "2026-07-14 (drill)"
sources:
  - "drill fixture seed"
depends_on:
  - drill.reporting.v_order_totals
contamination: null
purpose: "Net sales per customer; the reporting rollup."
---

## Purpose

Per-customer net sales, aggregated from `drill.reporting.v_order_totals`.

## Reporting notes

Attribution backfills historically blended this with
`drill.shop.legacy_sessions` — undeclared on purpose in this fixture: the
drill expects exactly this mention to surface as an *undeclared possible
reference* (KB §6 step 5).
