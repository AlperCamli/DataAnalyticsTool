---
doc_class: human-group
object: gsc.dimensions
written_against_schema_hash: "sha256:674ad28dc800a15035bab2fdfb0c18ebfe567f63ced23b0564e294e619254b71"
status: draft
last_verified: null
purpose: "The dimensions you can group/filter Search Analytics query results by — how CVBuilder's Google Search traffic is sliced."
object_purposes:
  "gsc.standard.country": "Country the search was made from, as an ISO 3166-1 alpha-3 code."
  "gsc.standard.date": "The day the search activity occurred (one row per day when grouped)."
  "gsc.standard.device": "Device class the search happened on: DESKTOP, MOBILE, or TABLET."
  "gsc.standard.page": "The canonical URI on jobspecificcv.com that appeared in / was clicked from results."
  "gsc.standard.query": "The search query string the user typed into Google."
  "gsc.standard.searchAppearance": "The search result feature/appearance the link showed as (e.g. a rich result type)."
sources:
  - "vendor doc: https://developers.google.com/webmaster-tools/v1/searchanalytics/query"
  - "vendor doc: https://support.google.com/webmasters/answer/7042828"
  - "KB: conventions.md (GSC query surface, dataState D-31)"
depends_on: []
contamination: null
---

# gsc — dimensions

Group of the six Search Analytics API dimensions (`searchanalytics.query`)
by which CVBuilder's Google Search performance can be grouped or filtered.
The verified property is `sc-domain:jobspecificcv.com` (see the system
[index](index.md)). These are a fixed vendor-defined set — there is no
SQL surface and no custom dimensions (see [conventions](../../conventions.md)).

## Grain

One row per distinct combination of the dimensions you group by, over the
requested date range. Rows with no data are omitted — per the query API
reference, "When date is one of the dimensions, any days without data are
omitted from the result list."

## Dimension meanings & value encodings

Facts (namespace, data type) live in the machine sibling
[dimensions.schema.md](dimensions.schema.md); this section carries only
value encodings and caveats the one-liners cannot.

- `gsc.standard.country` — value is a **3-letter ISO 3166-1 alpha-3** code
  ("Filter against the specified country, as specified by 3-letter country
  code (ISO 3166-1 alpha-3)"). Note this is alpha-**3** (e.g. `usa`, `gbr`),
  not the alpha-2 codes used elsewhere.
- `gsc.standard.date` — the day of the search. Emitted as `YYYY-MM-DD`.
  **Reporting timezone is not grounded here** — see Warnings.
- `gsc.standard.device` — one of exactly three values: **`DESKTOP`,
  `MOBILE`, `TABLET`** (vendor-enumerated, uppercase).
- `gsc.standard.page` — the **canonical URI** of the result on the property.
  When `page` is a grouping dimension, all impressions for the same page are
  combined into one impression for that page (aggregation `byPage`; see
  [metrics](metrics.md) and Join guidance).
- `gsc.standard.query` — the raw search string. Google withholds rare /
  privacy-sensitive queries, so summing `clicks`/`impressions` grouped by
  `query` under-counts the property total (anonymized-query gap).
- `gsc.standard.searchAppearance` — the result feature a link appeared as.
  The vendor does not publish a static value list: "To see a list of
  available values, run a query grouped by 'searchAppearance'." The concrete
  appearance types for this property are therefore a **runtime gap** (not
  enumerable from docs).

## Join guidance

There are no SQL joins here — this is an API group, not a table.
"Joining" means choosing which dimensions to group by in a single
`searchanalytics.query` request. Cross-dimension notes:

- Grouping or filtering by `page` forces **`byPage` aggregation**: per the
  query reference, "If you group or filter by page, you cannot aggregate by
  property." This changes `impressions`/`position` — see [metrics](metrics.md).
- `query` and `page` together yield query-per-page rows, but multiply the
  anonymized-query shortfall; treat property-level totals as authoritative.

## Reporting notes

- Fixed vocabulary: these six dimensions are the entire slice surface. No
  ad-hoc columns exist.
- `date` grouping omits empty days, so a continuous date axis in a report
  must be built client-side.

## Warnings

- **Reporting timezone for `date` is ungrounded.** No official Google doc
  consulted stated the timezone; do not assert Pacific/UTC. Named gap.
- **Anonymized queries:** query-grouped totals under-count; use for shape,
  not for exact property totals.
- **Freshness:** the most recent days may be provisional depending on
  `dataState` — see [conventions](../../conventions.md) and [_notes](_notes.md).
