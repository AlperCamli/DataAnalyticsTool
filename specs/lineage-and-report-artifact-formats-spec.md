# Contract Specification — Lineage Graph & Report Artifact Formats (v1)

Status: v1 draft for implementation. Two versioned artifact formats in one document: **`lineage/graph.json`** (machine-owned, KB-resident; the merged lineage graph) and the **intermediate report artifact** (the tool-agnostic report description that Publisher adapters translate). Producers and consumers are already contracted: lineage edges arrive via capability LP-1..LP-3 and the core SQL parser; the graph is walked by `get_lineage` (MCP §6.5) and the contamination scan (KB §6 step 3); artifacts are produced by the `report` skill (skill spec §5 S7), checked by `publish_report` (MT-10), and consumed by adapters under PB-1..PB-3.

---

## 1. Scope

**In scope:** node and edge models, edge identity and evidence-merging rules, the graph file format and walk semantics; the artifact envelope, identity/revision model, query/semantics/visual sections, blend expression, persistence and validation rules; conformance tests for both.

**Out of scope:** the SQL parser's internals (its *output* must conform to the edge model), adapter translation logic per BI tool, and visual rendering fidelity (adapters map the visual registry to their platform's nearest equivalent and record what they did in the publish result).

## 2. Design rulings

| # | Ruling | Rationale |
|---|---|---|
| F-1 | Edge identity = `sha256(source ‖ target ‖ operation)`; column mappings are edge properties, not identity | Stable IDs across regenerations; human annotation docs reference edge IDs (KB §4.5) and must not orphan when a mapping is refined |
| F-2 | Multi-tier attestations of one `(source, target, operation)` merge into a single edge with an **evidence array**; effective trust = strongest tier present | Corroboration, not duplication; the walk and the UI see one edge |
| F-3 | Gateway-observed edges (publishes, gateway-shipped reporting views) reuse tier `pipeline-tool` with `ref: "gateway:<audit-id>"` | First-party observation is at least tool-grade; avoids amending the three-tier taxonomy (HLR §8 P3) |
| F-4 | Published reports and data sources are **graph nodes**, written by the core from publish audit + artifact | The contamination walk terminates in the sentence the drift changelog needs: "affects these dashboards" |
| F-5 | Artifact identity = stable UUID + monotonic `revision`; content hash rides along for change detection only | PB-2 republish-as-update needs "same report, new content"; content-addressing would mint a new identity per edit |
| F-6 | Artifacts are persisted in ops Postgres at publish time; pre-publish drafts are session-local; git residence is the adapter's concern where `git_integration: yes` | Idempotency, audit, and F-4 node creation need a server copy; knowledge/ops split preserved (an artifact is an operational record, not estate knowledge) |
| F-7 | Every embedded query carries its `validated_against` snapshot pin; the server re-validates at publish | An artifact is not a bypass around the validation gate |
| F-8 | Both formats: closed schemas, additive-only within a version, integer-string version fields gate parsing | Mirrors snapshot S-7; artifacts outlive sessions and graphs outlive syncs, so both need the same evolution discipline |

## 3. Lineage graph format (`lineage/graph.json`)

### 3.1 Envelope

```json
{ "graph_version": "1",
  "generated_at": "2026-07-11T02:10:00Z",
  "inputs": [ {"kind": "sql-parse", "snapshot_ref": {"supabase": "sha256:…"}},
              {"kind": "provider", "system": "dbt", "job_id": "01J9…"},
              {"kind": "gateway", "through": "2026-07-11T02:00:00Z"} ],
  "nodes": [ … ], "edges": [ … ] }
```

`inputs` records exactly which evidence sets were merged — the graph's own provenance. The file is machine-owned (KB §3); regeneration follows generator idempotency (same inputs → byte-identical file; nodes and edges sorted by id).

**`generated_at` (clarifying amendment, task 1.9, applied):** the value is the latest `captured_at` among the input snapshots whose build last *changed this file's content* — never the builder's wall clock (the KB §4.1 rule, ported; rationale DECISIONS.md D-33/D-39). A regeneration whose output differs only in this member leaves the file byte-untouched. `sql-parse` inputs pin `snapshot_ref` as the sha256 of the snapshot's canonical body — `captured_at`-independent by snapshot S-3 — so an unchanged source state pins an unchanged `inputs` entry and the no-op is decidable from the envelope alone.

### 3.2 Node model

```json
{ "id": "supabase.reporting.v_net_sales",
  "node_kind": "view",
  "resolved": true,
  "doc": "systems/supabase/reporting/v_net_sales.schema.md" }
```

- `id` is the snapshot FQN for estate objects; for BI-side nodes (F-4): `"<target-system>.report.<publisher-id>"` / `"<target-system>.datasource.<publisher-id>"` using the stable ids from PB-2 results.
- `node_kind` ∈ snapshot kind registry ∪ `{report, datasource, external}`.
- `resolved: false` marks dangling nodes (capability LP-3): referenced by an edge but absent from the latest snapshots — served flagged by `get_lineage`, listed in the drift changelog, never silently dropped (a provider may legitimately know about objects before/after our snapshot does).
- `doc` links the node to its KB doc when one exists (how the contamination walk finds the docs to flag).

### 3.3 Edge model

```json
{ "id": "sha256:…",
  "source": "supabase.public.orders",
  "target": "supabase.reporting.v_net_sales",
  "operation": "aggregate",
  "columns": [ {"from": ["net"], "to": "net_total"} ],
  "evidence": [
    {"tier": "sql-parse", "ref": "view-def sha256:…"},
    {"tier": "pipeline-tool", "ref": "dbt:model.sales.v_net_sales"} ],
  "trust": "pipeline-tool",
  "annotations": ["lineage/sales-reporting.md#e-net-sales-agg"] }
```

- `operation` from the fixed taxonomy (`ingest, join, filter, aggregate, derive, cast, rename, dedupe, business-rule`); LP-1 rejection at delivery already guarantees inputs conform.
- `columns[].from` is a list (a derived column may draw on several); `to` is one target column; edges without derivable mappings omit `columns` — column-level *where derivable*, never fabricated.
- `evidence` per F-2; `trust` = strongest present tier, ordered `pipeline-tool > sql-parse > human` (HLR §8 P3; F-3 folds gateway into the strongest).
- `annotations` back-links human lineage-note docs whose `edges:` front-matter lists this id — the generator maintains the back-links at merge time so `get_lineage` can serve the *why* alongside the *what*.

**Edge id computation (clarifying amendment, task 1.9, applied):** F-1's `sha256(source ‖ target ‖ operation)` is normatively the SHA-256 of the UTF-8 encoding of `source + "\n" + target + "\n" + operation` (newline-delimited; `\n` cannot occur in an FQN or an operation name), rendered `"sha256:" + lowercase hex`. This encoding is frozen: annotation docs (KB §4.5) reference edge ids forever, so it must never change within `graph_version: "1"`. Rationale: DECISIONS.md D-40.

Human-declared edges (tier `human`) enter the graph from `lineage/<pipeline>.md` docs carrying a fenced `declared_edges:` YAML block (additive amendment to KB §4.5, recorded in §7 below) — the only path by which human knowledge becomes graph structure, and it is PR-reviewed like everything else.

### 3.4 Walk semantics (normative for `get_lineage` and the contamination scan)

Edges point in the direction of data flow. *Downstream* = follow edge direction from the start node; *upstream* = reverse. Each node is visited once per walk (cycles reported in the result, never traversed twice). The contamination walk (KB §6 step 3) is: downstream walk from each breaking-changed object → for every visited node, flag the docs reachable via `doc` and via `depends_on` declarations → record `contamination.path` as the edge-id sequence that reached the node. Depth is unbounded for the scan (correctness beats cost — it runs per drift, not per query) and capped at 10 for the interactive tool (MCP §6.5).

### 3.5 Scale rule

One file until it hurts: `graph.json` stays single-file below 25k edges; beyond that the generator shards by system (`lineage/graph/<system>.json` + a manifest) with identical semantics. Recorded as the shard trigger rather than an open decision — the format supports both from day one so sharding is not a migration.

### 3.6 Producer failure semantics — sql-parse (normative note, task 1.9 amendment, applied)

Two failure classes, deliberately asymmetric:

- **Unresolved reference** (parse succeeded; a referenced FQN is absent from the latest snapshots): the ruled marker path — dangling node with `resolved: false` (§3.2, capability LP-3, FG-3), edge kept, never a hard failure, never a silent drop. A legitimate estate condition with a format slot.
- **Parse failure** (a `stats.definition` the core parser cannot parse): **hard failure of the whole graph build — no graph is written** (atomic write; no partial file can exist). The error is loud and attributable: it names the object FQN and the `view-def sha256:` of the definition that failed, so the fix path is immediate. A parse failure is a platform defect; encoding it as graph content would launder it into downstream false negatives — the polarity snapshot D-2 rules out ("scan unnecessarily, never skip a scan").

Consumers inherit the guarantee: the contamination scan (KB §6 step 3) runs against a graph that is complete or absent, never quietly partial; an absent graph fails the drift run visibly. Rationale: DECISIONS.md D-41.

## 4. Intermediate report artifact format

### 4.1 Envelope

```json
{ "artifact_version": "1",
  "id": "ra-018f3c…",                 // UUID, stable across revisions (F-5)
  "revision": 3,
  "content_hash": "sha256:…",          // of canonical body, change detection only
  "title": "Monthly net sales by region",
  "created_by": {"subject": "oidc|a.demir@…", "session_id": "s-…"},
  "kb_ref": "<commit-sha>",
  "queries": [ … ], "semantics": { … }, "visuals": [ … ], "blend": null }
```

### 4.2 `queries[]` — the data

```json
{ "name": "net_sales",
  "system": "supabase",
  "request": {"dialect": "sql", "statement": "SELECT region, month, net_total FROM reporting.v_net_sales …"},
  "validated_against": "sha256:…",     // snapshot pin (F-7)
  "backing": {"mode": "reporting_view", "ref": "reporting.v_net_sales"} }
```

`request` reuses the capability CI-6 shape exactly (SQL or API dialect). `backing.mode` ∈ `direct | reporting_view | dataset_ref` tells the adapter how the query becomes a data source under its `sql_backing` flag: `views` adapters require `reporting_view` backing for recurring reports (the skill's SK-6 branch produced it); `native` adapters may take `direct`. `validated_against` enables the F-7 publish-time re-validation — cheap, and it converts "the schema moved since drafting" into a clean `revalidate_required` instead of a broken dashboard.

### 4.3 `semantics` — the KB bindings

```json
{ "metrics":    [ {"column": "net_total", "ref": "metrics/net-revenue.md", "certified": true} ],
  "dimensions": [ {"column": "region", "ref": "entities/sales-region.md"} ],
  "grain": "region × month",
  "trust_notes": [ "built on draft doc systems/ga4/metrics.md — user acknowledged" ] }
```

Every `ref` must resolve at publish (MT-10). `trust_notes` carries the K-TRUST disclosures that applied during drafting — they travel *into* the published world so a report built on a draft doc says so at its source, not only in a chat transcript that scrolled away.

### 4.4 `visuals[]` — the tool-agnostic presentation

```json
{ "kind": "line",                      // registry v1: table | line | bar | scorecard | pivot
  "query": "net_sales",
  "encoding": {"x": "month", "y": "net_total", "series": "region"},
  "title": "Net sales by region",
  "filters": [ {"column": "month", "kind": "date-range", "default": "last-2-quarters"} ] }
```

The visual registry is deliberately small and additive (F-8). Adapters map each kind to their platform's nearest equivalent and must record substitutions in the publish result's `detail` — fidelity is honest, not assumed. Layout is a hint (`layout: {order, sections}` optional field), never pixel geometry.

### 4.5 `blend` — cross-source reports

```json
{ "left": "gsc_pages", "right": "ga4_sessions",
  "keys": [ {"left_column": "page", "right_column": "pagePath",
             "entity_ref": "entities/page.md"} ],
  "join": "left" }
```

Present only when queries span systems. `entity_ref` is mandatory per key: blend keys come from the entity doc's documented mappings (HLR §8 P5 `cross_source: blending`), never improvised — and the reference makes the blend contaminable: a breaking change on the entity's mapped objects reaches this artifact through the graph (F-4 nodes + the artifact's semantics refs).

### 4.6 Persistence, idempotency, lineage effects

At `publish_report`, the server: (1) validates the artifact (schema, MT-10 ref resolution, F-7 re-validation of each query); (2) persists `{id, revision, body, content_hash}` to ops Postgres — same `id` + unchanged `content_hash` short-circuits to the existing publish result; (3) enqueues the publish job; (4) on success, writes F-4 nodes (`datasource`, `report`) and gateway-tier edges from each `queries[].backing` ref (or the underlying objects for `direct`) to the new nodes, into the next graph regeneration's input set. Republish of a known `id` with a new `content_hash` increments `revision` and updates (PB-2), never duplicates.

## 5. Conformance tests

| # | Test | Implements |
|---|---|---|
| FG-1 | Graph regeneration from identical inputs → byte-identical file; edge IDs stable when only `columns` mappings change | F-1, §3.1 |
| FG-2 | Two providers attesting one relationship → one edge, two evidence entries, trust = strongest | F-2 |
| FG-3 | Dangling provider edge → node `resolved: false`, served flagged by `get_lineage`, listed in drift changelog | §3.2, LP-3 |
| FG-4 | Cycle in fixtures → both walks terminate, cycle reported | §3.4 |
| FG-5 | Staged breaking change → contamination walk flags exactly the fixture's expected doc set with correct `contamination.path` | §3.4, KB §6 |
| FA-1 | Artifact with a non-resolving semantic ref → publish rejected before enqueue | §4.3, MT-10 |
| FA-2 | Snapshot moved since drafting → publish returns `revalidate_required`; nothing reaches the adapter | F-7 |
| FA-3 | Same `id` + same `content_hash` republished → prior result returned, no job enqueued; new hash → `revision+1`, adapter update path | F-5, §4.6 |
| FA-4 | Blend without `entity_ref` on every key → schema-invalid | §4.5 |
| FA-5 | Successful publish → `report`/`datasource` nodes and gateway-tier edges appear in the next graph regeneration | F-4, §4.6 |

## 6. Amendments to other specs (additive)

> **Status: applied.** Folded into home specs in the consolidation pass; retained as the change record.

1. **KB repository spec §4.5:** lineage annotation docs (`doc_class: lineage-note`) gain an optional fenced `declared_edges:` YAML block — the human-tier edge source (§3.3). KB CI validates the block against the edge model; the generator ingests it at merge.
2. **Capability interfaces spec §8.2:** `PublishResult.detail` gains a documented `visual_substitutions` list (adapters record §4.4 fidelity substitutions). Additive.

## 7. Open decisions (spec-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| FM-1 | Column-level contamination (walk narrowed to affected columns via `columns` mappings, not whole nodes) | Node-level flagging in v1; column mappings served as context in the flag detail | If pilot shows node-level flags are too noisy on wide models |
| FM-2 | Visual registry growth (maps, gauges, conditional formatting) | Five kinds in v1; additions via this register, adapter support declared per flag docs | First customer report the registry cannot express |
| FM-3 | Artifact retention in ops Postgres | Keep all revisions of published artifacts (they are audit evidence); prune drafts never persisted | Storage telemetry |
| FM-4 | Parameterized artifacts (runtime-bound filters beyond defaults) | Defaults only in v1; parameterization pairs with skill-spec SP-4 (saved re-runs) | Recurring-report demand in pilot |
| FM-5 | Cross-system lineage edges from blend usage (gsc.page ↔ ga4.pagePath as graph edges vs entity-doc-only knowledge) | Entity-doc-only in v1 (cross-system relations are human knowledge, snapshot §4.4 rationale); blend publishes create edges to the report node from *each* side, which captures the dependency without asserting source-to-source flow | If reconciliation questions need source-to-source cross-system edges |
| FM-6 | Column-mapping expressiveness gaps (one question: what can v1 `columns[]` not say?): (a) per-column derivation kind — passthrough vs derived vs cast is carried only by the edge-level single-valued `operation`; sketched additive path: optional `columns[].via`; (b) filter/join/group-key dependencies — a source column feeding no output column (e.g. a `WHERE`-only column) is not representable, since `to` is mandatory | Not expressible in v1; the edge-level `operation` and the relation-level edge carry the facts, and walks stay node-level (FM-1) so nothing is lost to consumers yet | FM-1's revisit (column-narrowed contamination) — both gaps gate it and must be decided together |
