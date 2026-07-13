---
doc_class: human-group
object: gsc.metrics
written_against_schema_hash: "sha256:852dff2ac0b25ac18f404a97c08c7f48cb63f31f2ad1d1d881937d475c0f38df"
status: draft
last_verified: null
sources:
  - "Google Search Console Help, “What are impressions, position, and clicks?” — https://support.google.com/webmasters/answer/7042828 (retrieved 2026-07-13)"
  - "Google Search Analytics API reference — https://developers.google.com/webmaster-tools/v1/searchanalytics/query (retrieved 2026-07-13)"
  - "systems/gsc/index.md (machine snapshot: data_freshness.data_states)"
  - "conventions.md (D-31 dataState semantics; GSC quota notes)"
depends_on:
  - gsc.standard.clicks
  - gsc.standard.ctr
  - gsc.standard.impressions
  - gsc.standard.position
  - gsc.standard.page
---

# gsc — metrics (human doc)

The four metrics `searchanalytics.query` returns per row. The schema is
fixed by Google — definitions below are carried from Google's official
documentation, cited per entry. Machine facts (types, hashes) live in
[metrics.schema.md](metrics.schema.md).

## `gsc.standard.clicks` (integer)

"Any click that sends the user to a page outside of Google Search,
Discover, or News is counted as a click; clicking a link that stays inside
the Google platform is not counted as a click" ([help
7042828](https://support.google.com/webmasters/answer/7042828)).

## `gsc.standard.impressions` (integer)

"An impression means that a user has seen (or potentially seen) a link to
your site in Search, Discover, or News" ([help
7042828](https://support.google.com/webmasters/answer/7042828)).
Impression counting depends on aggregation: when one search element
carries several links to the property, "only one impression is counted
for the entire card" by property, versus "five pages with one impression
each" when grouped by page (same source). Totals grouped by
`gsc.standard.page` will not match property-aggregated totals.

## `gsc.standard.ctr` (double)

"The calculation of (clicks ÷ impressions)" ([help
7042828](https://support.google.com/webmasters/answer/7042828)). Derived
from the two metrics above — do not re-average CTR across rows; recompute
it from summed clicks and impressions.

## `gsc.standard.position` (double)

"The topmost position occupied by a link to your property or page in
search results, averaged across all queries in which your property
appeared"; "position is calculated only for Google Search results," and
numbering begins at 1 for the topmost result ([help
7042828](https://support.google.com/webmasters/answer/7042828)). Lower is
better; a position average is only meaningful alongside the impression
count it was averaged over.

## Freshness (`dataState`)

These numbers change until finalized. The request vocabulary is
`data_freshness.data_states: [all, final]` ([index.md](index.md)); API
wording: "If 'all' (case-insensitive), data will include fresh data. If
'final' (case-insensitive) or if this parameter is omitted, the returned
data will include only finalized data" ([API
reference](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)).
Practical semantics and the agent convention (`final` for anything
certified or recurring; `all` only on explicit request, flagged as
provisional) are ruled in
[conventions.md](../../conventions.md#quota-notes-for-api-sources).
