---
doc_class: human-group
object: ga4.dimensions
written_against_schema_hash: "sha256:931a00ae132fcf92da75775e5515f8f9ff93137082f53d7e95c8f433fb027bef"
status: draft
last_verified: null
sources:
  - "systems/ga4/dimensions.schema.md (machine snapshot, generated_at 2026-07-13: roster, per-object facts incl. API-carried descriptions)"
  - "systems/ga4/index.md (machine snapshot: property jobspecificcv, properties/542045072)"
  - "No customer source exists for the custom definition's meaning (confirmed with R2, 2026-07-13)"
depends_on:
  - "ga4.custom.customEvent:export_status"
  - ga4.standard.eventName
  - supabase.public.exports
  - supabase.public.cover_letter_exports
---

# ga4 — dimensions (human doc)

This property (`jobspecificcv`, `properties/542045072`) exposes 376
dimensions; 375 are Google-standard, defined by Google and carried with
their official descriptions in
[dimensions.schema.md](dimensions.schema.md) — this doc does not restate
them. It covers the one thing Google cannot define: the property's
custom definitions.

## Custom definitions — exactly one

`ga4.custom.customEvent:export_status` (type string) is the property's
only custom dimension. Machine-attested facts: namespace `custom`, and
the API-carried description "An event scoped custom dimension for your
Analytics property" — so its value is populated per event, not per user
or session.

**Its business meaning is undocumented.** No customer source exists
(confirmed 2026-07-13): the value vocabulary, which events carry it,
and what an absent value means are all unknown. Observations that are
grounded but must not be over-read:

- The name parallels the `status` columns of
  `supabase.public.exports` and `supabase.public.cover_letter_exports`
  (both `text`, both with undocumented vocabularies). Whether the GA4
  parameter mirrors those columns is **not documented anywhere** — do
  not treat them as equivalent without a customer source.
- By the Data API's `customEvent:` naming, the suffix is expected to be
  an event parameter named `export_status`; we could not retrieve
  vendor wording confirming that reading, so it stays unverified (see
  PR gaps).

## What a query-writer must know

- Event-scoped (machine-attested) means the dimension's value is
  populated per event: a report slicing by it is slicing events, not
  users or sessions. How events that never set the parameter render in
  results is not documented in this KB — verify before relying on it.
- Filter by `ga4.standard.eventName` alongside it if you only want the
  event(s) that actually populate the parameter — which events those
  are is itself undocumented (gap above).
- Custom definitions change rarely; metadata re-snapshots are nightly —
  per [conventions.md](../../conventions.md#quota-notes-for-api-sources),
  never re-pull metadata inside a session, and session-cache `runReport`
  results.
