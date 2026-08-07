---
doc_class: human-object
object: triage.shop.imports
written_against_schema_hash: "sha256:22a1b7db0c5e5f8eab3d9c6a4f8b2e1d7c5b9f3a1e0d8c6b4a2f1e0d9c8b7a6e"
status: draft
last_verified: null
purpose: "One row per uploaded file being turned into shop data."
column_purposes:
  status: "Import lifecycle state; see Warnings for the enum."
  parser_name: "Which parser handled the file."
sources:
  - "customer doc: shop-data-model/imports.md"
  - "app DDL: CHECK constraint on shop.imports.status, read from .contextlayer/snapshots/triage.json (captured 2026-08-06)"
depends_on:
  - triage.shop.imports
contamination: null
---

# `triage.shop.imports`

## Column meanings & enum decodings

- `status` — the database admits exactly six values: **`uploaded`**,
  **`parsing`**, **`parsed`**, **`reviewed`**, **`converted`**, **`failed`**.
  Four of them are decoded by the customer doc: an import lands `uploaded`,
  moves to `parsing` while a parser reads it, reaches `parsed` once it has
  been read, and ends at `failed` where it stopped. `reviewed` and
  `converted` are legal values that no source read for this repair decodes —
  see Warnings.

## Warnings

- **`reviewed` and `converted` are undecoded.** The `CHECK` constraint proves
  they are legal `status` values; nothing read here says what they mean or
  where they fall in the lifecycle, and their names are not evidence. A
  migration or the import worker's own code would settle it.
- This doc previously listed four values as "the whole vocabulary" and said
  nothing sits between `parsed` and the data being live. Both claims are
  wrong against the current schema: the `CHECK` constraint on `status`
  admits six, and two of the additions sit exactly in the range the doc
  ruled out. Where the customer doc and the constraint disagree, the
  constraint is what the database enforces and wins. Anything that treats
  `parsed` as terminal, or as the point the data goes live, will miss rows.
- `parser_name` is null until a parser is chosen.
