---
doc_class: human-object
object: triage.shop.exports
written_against_schema_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
status: contaminated
last_verified: null
purpose: "One row per export job; the artifact-production fact table."
column_purposes:
  order_id: "The order whose contents were exported."
  format: "Output file format requested; see Warnings for the value set."
  status: "Job lifecycle state; see Warnings for the enum."
sources:
  - "customer doc: shop-data-model/exports.md"
  - "inferred from column names"
depends_on:
  - triage.shop.exports
  - triage.shop.orders
contamination: {object: "triage.shop.exports", change: "stat_changed", detail: "stat_changed: checks"}
---

# `triage.shop.exports`

## Column meanings & enum decodings

- `status` — the job lifecycle: **`processing`** while the worker holds it,
  **`completed`** once the file exists, **`failed`** when the worker gave up.
  Exactly these three; there is no queued state.
- `format` — **`pdf`** or **`csv`**. Nothing else is accepted.

## Warnings

- A `completed` row without a file is a bug, not a state.
