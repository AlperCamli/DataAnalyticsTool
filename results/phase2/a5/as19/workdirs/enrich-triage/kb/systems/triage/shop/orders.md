---
doc_class: human-object
object: triage.shop.orders
written_against_schema_hash: "sha256:33b2c8ec1d6f6a9fbc4e0d7b5a9c3f2e8d6c0a4b2f1e9d7c5b3a2f1e0d9c8b7a"
status: contaminated
last_verified: null
purpose: "One row per placed order; the commerce fact table."
column_purposes:
  customer_id: "The account that placed the order."
  total_cents: "Order total in minor units."
sources:
  - "customer doc: shop-data-model/orders.md"
depends_on:
  - triage.shop.orders
  - triage.shop.legacy_carts
contamination: {object: "triage.shop.legacy_carts", change: "object_removed", detail: "object_removed"}
---

# `triage.shop.orders`

## Join guidance

- Pre-migration orders carry their basket in `triage.shop.legacy_carts`, keyed
  by `id`; anything placed before the cutover has to be read through it.

## Warnings

- `total_cents` excludes shipping.
