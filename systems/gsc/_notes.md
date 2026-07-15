---
doc_class: human-notes
purpose: "Google Search Console for jobspecificcv.com: one API surface, its freshness/quota rules, and how the two groups fit together."
---

# gsc — system notes

> Status: draft · last_verified: null. The `human-notes` front-matter schema
> admits only `doc_class` and `purpose` (the vendored CI schema is closed),
> so trust status is recorded here in prose rather than front-matter. Treat
> this doc as **draft**, unverified.

Google Search Console for the single verified property
`sc-domain:jobspecificcv.com` (permission `siteRestrictedUser`; see the
machine [index](index.md) source-properties). Access is the Search Analytics
API `searchanalytics.query` operation — an API source, **no SQL surface**,
fixed dimension/metric vocabulary (see [conventions](../../conventions.md)).

## The two groups

- [dimensions.md](dimensions.md) — the six slice dimensions (`country`,
  `date`, `device`, `page`, `query`, `searchAppearance`).
- [metrics.md](metrics.md) — the four metrics (`clicks`, `impressions`,
  `ctr`, `position`).

A report is one `searchanalytics.query`: pick metrics, pick grouping
dimensions. The page-vs-property aggregation choice is the main correctness
trap — it is documented in both group docs.

## Data freshness (`dataState`)

The snapshot records the request vocabulary
(`data_freshness.data_states: [all, final]`); the semantics are fixed by
[conventions](../../conventions.md) (ruling D-31):

- `dataState=final` — finalized rows only; stable, lagging a few days.
- `dataState=all` — adds the fresh-but-provisional recent tail. Per the
  vendor performance-report doc, "The newest data can be preliminary,
  meaning it's still being collected and might change in the next few hours."
- Convention: use `final` for certified/recurring reports; use `all` only
  when the freshest numbers are explicitly wanted, and flag recent days as
  provisional.

## Quota

Modest quotas; one query per report request is the norm — no session-scale
quota risk, but the session-caching convention still applies (don't re-issue
identical queries). See [conventions](../../conventions.md) "Quota notes."

## Sources

- vendor doc: https://developers.google.com/webmaster-tools/v1/searchanalytics/query
- vendor doc: https://support.google.com/webmasters/answer/7042828
- vendor doc: https://support.google.com/webmasters/answer/7576553 (preliminary-data quote)
- KB: conventions.md (D-31 dataState semantics; quota notes)
