---
doc_class: human-group
object: ga4.metrics
written_against_schema_hash: "sha256:17777ce225a27e87a19af9c03ec2a36544e19e2089ad07aaf87e5e9ef8ffd585"
status: draft
last_verified: null
purpose: "GA4 metrics for the jobspecificcv property — all Google-standard; the key-event counts surface the purchase conversion."
object_purposes:
  "ga4.standard.keyEvents": "Count of all key events (conversions) across every event marked as a key event."
  "ga4.standard.keyEvents:purchase": "Count of the purchase key event specifically."
sources:
  - "machine doc: ga4.standard.keyEvents (TYPE_FLOAT), ga4.standard.keyEvents:purchase (TYPE_INTEGER)"
  - "vendor doc: https://support.google.com/analytics/answer/9267568 (key events)"
  - "vendor doc: https://developers.google.com/analytics/devguides/reporting/data/v1/advanced (key-event metric naming)"
depends_on:
  - ga4.standard.purchase
contamination: null
---

# ga4 — metrics

All 89 metrics on `properties/542045072` are Google-standard (**0 custom**).
This doc enriches only the two **key-event count** metrics, which are the
reporting hinge for conversions on this property; the rest carry Google's own
metric semantics (official GA4 metric reference).

## Key-event metrics

A **key event** is "an event that measures an action that's particularly
important to the success of your business" (formerly a "conversion").

- `ga4.standard.keyEvents` (`TYPE_FLOAT`) — the count of **all** key events,
  summed across every event type marked as a key event.
- `ga4.standard.keyEvents:purchase` (`TYPE_INTEGER`) — the count of the
  **`purchase`** key event specifically (Data API per-event naming
  `keyEvents:<event_name>`).

Because `purchase` is currently the property's only key event (see
[events.md](events.md)), `keyEvents` and `keyEvents:purchase` coincide **today**
— but `keyEvents` will diverge the moment another event is marked as a key
event, so do not treat them as permanently equal.

## Reporting notes

- Use `keyEvents:purchase` for a purchase-specific conversion count; use
  `keyEvents` only when you deliberately want the roll-up across all key-event
  types.
- Revenue is not a key-event metric — for purchase value use the standard
  revenue metrics fed by the event's `value`/`currency` (see
  [events.md](events.md)).

## Warnings

- `keyEvents` is a **float**; in attribution/modeled reports it can be
  fractional. `keyEvents:purchase` is an integer count. Don't assume both are
  whole numbers when combining.
- The set of events counted by `keyEvents` is a property configuration that
  can change over time; a shift in `keyEvents` may reflect a config change,
  not user behavior.
