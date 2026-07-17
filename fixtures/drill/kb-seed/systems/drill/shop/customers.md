---
doc_class: human-object
object: drill.shop.customers
written_against_schema_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
status: verified
last_verified: "2026-07-14 (drill)"
sources:
  - "drill fixture seed"
depends_on:
  - drill.shop.orders
contamination: null
purpose: "One row per registered customer."
column_purposes:
  email: "Login identity; unique in practice, not constrained."
---

## Purpose

One row per registered customer; joined from `drill.shop.orders` via
`customer_id`.

## Grain

One row per customer id.
