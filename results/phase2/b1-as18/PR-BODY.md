# enrich(drill): document `shop.orders` discount semantics — steward batch, 1 of 2 requests

Queue-driven batch (S1b). Two approved requests were delivered; one is
drafted here, one is handed back untouched.

## Docs in this batch

| Doc | Object | Evidence grade |
|---|---|---|
| `systems/drill/shop/orders.md` | `drill.shop.orders` | customer-provided (column semantics) + snapshot machine facts and view definitions (structure, reporting caveat) |

Status is `draft` throughout, `last_verified: null`. Nothing here is
certified; an approved request is not a certification (CP-E3).

## Grounding sources

- **`customer-provided, rene-reporter, 2026-08-07`** — the approved
  request `c5423c1f-8e0b-4be9-bf43-5583e5630570`. Name and date are the
  `by`/`at` the ledger recorded at filing time, not anything read out of
  the request text. **This is the sole source** for the two semantic
  claims in the doc: that `discount` is a currency amount rather than a
  rate, and that `net` is stored with it already deducted. Nothing in the
  estate corroborates or contradicts either claim — see "Grounding
  sufficiency".
- **`systems/drill/shop/orders.schema.md`** (snapshot
  `sha256:2af8bf2c…`, trust `machine` / `use-freely`) — settled the
  structural purposes: `id` as primary key, `customer_id` as the foreign
  key to `shop.customers.id`, `created_at` defaulting to `now()`, and the
  absence of any check constraint on the table. That absence is what the
  first warning rests on.
- **`drill.reporting.v_order_totals` view definition** (same snapshot,
  trust `machine` / `use-freely`) — settled the reporting caveat: the
  view computes `items_total` as `sum(qty * price)` over
  `drill.shop.order_items` and never references `orders.net` or
  `orders.discount`. `drill.reporting.v_net_sales` aggregates that view,
  so the divergence propagates to per-customer net sales.
- **`systems/drill/shop/customers.md`** — checked only so the join
  direction in this doc agrees with the existing routing (`customer`
  entity → `drill.shop.customers` as system of record). No claim here
  depends on it.

No DDL, migration, or application source for the `drill` estate was
available in this working copy, so the customer's claim could not be
raised above the stated tier. It is cited as stated, not observed.

## JSON columns

None. `drill.shop.orders` has no `json`/`jsonb` column — every column is
`bigint`, `text`, `numeric(12,2)`, or `timestamptz`. The JSON rule does
not apply to this batch.

## Machine re-renders

**Not run — and this PR should not be read as validated.** This session
was scoped to producing draft files in a `out/` directory: no KB clone
was provisioned (S0), so `generator.render` and `generator.validate` were
never executed and no CI has reported. Before this becomes a real pull
request, someone must run, from the KB clone root:

```bash
.venv/bin/python -m generator.render .contextlayer/snapshots/drill.json --out .
.venv/bin/python -m generator.validate .
```

and confirm `0 errors, 0 warnings` — KB-8 (render consistency) and KB-10
(every `column_purposes` key resolves against the snapshot) in
particular. The five `column_purposes` keys were written against the
snapshot column list above and are expected to resolve, but expected is
not the same as validated. The change is purpose-slot-confined, so
`generated_at` should not move; if it does, something other than purposes
moved.

## Ungrounded gaps

- **`drill.shop.orders.status` has no documented vocabulary.** The column
  is `text` with default `'new'` and no check constraint in the snapshot.
  `'new'` is the only grounded value. It is deliberately left with no
  purpose rather than given a plausible one; unblocked by the DDL or
  application code that writes the column.
- **NULL `discount` is undefined.** The column is nullable and the
  request does not distinguish "no discount applied" from "not recorded".
  Unblocked by a one-line answer from the requester, or by the checkout
  code path that writes the column.
- **The deduction is unenforced.** No check constraint ties `net` to
  `discount`, so the convention holds only as far as the application
  holds it. Unblocked by the DDL or by a query comparing
  `sum(order_items.qty * order_items.price) - discount` against `net`
  across live rows.
- **`drill.reporting.v_net_sales`'s human doc is stale** — its
  `written_against_schema_hash` does not match the current schema hash
  and its trust block reads `warn-user`. This batch did not build on that
  human doc; the reporting caveat is grounded in the machine view
  definitions, which are `use-freely`. Flagged because the next person to
  touch these views will hit it.

## Grounding sufficiency

Honest summary: this doc is structurally well grounded and semantically
grounded only by the customer's word.

Everything about shape — grain, keys, the join to `shop.customers`, the
line-item relationship, the absence of constraints, and how the reporting
views actually compute their totals — comes from the accepted snapshot
and is as solid as the snapshot is. The reporting caveat in particular is
observed from view SQL, not inferred, and is the most useful thing in the
doc for anyone reconciling numbers.

The two claims the request was actually filed about are a different
matter. They rest on one stated source and nothing else: no DDL, no
migration, no customer document, no usage evidence was available for this
estate. That is enough to draft under S1b outcome (2), and it is not
enough for anyone to treat the deduction as an invariant — which is why
the doc says so in its own first warning rather than leaving the reader to
infer it from the sources list. A reviewer who wants this stronger should
ask for the checkout code path or run the reconciliation query named
above.

## Requests in this batch

| Request | Doc | Grounding |
|---|---|---|
| `c5423c1f-8e0b-4be9-bf43-5583e5630570` — `drill.shop.orders` discount | `systems/drill/shop/orders.md` | customer-provided only (semantics); snapshot machine facts (structure, reporting caveat) |

### Handed back — needs returning to the queue

- **`b5ebc4fd-9b6f-49c7-b578-fa575ed12efa` — "the churn number".** Not
  draftable without guessing, so it is deliberately absent from the
  trailers below. The request names no object, no metric, and no
  definition, and nothing in the estate supplies one: `search_context`
  over churn and over subscription/cancellation/retention returns only
  the `customer` entity and the net-sales rollup, and the `drill` system
  has no subscription, contract, or cancellation object from which a
  churn figure could be derived at all. Drafting anything here would mean
  inventing both the metric and its source.

  **Unblocked by**, from the requester: (a) the definition — what counts
  as churned, over what window, and what the denominator is; and (b)
  which object or query the figure is meant to come from today, if it is
  already being reported somewhere. If churn is genuinely not computable
  from this estate, the honest resolution is a `capability_gap` for the
  data that would have to exist first, not an enrichment doc.

  **Still `batched`: the steward has to return it to the queue.** There
  is no session-side inlet for that write — `batched → approved` is a
  governed transition with no tool on this side of the wire (B1-F9), so
  this is a hand-back, not a state change I have made.

CL-Resolves: c5423c1f-8e0b-4be9-bf43-5583e5630570
