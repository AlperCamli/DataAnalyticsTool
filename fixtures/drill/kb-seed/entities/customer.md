---
doc_class: entity
status: verified
last_verified: "2026-07-14 (drill)"
maps:
  - { object: "drill.shop.customers", role: system-of-record, keys: [id] }
depends_on:
  - drill.shop.customers
contamination: null
---

## What it is

The purchasing customer; system of record is `drill.shop.customers`.

## Keys & join paths

Join orders to customers on `customer_id = id`.
