---
doc_class: human-group
object: ga4.events
written_against_schema_hash: "sha256:6050f287b022ce0333d31826053ff5f8ec84e8016fc244631869b9696f52c293"
status: draft
last_verified: null
sources:
  - "systems/ga4/events.schema.md (machine snapshot, generated_at 2026-07-13: purchase, Key event: true)"
  - "systems/ga4/metrics.schema.md / dimensions.schema.md (machine snapshot: keyEvents, keyEvents:purchase, isKeyEvent with API-carried descriptions)"
  - "systems/ga4/index.md (machine snapshot: currency_code USD, time_zone America/Vancouver)"
  - "Google Analytics Help, “About key events” — https://support.google.com/analytics/answer/9267568 (retrieved 2026-07-13)"
  - "GA4 recommended events reference (purchase) — https://developers.google.com/analytics/devguides/collection/ga4/reference/events (retrieved 2026-07-13)"
  - "No customer source exists for this property's purchase implementation (confirmed with R2, 2026-07-13)"
depends_on:
  - ga4.standard.purchase
  - ga4.standard.isKeyEvent
  - ga4.standard.keyEvents
  - "ga4.standard.keyEvents:purchase"
  - ga4.standard.eventName
---

# ga4 — events (human doc)

The snapshot's events group holds exactly one object:
`ga4.standard.purchase`, flagged `Key event: true`
([events.schema.md](events.schema.md)).

## What "key event" means

Google's definition: "A key event is an event that measures an action
that's particularly important to the success of your business" ([About
key events](https://support.google.com/analytics/answer/9267568)). Key
events are GA4's successor to "conversions" for measurement purposes
(same source). Per the API-carried `isKeyEvent` description in
[dimensions.schema.md](dimensions.schema.md): "Marking an event as a key
event affects reports from time of creation. It doesn't change historic
data," and some events "such as `first_open` or `purchase` are marked as
key events by default" — so `purchase` being a key event here may be the
default marking rather than a deliberate customer choice; which it is,
is undocumented (see PR gaps).

## The standard `purchase` event

Google's reference: "This event signifies when one or more items is
purchased by a user," with documented parameters `currency`, `value`,
`transaction_id`, `items` ([recommended events
reference](https://developers.google.com/analytics/devguides/collection/ga4/reference/events)).
**What this property actually sends is unverified**: no customer source
documents where `purchase` fires in the product (plausibly subscription
checkout — but `supabase.public.subscriptions` carries no amounts, and
no customer doc links the two), nor which parameters are populated.
Treat the vendor parameter list as an upper bound, not a description of
this property's data.

## Query surfaces (machine-attested in this property's rosters)

- `ga4.standard.keyEvents` (metric, TYPE_FLOAT): "The count of key
  events" (API-carried description).
- `ga4.standard.keyEvents:purchase` (metric, TYPE_INTEGER): "The count
  of a specific key event" — the purchase-specific counter.
- `ga4.standard.isKeyEvent` (dimension, string `true`/other) and
  `ga4.standard.eventName` for filtering.

Property configuration (machine index): `currency_code: USD`,
`time_zone: America/Vancouver` — state both when reporting
`purchase`-derived values or daily counts.

## Caveats

- With only one key event on the property, `keyEvents` and
  `keyEvents:purchase` should agree today, but that equality breaks the
  moment another key event is marked — prefer `keyEvents:purchase` for
  purchase-specific reporting.
- Quota and session-caching conventions for `runReport` apply — see
  [conventions.md](../../conventions.md#quota-notes-for-api-sources).
