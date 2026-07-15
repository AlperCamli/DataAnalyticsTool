---
doc_class: human-group
object: ga4.dimensions
written_against_schema_hash: "sha256:e3cf185f86435cd690116c7d888a3615bb2bf9f8411fe19b0c677ce1790391aa"
status: draft
last_verified: null
purpose: "Dimensions available for GA4 reporting on the jobspecificcv property — 375 Google-standard plus one custom (export_status)."
object_purposes:
  "ga4.custom.customEvent:export_status": "Event-scoped custom dimension: the export outcome recorded on cv_exported events."
sources:
  - "machine doc: ga4.custom.customEvent:export_status (namespace custom; 'An event scoped custom dimension')"
  - "app code (customer definition): CV_Builder/frontend/src/app/pages/CVEditor.tsx (export_status param on cv_exported) + integration/analytics.ts"
  - "app DDL: CV_Builder/backend/supabase/migrations (exports_status_check: processing|completed|failed)"
  - "vendor doc: https://developers.google.com/analytics/devguides/reporting/data/v1/advanced"
depends_on:
  - supabase.public.exports
contamination: null
---

# ga4 — dimensions

The GA4 Data API dimension surface for `properties/542045072`. Of 376
dimensions, **375 are Google-standard** (defined and documented by Google) and
**one is customer-defined**. This doc enriches only the custom one; standard
dimensions carry Google's own semantics (official GA4 dimension reference).

## The custom dimension

`ga4.custom.customEvent:export_status` — an **event-scoped custom dimension**
(Data API naming: `customEvent:<event_parameter_name>`; the API description is
"An event scoped custom dimension for your Analytics property"). It surfaces
the **`export_status`** event parameter, which the frontend attaches to the
**`cv_exported`** GA4 event. Its value is the export record's status, so it
takes the same values as `supabase.public.exports.status`: **`processing` |
`completed` | `failed`**.

Population caveat (grounded in app code): `export_status` is sent on the
*new-export* `cv_exported` call, but **not** on the history-download call — so
some `cv_exported` events carry `(not set)` for this dimension.

## Standard dimensions (not enriched here)

375 standard dimensions are Google-defined; use Google's dimension reference
for their meaning. Note the Google Ads dimensions present in the snapshot —
`googleAdsCustomerId`, `sessionGoogleAdsCustomerId`,
`firstUserGoogleAdsCustomerId` — are standard (not custom) and populate **only
when the property is linked to Google Ads**; whether such linking exists for
this property is not grounded (gap).

## Reporting notes

- A custom definition must be **registered in the property** before the API
  will accept it — `customEvent:export_status` is registered (it appears in
  the metadata snapshot).
- Slice export outcomes by grouping the `cv_exported` event on
  `customEvent:export_status`; join to `supabase.public.exports` for the
  authoritative per-export record.

## Warnings

- `export_status` exists only on events that carried the parameter — treat
  `(not set)` as "not reported," not as a distinct outcome.
- Do not read the `googleAds*` dimensions as populated without confirming
  Google Ads linking (gap above).
