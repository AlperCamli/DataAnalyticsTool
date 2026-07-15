---
doc_class: human-group
object: ga4.events
written_against_schema_hash: "sha256:2e8105a4a9f926300256d74ed256f83a217a233eb8320b2c826039619df6a256"
status: draft
last_verified: null
purpose: "GA4 events registered for the jobspecificcv property; purchase is the property's key event."
object_purposes:
  "ga4.standard.purchase": "Standard GA4 purchase event, marked as this property's key event (conversion)."
sources:
  - "machine doc: ga4.standard.purchase (is_key_event: true)"
  - "vendor doc: https://developers.google.com/analytics/devguides/collection/ga4/reference/events (purchase recommended event)"
  - "vendor doc: https://support.google.com/analytics/answer/9267568 (key events)"
  - "app code: CV_Builder/frontend/src/app/integration/analytics.ts (key-event recommendations; payment value/currency mapping)"
depends_on: []
contamination: null
---

# ga4 — events

The GA4 event metadata for `properties/542045072`. The snapshot exposes a
single event object, `ga4.standard.purchase`, flagged **`Key event: true`**
(machine fact).

## `purchase` — standard recommended event

`purchase` is a Google **recommended event** that "signifies when one or more
items is purchased by a user." Its parameters (official GA4 reference) include
`currency` (3-letter ISO 4217), `value` (monetary value), `transaction_id`
(dedupe key), and `items`; "if you set `value` then `currency` is required for
revenue metrics to be computed accurately." The property currency is `USD`.

## Key event

`purchase` is marked as this property's **key event** — "an event that
measures an action that's particularly important to the success of your
business" (formerly a "conversion"). Its count is reported by
`ga4.standard.keyEvents:purchase` (see [metrics.md](metrics.md)).

## Population — grounding gap

**How `purchase` is populated for this property is not grounded.** The
CVBuilder frontend analytics layer emits `payment_completed` (with a
plan→`value` map and `USD` currency) and *recommends* marking
`payment_completed`, `tailored_cv_generated`, `cv_exported`, and
`signup_page_view` as key events — it does **not** emit a GA4 `purchase`
event. Whether `purchase` is produced server-side, via a tag manager, or by a
payment-provider integration is unknown from the available app code. **Do not
assume `payment_completed` equals `purchase`** — treat the mapping as an open
question for the property owner.

## Reporting notes

- Purchase conversions = `keyEvents:purchase`; purchase revenue comes from the
  event's `value`/`currency`, reported via GA4's standard revenue metrics.

## Warnings

- The population gap above is the key caveat: reconcile GA4 `purchase` counts
  against `supabase.public.subscriptions` before treating them as the same
  business event — the linkage is not established here.
- `value` without `currency` yields no revenue; both are needed.
