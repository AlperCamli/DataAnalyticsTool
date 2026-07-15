---
doc_class: human-group
object: gsc.metrics
written_against_schema_hash: "sha256:08e7c1b5ca5f335bde8943ee022888c70a4c25b2373986285e2a7d34a34ca1b5"
status: draft
last_verified: null
purpose: "The four Search Analytics performance metrics reported for CVBuilder's Google Search presence."
object_purposes:
  "gsc.standard.clicks": "Count of clicks from Google Search results to the property."
  "gsc.standard.ctr": "Click-through rate: clicks divided by impressions."
  "gsc.standard.impressions": "Count of times a link to the property was seen in results."
  "gsc.standard.position": "Average topmost position of the property's link in results."
sources:
  - "vendor doc: https://support.google.com/webmasters/answer/7042828"
  - "vendor doc: https://developers.google.com/webmaster-tools/v1/searchanalytics/query"
  - "KB: conventions.md (GSC dataState D-31)"
depends_on: []
contamination: null
---

# gsc — metrics

The four metrics `searchanalytics.query` returns for the verified property
`sc-domain:jobspecificcv.com`. These are a fixed vendor-defined set with no
SQL surface; their values depend on which [dimensions](dimensions.md) the
request groups by (especially the `byPage` vs `byProperty` distinction).

## Grain

Each metric is an aggregate over the rows produced by the grouping
dimensions and date range of a single query. Data types (machine sibling
[metrics.schema.md](metrics.schema.md)): `clicks`/`impressions` are
integers; `ctr`/`position` are doubles.

## Metric meanings & aggregation caveats

- `gsc.standard.clicks` — "any click that sends the user to a page outside
  of Google Search, Discover, or News is counted as a click." Returning to
  click the same link again is **one** click; query-refinement clicks that
  stay in Google are **not** counted.
- `gsc.standard.impressions` — "a user has seen (or potentially seen) a
  link to your site." Counting depends on result type: standard results
  count "whether or not the item is scrolled into view," but inside
  carousels/expanding widgets (and in image search) the item **must be
  scrolled into view / expanded** to register.
- `gsc.standard.ctr` — "The calculation of (clicks ÷ impressions)." It is
  computed from **summed** clicks and impressions for the row, i.e. a
  weighted ratio — **not** an average of per-row CTRs. Do not average CTR
  across rows; recompute it from summed clicks and impressions.
- `gsc.standard.position` — the **topmost** position of the property's link
  per query, then **averaged** across impressions: "the metric is shown as
  average position, which averages the position value for all impressions,"
  and "the position value shown … is the topmost position occupied by a
  link to your property or page." Worked example from the vendor: query
  positions (2,4,6)→2 and (3,5,9)→3 average to **2.5**.

## Join guidance

No SQL joins — combining metrics means requesting them together in one
`searchanalytics.query` and choosing the grouping dimensions. The
aggregation mode changes the numbers:

- **`byProperty`** (default when `page` is not grouped/filtered): multi-link
  elements like a knowledge panel count as "one impression … for the entire
  card."
- **`byPage`** (forced when grouping/filtering by `page`): "all impressions
  for the same page are combined into a single impression when grouping data
  by page," and property-level aggregation is unavailable. `impressions`,
  `ctr`, and `position` all shift accordingly.

## Reporting notes

- **Never average `ctr` or `position`** across pre-aggregated rows —
  re-derive `ctr` from summed clicks/impressions, and treat `position` as an
  impression-weighted average that cannot be re-summed from row values.
- Because `position` is topmost-per-query, it understates how deep other
  links to the property ranked.

## Warnings

- Switching a report between page-grouped and property-grouped slices
  silently changes `impressions`/`ctr`/`position` — state the aggregation
  mode alongside any figure.
- The most recent days may be provisional under `dataState=all`; use
  `dataState=final` for certified/recurring metrics (see
  [conventions](../../conventions.md) and [_notes](_notes.md)).
