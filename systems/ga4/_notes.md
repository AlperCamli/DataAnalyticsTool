---
doc_class: human-notes
purpose: "GA4 for the jobspecificcv property: the Data API surface, its one custom dimension and one key event, timezone, and quota."
---

# ga4 — system notes

> Status: draft · last_verified: null. The `human-notes` front-matter schema
> admits only `doc_class` and `purpose`, so trust status and sources live in
> this body. Treat this doc as **draft**, unverified.

Google Analytics 4 for the property `properties/542045072` (display name
`jobspecificcv`, currency `USD`, timezone `America/Vancouver` — see the
machine [index](index.md) source-properties). Access is the GA4 Data API
`runReport`; an API source, **no SQL surface**, with a large Google-defined
field vocabulary (see [conventions](../../conventions.md)).

## Scale & what is custom

466 objects: **376 dimensions** (375 Google-standard + **1 custom**),
**89 metrics** (all Google-standard, **0 custom**), and **1 event**
(`purchase`, a key event). The vast majority are Google-defined; the only
customer-defined field is one custom dimension. The three human group docs
focus enrichment on what is customer-specific or reporting-critical:

- [dimensions.md](dimensions.md) — the custom dimension
  `customEvent:export_status` (standard dimensions are Google-defined).
- [metrics.md](metrics.md) — the key-event count metrics `keyEvents` and
  `keyEvents:purchase`.
- [events.md](events.md) — the `purchase` key event.

## Timezone & date

Unlike GSC, GA4's reporting timezone is grounded: `date`/`dateHour`
dimensions report in the property timezone **`America/Vancouver`**
(source-properties). Convert to UTC or a business timezone before joining GA4
dates to Supabase timestamps (which are `timestamptz`, stored UTC).

## Quota

GA4 Data API quota is property-scoped tokens and a real failure mode. The
session-caching convention is required and metadata is not re-pulled
mid-session; exhaustion surfaces as a deferral, not an error. See
[conventions](../../conventions.md) "Quota notes for API sources."

## Sources

- machine doc: `ga4` index (source-properties: property_id, time_zone, currency)
- vendor doc: https://developers.google.com/analytics/devguides/reporting/data/v1/advanced (custom dimension API naming)
- vendor doc: https://support.google.com/analytics/answer/9267568 (key events)
- KB: conventions.md (GA4 quota + session-caching)
