---
doc_class: human-object
object: triage.shop.imports
written_against_schema_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
status: contaminated
last_verified: null
purpose: "One row per uploaded file being turned into shop data."
column_purposes:
  status: "Import lifecycle state; see Warnings for the enum."
  parser_name: "Which parser handled the file."
sources:
  - "customer doc: shop-data-model/imports.md"
depends_on:
  - triage.shop.imports
contamination: {object: "triage.shop.imports", change: "stat_changed", detail: "stat_changed: checks"}
---

# `triage.shop.imports`

## Column meanings & enum decodings

- `status` — an import moves **`uploaded`** → **`parsing`** → **`parsed`**, or
  ends at **`failed`**. Those four are the whole vocabulary; nothing sits
  between `parsed` and the data being live.

## Warnings

- `parser_name` is null until a parser is chosen.
