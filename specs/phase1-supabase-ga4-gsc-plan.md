# Phase 1 Engineering Plan — Customer 2 (Supabase + GA4 + GSC → Looker Studio)

Scope: instantiate the Context Layer v1 spec (see `context-layer-v1-spec.md`) for a customer with a Supabase OLTP database, Google Analytics 4, Google Search Console, no data warehouse, and Looker Studio as the BI target. This document covers phase 1 (KB core) in engineering detail, plus the customer-specific rulings that adapt the master spec.

**Framing: this customer is the first demo, not the product's shape.** Everything here is built against the platform contracts (`platform-architecture.md` — connector SDK, snapshot schema, capability interfaces), so this deployment proves the end-to-end journey while the architecture stays ready for arbitrary future connections: more databases, pipeline tools, knowledge sources, and BI targets arrive as additive connectors and adapters, not rework.

---

## 1. Deviations from the master spec

| Master spec | This customer | Consequence |
|---|---|---|
| SAP + OLTP + DW | Supabase (Postgres) + GA4 + GSC, no DW | Introduces a second system class: **API-queryable sources** with no SQL surface |
| Query-history mining | Not used; customer supplies DDL + existing docs | Enrichment grounded in provided docs; `pg_stat_statements` (on by default in Supabase) available later if wanted |
| Reports run on DW | Reports run directly on production OLTP | Read-only role, statement timeouts, row limits mandatory from day one; read replica preferred if their tier has one |
| Power BI adapter (PBIP/TMDL) | Looker Studio adapter | No full authoring API → capability-flag-limited adapter; publishing via reporting views + template reports + Linking API |
| Live introspection | DDL-file mode first, live later | Connector supports both modes, producing identical snapshots |
| Pipeline tools for lineage | None — lineage derived from SQL | View definitions (and, at publish time, reporting views and Looker Studio blend configs) are parsed into the lineage graph; no `LineageProvider` connector needed for the demo |

## 2. System classes and query conventions

`conventions.md` in the customer KB defines two system classes and how agents must query each:

**SQL-queryable — `supabase`.** Dialect: PostgreSQL. Execution: read-only role, `SELECT` only, `statement_timeout` enforced, row cap. Report-grade SQL that will back a Looker Studio data source is materialized as a view in the `reporting` schema via migration PR — never ad-hoc against production for recurring reports.

**API-queryable — `ga4`, `gsc`.** No SQL. GA4 is queried through the Data API `runReport` (dimensions/metrics as documented in the KB; quota-aware). GSC through the Search Analytics API (fixed dimension/metric set). Cross-source questions resolve one of two ways, and entity docs say which: (a) Looker Studio **blending** joined on documented entity keys, for recurring reports; (b) agent-side fetch-and-combine, for ad-hoc answers.

## 3. Connector designs

### 3.1 Supabase / Postgres connector
One introspector, two input modes, one output (the normalized snapshot):

- **DDL mode (start here):** apply the customer's DDL files to an ephemeral Postgres container, then introspect it exactly as if live. No SQL parsing, no drift between modes.
- **Live mode (later):** same introspector against their database using a read-only role, over `pg_catalog`/`information_schema`: schemas, tables, views *including their full SQL definitions* (`pg_get_viewdef` — the input to lineage derivation), columns, types, defaults, PK/FK/unique constraints, indexes, comments (`pg_description`), row estimates.

Sync triggers: CI webhook on the customer's migrations repo (their schema-change PR → our KB PR) — this works in *both* modes; scheduled polling added once live mode is on.

### 3.2 GA4 connector
Inputs: property ID + service account with read access. Pulls the Data API metadata endpoint (all standard + custom dimensions and metrics available on that property), the Admin API custom definitions (custom dimensions/metrics with scope), and the key events list. Output: one doc per dimension/metric group, one events doc. Sync: scheduled (custom definitions change rarely; nightly is plenty).

### 3.3 GSC connector
Inputs: verified property + service account. Schema is fixed (dimensions: `query`, `page`, `country`, `device`, `date`, `searchAppearance`; metrics: `clicks`, `impressions`, `ctr`, `position`), so the doc is largely static; the connector contributes the property list, verified state, and data freshness notes. Sync: scheduled.

## 4. Normalized metadata snapshot (draft schema)

Every connector emits this shape; the generator and sync engine consume only this.

```json
{
  "snapshot_version": "1",
  "system": "supabase",
  "system_class": "sql | api",
  "captured_at": "2026-07-03T00:00:00Z",
  "source_mode": "ddl-file | live | api",
  "objects": [
    {
      "kind": "table | view | api_dimension | api_metric | api_event",
      "schema": "public",
      "name": "orders",
      "description": "from DB comment or API metadata, if any",
      "schema_hash": "sha256-of-normalized-definition",
      "columns": [
        {"name": "id", "type": "uuid", "nullable": false, "default": null, "description": null}
      ],
      "keys": {"primary": ["id"], "foreign": [{"columns": ["user_id"], "ref": "public.users.id"}]},
      "stats": {"row_estimate": 120000}
    }
  ]
}
```

API sources map into the same shape: a GA4 metric is an object of kind `api_metric` with no columns but with `data_type`, scope, and formula fields in `stats`; the hash mechanism and sync diffing work identically.

Lineage is a separate versioned artifact rather than part of the snapshot: `LineageProvider` connectors and the core's SQL parser emit graph edges (source → operation → target, column-level where derivable), which the generator merges into `lineage/graph.json`. For this customer, all lineage comes from parsing view definitions captured in the Postgres snapshot — no pipeline connector required.

## 5. Customer KB layout and doc templates

```
kb/
├── index.md
├── conventions.md                  # §2 above, rendered
├── systems/
│   ├── supabase/
│   │   ├── index.md                # per-schema table listing, hot/stub status
│   │   ├── public/orders.md        # human-owned semantics
│   │   └── public/orders.schema.md # machine-owned, regenerated
│   ├── ga4/
│   │   ├── index.md
│   │   ├── dimensions.md / metrics.md / custom-definitions.md / events.md
│   └── gsc/
│       └── index.md                # properties + fixed schema doc
├── entities/
│   ├── user.md          # supabase.public.users ↔ GA4 userId / clientId
│   ├── page.md          # gsc.page ↔ GA4 pagePath ↔ content tables
│   └── conversion.md    # GA4 key events ↔ supabase transactions/orders
├── metrics/             # certified definitions, incl. cross-source ones
├── lineage/             # graph.json (machine-owned) + view/blend annotations
└── .contextlayer/       # source configs, sync policy, role map
```

Machine-owned table doc front-matter (generated):

```yaml
---
object: supabase.public.orders
schema_hash: "sha256:…"
generated_at: 2026-07-03
source_mode: ddl-file
status: machine
---
```

Human-owned doc front-matter:

```yaml
---
object: supabase.public.orders
written_against_schema_hash: "sha256:…"
last_verified: 2026-07-03 (name)
status: verified | draft | stale | contaminated
sources: ["customer doc: orders-service.md", "enrich skill draft"]
---
```

Body sections for human-owned table docs: Purpose · Grain · Column meanings & enum decodings · Join guidance · Reporting notes (which reporting views expose it) · Warnings.

## 6. Work breakdown

| Task | Content | Exit criterion |
|---|---|---|
| 1.1 | Snapshot schema finalized (from §4), with fixture files for all three systems | Fixtures validate against JSON Schema; sync diff runs on fixtures |
| 1.2 | Postgres introspector + ephemeral-DDL mode | Customer DDL → snapshot; snapshot identical when same DDL is introspected live in a test container |
| 1.3 | GA4 connector | Live pull from customer property produces dimension/metric/event objects incl. custom definitions |
| 1.4 | GSC connector | Property list + fixed schema rendered |
| 1.5 | Generator + templates (§5) | Snapshots → repo renders; regeneration is idempotent (no-op diff when nothing changed) |
| 1.6 | Customer KB bootstrap | Generated KB merged into a git repo; `conventions.md` + role map committed |
| 1.7 | Existing-docs ingestion | Customer's documentation converted to human-owned docs via the `enrich` Claude Code skill, landed as PRs |
| 1.8 | Entity drafts | `user`, `page`, `conversion` entity docs drafted with concrete key mappings, reviewed by customer |
| 1.9 | Lineage derivation | Column-level lineage parsed from view SQL in the customer DDL (later extended to reporting views and blend definitions), merged into `lineage/graph.json` | For every view in the DDL, upstream tables and column mappings resolve correctly; `get_lineage` walks them |

Tasks 1.2–1.4 are parallel after 1.1. Phase 1 exit (per master spec): the customer's generated KB is merged in their git server, docs render correctly, and an agent reading only the KB can correctly describe the estate.

## 7. Looker Studio adapter — capability ruling (feeds phase 8)

Recorded now because it shapes entity and metric docs. Capability flags: `create_report: no` (no authoring API), `template_link: yes` (Linking API — GA4 and GSC connectors are supported), `sql_backing: via reporting views` (Looker Studio Postgres connector pointed at agent-authored views in the `reporting` schema, shipped as migration PRs), `cross_source: blending` (join keys must be documented per entity). The realistic M3 journey: agent ships the reporting view (PR), then hands the user a pre-wired template link; one human click instantiates the report.

## 8. Customer ask list

DDL files and existing documentation handed over (seeds 1.2 and 1.7). GA4 property ID + read-access service account; GSC verified property + service account (1.3, 1.4). Location of their migrations repo + permission to add a CI webhook (sync). Supabase tier — is a read replica available? Their git server for hosting the KB repo. And for phase 2: ten real report requests they actually want, ideally with any existing SQL — this seeds the golden benchmark.

## 9. Risks specific to this customer

Direct-on-OLTP reporting is the main operational risk — mitigated by the read-only role, timeouts, the reporting-views pattern (recurring reports hit views, not ad-hoc queries), and a replica when available. GA4 Data API quotas can throttle heavy report iteration — mitigated by caching runReport results during a session and documenting quota behavior in `conventions.md`. Looker Studio's API ceiling caps automation at "one click to instantiate" — set this expectation with the customer now, not at M3.
