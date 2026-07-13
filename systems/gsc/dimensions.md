---
doc_class: human-group
object: gsc.dimensions
written_against_schema_hash: "sha256:356c5af05cb6439b01a3d0fa7a24e39afbaf212f42558ee375c150e07e96f777"
status: draft
last_verified: null
sources:
  - "Google Search Analytics API reference — https://developers.google.com/webmaster-tools/v1/searchanalytics/query (retrieved 2026-07-13)"
  - "Google Search Console Help, “What are impressions, position, and clicks?” — https://support.google.com/webmasters/answer/7042828 (retrieved 2026-07-13)"
  - "Google Search Console Help, “Performance report (Search results)” — https://support.google.com/webmasters/answer/7576553 (retrieved 2026-07-13)"
  - "systems/gsc/index.md (machine snapshot: data_freshness.data_states, properties)"
  - "conventions.md (D-31 dataState semantics; GSC quota notes)"
depends_on:
  - gsc.standard.country
  - gsc.standard.date
  - gsc.standard.device
  - gsc.standard.page
  - gsc.standard.query
  - gsc.standard.searchAppearance
---

# gsc — dimensions (human doc)

Grouping dimensions available to `searchanalytics.query` on this estate's
Search Console property (`sc-domain:jobspecificcv.com`, per the machine
snapshot in [index.md](index.md)). The schema is fixed by Google — the
authoritative definitions below are carried from Google's official
documentation, cited per entry. Machine facts (types, hashes) live in
[dimensions.schema.md](dimensions.schema.md).

## The six dimensions

All six are type `string` (machine doc).

### `gsc.standard.query`

The search query the user typed. The Performance report groups "by the
search query users typed" ([Performance report
help](https://support.google.com/webmasters/answer/7576553)). Caveat from
the same page: "Even if a query appears in your list, you might not see
your site in results if you run the same query in Google Search."

### `gsc.standard.page`

The result URL. In filter form the API matches "against the specified URI
string" ([API
reference](https://developers.google.com/webmaster-tools/v1/searchanalytics/query));
when results are aggregated by page, "all data is aggregated by canonical
URI" (same page). See "Aggregation" below — grouping by page changes
impression counting.

### `gsc.standard.country`

Country of the search, "as specified by 3-letter country code" ([API
reference](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)).

### `gsc.standard.device`

Device type. "Supported values: DESKTOP, MOBILE, TABLET" ([API
reference](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)).

### `gsc.standard.date`

Calendar date of the search. API behavior note: "When date is one of the
dimensions, any days without data are omitted" ([API
reference](https://developers.google.com/webmaster-tools/v1/searchanalytics/query))
— a gap in a date-grouped result is missing data, not zero rows.

### `gsc.standard.searchAppearance`

Search result feature the impression appeared as; the filter form matches
"against a specific search result feature" ([API
reference](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)).

## Aggregation (byPage vs byProperty)

From the [API
reference](https://developers.google.com/webmaster-tools/v1/searchanalytics/query):
"If aggregated by property, all data for the same property is aggregated;
if aggregated by page, all data is aggregated by canonical URI," and "If
you group or filter by page, you cannot aggregate by property." The
practical effect on impressions ([help
7042828](https://support.google.com/webmasters/answer/7042828)): when one
search element carries several links to the property, "only one impression
is counted for the entire card" by property, while the same element counts
as "five pages with one impression each" when grouped by page. Numbers
grouped by `page` and numbers grouped without it are therefore not
comparable.

## Search type

Results are also scoped by the request's `type` field: `web` (the default,
the combined "All" tab in Google Search), `image`, `video`, `news`,
`googleNews`, or `discover` ([API
reference](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)).
Rows from different types are different populations — don't mix them in
one report without saying so.

## Freshness (`dataState`)

The snapshot records the request vocabulary
`data_freshness.data_states: [all, final]` ([index.md](index.md)). API
wording: "If 'all' (case-insensitive), data will include fresh data. If
'final' (case-insensitive) or if this parameter is omitted, the returned
data will include only finalized data" ([API
reference](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)).
What that means in practice, and the agent convention (use `final` for
anything certified or recurring; `all` only on explicit request, flagged
as provisional), is ruled in
[conventions.md](../../conventions.md#quota-notes-for-api-sources).
