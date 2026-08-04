# Sync review: sync: 4 breaking, 1 additive across drill

Verdict: BREAKING — repair before merge
4 breaking objects (blast up to 3 docs) contaminate 5 human docs across the
reporting and customer chains; 1 additive change, 1 doc stale — this is not a
clean merge. Docs that agents are served today as `use-freely` (and one
`certified` metric) are the ones the drift invalidates.

## Breaking (ranked by blast radius)

1. `drill.shop.orders` — column_removed: discount; column_ordinal_changed: created_at — blast radius: 3 docs
   - contaminates `metrics/net-sales.md` (lineage path: `sha256:3ffcb89caadd…` → `sha256:b6b4ccf14588…`)
   - contaminates `systems/drill/reporting/v_net_sales.md` (lineage path: `sha256:3ffcb89caadd…`)
   - contaminates `systems/drill/shop/customers.md` (declared dependency)
2. `drill.reporting.v_order_totals` — definition_changed — blast radius: 2 docs
   - contaminates `metrics/net-sales.md` (lineage path: `sha256:b6b4ccf14588…`)
   - contaminates `systems/drill/reporting/v_net_sales.md` (declared dependency)
3. `drill.shop.customers` — column_removed: name — blast radius: 2 docs
   - contaminates `entities/customer.md` (declared dependency)
   - contaminates `systems/drill/shop/customers.md` (declared dependency)
4. `drill.shop.legacy_sessions` — object removed from snapshot — blast radius: 1 doc
   - contaminates `systems/drill/shop/legacy_sessions.md` (declared dependency)

Ranking notes: fan-out is the changelog's per-object lists (authoritative for full
fan-out); `triage.py` over the sync checkout counts the same 5 contaminated docs.
`drill.shop.orders` carries no `contamination:` marker of its own in the tree
(each multiply-contaminated doc records a single primary object — `net-sales.md`,
`v_net_sales.md`, and `customers.md` each record their other source), so it shows
blast 0 in the triage counts while the changelog attributes 3 docs to it; the
changelog governs the ranking. The `#2`/`#3` tie at 2 docs is broken
alphabetically (`drill.reporting.v_order_totals` < `drill.shop.customers`) so
this ranking is reproducible. Highest-blast lineage confirmed via `get_lineage`:
`drill.shop.orders` → `drill.reporting.v_order_totals` (edge `sha256:3ffcb89caadd…`, aggregate/sql-parse)
→ `drill.reporting.v_net_sales` (edge `sha256:b6b4ccf14588…`, aggregate/sql-parse).

## Rename candidates (human decision required)

- `drill.shop.customers`: `name` → `full_name` (type text, ordinal 3) — either
  **column renamed** or **column removed + column added**; evidence: the removed
  `name` is `text` at ordinal 3 (served schema `drill.shop.customers`, col #3,
  nullable) and the proposed `full_name` is also `text` at ordinal 3 — same type,
  same slot, which is circumstantial support for a rename; but no migration and no
  doc body disambiguates (no human doc cites `name` or `full_name` — `customer.md`
  joins on `id`, `customers.md` documents only `id`/`email`/`customer_id`), so
  nothing authoritative resolves it. The removal of `name` is breaking under both
  readings; leave the interpretation to the human at repair time (do not pick one).

## Additive

- `drill.shop.order_items` — column_added: discount_pct — additive-only; carries no
  contamination. Re-verify `systems/drill/shop/order_items.md` at leisure.

## Docs marked stale

- `systems/drill/shop/order_items.md` (additive drift on `drill.shop.order_items` —
  `discount_pct` added). Stale, not contaminated; safe to re-verify without urgency.

## Undeclared references (non-authoritative)

- `systems/drill/reporting/v_net_sales.md` mentions `drill.shop.legacy_sessions` —
  body-text mention only (Reporting notes: attribution backfills "historically
  blended this with `drill.shop.legacy_sessions`"), not declared in `depends_on` and
  not flagged by the scan (KB §6 step 5); reviewer attention item, not a finding.
  Worth noting only because `drill.shop.legacy_sessions` is being removed, so this
  prose now points at a gone object — but it remains non-authoritative and does not
  change the contamination set.

## Served trust state (present, from MCP)

The PR describes a future state; the MCP describes what agents are served **now**.
The gap is the urgency. Served ref `kb_ref 03a90d63…` (a deployed state — not
either git commit in this clone; `main` is `3f53f82`, sync is `1e9abbe`):

| Doc | Served status today | Guidance today | After the drift |
|---|---|---|---|
| `metrics/net-sales.md` | verified, **certified** | `use-freely` | invalidated (v_order_totals def + orders cols) |
| `entities/customer.md` | verified | `use-freely` | invalidated (customers.name removed) |
| `systems/drill/shop/customers.md` | verified, hash_match | `use-freely` | invalidated (customers.name + orders cols) |
| `systems/drill/reporting/v_net_sales.md` | verified | `warn-user`* | invalidated (v_order_totals def + orders cols) |
| `systems/drill/shop/legacy_sessions.md` | contaminated (deployed) | `refuse-unless-override` | object removed |

\* `v_net_sales.md` is already `warn-user` for an unrelated pre-existing reason:
its `written_against_schema_hash` is the all-zeros placeholder
(`sha256:0000…`), which never matched the live view hash
(`sha256:10090faac6ee…`) — repair should refresh this to the real post-merge hash.
Note also the served deployed state already marks `legacy_sessions` contaminated
(`refuse-unless-override`), while the git `main` checkout still shows it `verified`;
that is a served-vs-checkout gap on the deployed ref, not a changelog↔tree
disagreement (those agree). The urgent cases are the three `use-freely` docs —
especially the **certified** `net-sales` metric — which agents trust fully today but
which the drift has already invalidated at source.

## Recommendation

Breaking PR. Per-doc repair list, ordered by unblock count (repair that clears the
most downstream contamination first). Repairs are separate PRs against `main` under
the steward's identity — **not** drafted this session (review only).

**Reporting chain first** (deepest chain; a certified metric sits downstream; driven
by the highest-blast object `orders` plus `v_order_totals`):

1. `systems/drill/reporting/v_net_sales.md` — broke by `v_order_totals`
   definition_changed (declared dep) and `orders` column_removed:discount /
   created_at ordinal (lineage `sha256:3ffcb89caadd…`). Repair needs: the post-drift
   `drill.reporting.v_order_totals` view definition and the new `orders` column set
   written into the reporting notes, plus `written_against_schema_hash` refreshed off
   the zero placeholder. **Groundable from the KB's own evidence** — the new
   snapshot's machine view-def carries the definition (sql-parse tier); the *semantic*
   effect on net sales should be confirmed but the mechanics are grounded. Unblocks
   the metric below.
2. `metrics/net-sales.md` — broke by `v_order_totals` definition_changed via lineage
   `sha256:b6b4ccf14588…` (and `orders` via `sha256:3ffcb89caadd…` → `…b6b4ccf14588…`).
   Repair needs: re-verify `SELECT customer_id, net_total FROM reporting.v_net_sales`
   still holds once #1 lands. **Groundable** once the view repair is in. Highest
   urgency to re-verify — served `certified`/`use-freely` today.

**Customers chain second** (2 docs, but gated on the human rename decision):

3. `systems/drill/shop/customers.md` — broke by `customers` column_removed:name
   (declared) and `orders` column_removed:discount / created_at ordinal (declared dep).
   Repair needs: the human's rename decision (renamed → `full_name`, vs removed+added)
   **first**; then refresh column facts and `written_against_schema_hash`. No body
   claim cites the removed columns, so after the rename call the repair is largely
   re-verification. **Groundable from KB evidence** once the rename is decided.
   Unblocks the entity below.
4. `entities/customer.md` — broke by `customers` column_removed:name (declared dep).
   Repair needs: follow the rename decision; the entity keys on `id` (unaffected), so
   re-verify the system-of-record mapping once #3 lands. **Groundable.**

**Removal last** (blast 1, already served `refuse-unless-override`, and the one repair
that needs customer knowledge):

5. `systems/drill/shop/legacy_sessions.md` — broke by `drill.shop.legacy_sessions`
   removed from snapshot. Repair needs **business knowledge the KB lacks**: was the
   table intentionally decommissioned, and are the attribution backfills it fed still
   needed? Its purpose ("pre-migration sessions, kept for attribution backfills")
   cannot be re-grounded once the object is gone. At repair time this is a K-FAIL:
   `flag_gap(missing_doc)` naming the `last_verified` owner (the `2026-07-14 (drill)`
   trail), leave the doc's repair explicitly incomplete, and decide retire-vs-keep with
   the customer. (Resolving this also settles the dangling body mention in
   `v_net_sales.md` above.) Not filed this session — review only.

**Merge sequencing.** Recommend merging the **sync PR** after this review — I do not
merge (certification is the human's act, with their name on it). Rationale: the
contamination markings are accurate (verified against the tree, the changelog, and the
lineage graph), and landing them flips the three docs agents see today as
`use-freely`/`certified` (`net-sales`, `customer`, `customers`) to
`contaminated`/`refuse`, closing the window where agents trust source data that has
already drifted. Repairs then follow as the separate PRs above, in order; each returns
its doc to `verified` only when the human clears `contamination`, refreshes
`written_against_schema_hash`, and sets `last_verified` with their own name.

If the customer's policy is repair-first (hold the sync PR until repairs are ready),
the tradeoff is a window where these docs are wrong but **unmarked** — agents keep
getting `use-freely`/`certified` guidance on `net-sales`/`customer`/`customers` while
the source has already moved. Given `net-sales` is a certified metric served
`use-freely` today, that window is materially risky; merge-to-record-reality is the
safer default here.
