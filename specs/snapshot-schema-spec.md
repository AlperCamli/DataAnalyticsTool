# Contract Specification — Normalized Metadata Snapshot (v1)

Status: v1 draft for implementation. Implements §5 J1/J2 and §8 P1 of `high-level-requirements-and-user-journeys.md`; formalizes §4 of `phase1-supabase-ga4-gsc-plan.md` and the `MetadataProvider` boundary of `platform-architecture.md` §2. Blocks phase-1 tasks 1.1–1.4.

The snapshot is the single boundary between connectors and the rest of the platform. Everything downstream — generator, sync/diff engine, `validate_sql`, lineage derivation — consumes only this format and never knows how a source was introspected.

---

## 1. Scope

**In scope:** the snapshot document format, its canonicalization and hashing rules, versioning and evolution rules, per-kind object models, the diff semantics the sync engine relies on, and the conformance tests every connector must pass.

**Out of scope:** the job protocol by which snapshots are transported (separate spec), the lineage graph format (separate spec — lineage is a distinct versioned artifact, not part of the snapshot), and generator template behavior.

## 2. Design rulings

| # | Ruling | Rationale |
|---|---|---|
| S-1 | Object identity is the tuple `(system, kind, schema, name)` | `kind` disambiguates API namespaces where dimension and metric names may collide; SQL systems get it for free |
| S-2 | `schema_hash` covers structural fields only; descriptions and stats are excluded | Separates "regenerate machine docs" (any change) from "run severity classification + contamination scan" (hash change). A comment edit must never contaminate a human doc |
| S-3 | Idempotency = byte-identical canonical body, excluding `captured_at` | Same source state → same bytes, making idempotency a trivial contract test; `captured_at` is envelope metadata and necessarily varies per run |
| S-4 | Mode invariance: all supported `source_mode`s of a connector must yield identical canonical bodies for the same source state | Guarantees the least-privilege-first rule (HLR §9.3) is free: starting in DDL-file mode and upgrading to live later produces no spurious diffs |
| S-5 | `kind` is an open registry, not a closed enum; consumers skip unknown kinds with a logged warning | Adding kinds stays additive; no version bump, no validator breakage |
| S-6 | Snapshots are all-or-nothing per system | A partial introspection fails the job (dead-letter → health feed); a silently shrunken snapshot would cascade into false "object removed" breaking changes |
| S-7 | Evolution is additive-only within a `snapshot_version`; field removal or semantic change bumps the version | Consumers ignore unknown fields; producers emit only fields defined for their declared version |
| S-8 | All free-text fields are carried verbatim from the source (comments, API descriptions); the snapshot never synthesizes prose | The snapshot is facts-only; interpretation belongs to the generator and the enrich skill |

## 3. Document envelope

A snapshot is one JSON document describing one system at one moment.

```json
{
  "snapshot_version": "1",
  "system": "supabase",
  "system_class": "sql",
  "source_mode": "ddl-file",
  "captured_at": "2026-07-11T02:00:00Z",
  "connector": { "name": "postgres", "version": "0.3.1" },
  "source_properties": { },
  "objects": [ ]
}
```

| Field | Type | Req | Semantics |
|---|---|---|---|
| `snapshot_version` | string | ✓ | Format version; parsers hard-fail on unknown versions |
| `system` | string | ✓ | Deployment-unique logical name from `.contextlayer/` source config. All cross-references (lineage, KB front-matter) use this name |
| `system_class` | `"sql"` \| `"api"` | ✓ | Drives query conventions (HLR §8 P2) and generator template family |
| `source_mode` | `"ddl-file"` \| `"live"` \| `"api"` | ✓ | Recorded for provenance; MUST NOT affect the canonical body (S-4) |
| `captured_at` | ISO-8601 UTC string | ✓ | Envelope metadata; excluded from idempotency comparison (S-3) |
| `connector` | object | ✓ | `name` + semver `version` of the producing connector; provenance for debugging, excluded from canonical body |
| `source_properties` | object | – | System-level facts that are not objects: e.g. GSC verified properties + verification state, GA4 property ID/timezone/currency, Postgres server version. Per-connector documented keys; additive |
| `objects` | array | ✓ | The estate; ordering per §6 |

**Canonical body** := the envelope minus `captured_at` and `connector`, serialized per §6. Idempotency (S-3) and mode invariance (S-4) are defined over the canonical body.

## 4. Object model

Every element of `objects` shares a common core; kinds extend it through `columns`, `keys`, and kind-specific documented `stats` fields.

### 4.1 Common core

```json
{
  "kind": "table",
  "schema": "public",
  "name": "orders",
  "description": "verbatim source comment/description or null",
  "schema_hash": "sha256:…",
  "columns": [],
  "keys": {},
  "stats": {}
}
```

| Field | Type | Req | Semantics |
|---|---|---|---|
| `kind` | string | ✓ | From the kind registry (§4.2); consumers skip unknown kinds with a warning (S-5) |
| `schema` | string | ✓ | SQL: the schema/namespace. API: the logical namespace (see per-kind rules) |
| `name` | string | ✓ | Source-native name, case preserved as the source reports it |
| `description` | string \| null | ✓ | Verbatim from source (`pg_description`, API metadata); never synthesized (S-8) |
| `schema_hash` | string | ✓ | `"sha256:" + hex`, computed per §5 |
| `columns` | array | ✓ (may be empty) | Ordered per §6; element shape in §4.3 |
| `keys` | object | ✓ (may be empty) | `primary`, `foreign`, `unique` arrays; shape in §4.4 |
| `stats` | object | ✓ (may be empty) | Kind-specific documented fields (§4.5); additive per connector |

### 4.2 Kind registry (v1)

| Kind | System class | `schema` means | Notes |
|---|---|---|---|
| `table` | sql | DB schema | Base tables |
| `view` | sql | DB schema | `stats.definition` carries the full normalized SQL definition — the input to core lineage derivation |
| `materialized_view` | sql | DB schema | As `view`, plus refresh semantics in `stats` when introspectable |
| `api_dimension` | api | logical group (e.g. `standard`, `custom`, or the API's own category) | No `columns`; typing via `stats.data_type` |
| `api_metric` | api | as above | `stats`: `data_type`, `scope`, `formula` (custom metrics) |
| `api_event` | api | `standard` \| `custom` \| `key` | GA4 events / key events; parameters may be listed as `columns` when the API exposes them |

Registry extensions (functions, procedures, DW models, external tables…) are additive per S-5 and land as amendments to this table.

### 4.3 Column shape

```json
{ "name": "id", "type": "uuid", "nullable": false, "default": null,
  "ordinal": 1, "description": null }
```

`type` is the source-native type string, normalized per connector rules (the Postgres connector emits `pg_catalog` canonical names, e.g. `int4` → `integer`). `ordinal` is the source-reported position and defines column ordering (§6). `default` is the source-native default expression string or null.

### 4.4 Keys shape

```json
{
  "primary": ["id"],
  "foreign": [ { "columns": ["user_id"], "ref": "public.users", "ref_columns": ["id"] } ],
  "unique":  [ ["email"] ]
}
```

`ref` is `schema.name` within the same system; cross-system relationships are *never* snapshot facts — they are human/entity-doc knowledge (KB `entities/`), because no source system can attest to them.

### 4.5 `stats` documented fields (v1)

| Kind | Field | Type | Source |
|---|---|---|---|
| `table`, `materialized_view` | `row_estimate` | integer | `pg_class.reltuples` or equivalent; excluded from hash |
| `table`, `materialized_view` | `indexes` | array of strings | Engine-canonical index definitions (Postgres: `pg_get_indexdef`), lexicographically sorted; indexes backing declared constraints are omitted (those facts ride `keys`); **excluded from hash** |
| `view`, `materialized_view` | `definition` | string | Normalized SQL (`pg_get_viewdef`); **included in hash** |
| `api_dimension` / `api_metric` | `data_type` | string | API metadata; **included in hash** |
| `api_metric` | `scope`, `formula` | string | Admin API custom definitions; **included in hash** |
| `api_event` | `is_key_event` | boolean | GA4 key events list; **included in hash** |

Connectors may add documented `stats` fields additively; each new field declares whether it is hash-included (structural) or hash-excluded (volatile) at the time it is registered. Undeclared fields are forbidden in emitted snapshots (S-7).

**Registration record (task 1.2 amendment, applied):** `indexes` (for `table` and `materialized_view`) and `row_estimate` extended to `materialized_view` were registered by the Postgres connector task, both hash-excluded. `indexes` is hash-excluded by ruling: an index cannot break a dependent or contradict a documented meaning (the S-2 test), and a hash-included polarity would make every routine `CREATE INDEX` a breaking change driving contamination scans (per the D-2 default for unlisted structural changes) — drift-pipeline noise worse than the edge it protects. *Caveat, by convention rather than polarity:* semantic uniqueness must be declared as a `UNIQUE` constraint, which lands in `keys.unique` (hash-included, structural); a unique index without a constraint rides `indexes` and is deliberately hash-excluded — it is a physical artifact until promoted to a declared constraint.

## 5. Hashing

`schema_hash` answers one question for the sync engine: *did the structural definition of this object change in a way that could break dependents or contradict human docs?*

**Hash input** := the canonical JSON serialization (§6 rules) of the object's structural projection:

- `kind`, `schema`, `name`
- `columns`, each reduced to `{name, type, nullable, default, ordinal}` (**`description` excluded**)
- `keys` (complete)
- hash-included `stats` fields per the §4.5 registry (`definition`, `data_type`, `scope`, `formula`, `is_key_event`)

Excluded: object `description`, column `description`s, all hash-excluded stats (`row_estimate`, `indexes`), and everything in the envelope.

**Algorithm:** `schema_hash = "sha256:" + hex(sha256(utf8(canonical_json(projection))))`.

**Consequences (by design):**
- Comment/description edits change the snapshot (→ machine-doc regeneration) but not the hash (→ no severity classification, no contamination scan). This implements ruling S-2.
- A view's hash changes when its SQL changes — which is exactly when lineage must be re-derived and downstream contamination re-evaluated.
- `row_estimate` drift never produces a hash change; nightly re-snapshots of a stable schema are hash-stable.

**SQL normalization for `definition`:** connectors emit the *source engine's* canonical form (Postgres: `pg_get_viewdef(oid, true)`), never raw user text. This makes formatting-only edits hash-neutral to the extent the engine normalizes them, with zero SQL parsing in the connector. Engines lacking a canonical form must apply the SDK's whitespace-and-case normalizer and declare so in their connector docs.

## 6. Canonical serialization and ordering

These rules make S-3 (idempotency) and S-4 (mode invariance) byte-testable:

1. JSON, UTF-8, no insignificant whitespace, `\n` line endings if pretty-printed for storage (the canonical form for hashing/comparison is compact).
2. Object keys sorted lexicographically at every nesting level.
3. `objects` sorted by (`kind`, `schema`, `name`), each lexicographic.
4. `columns` sorted by `ordinal`.
5. `keys.foreign` sorted by (`columns` joined, `ref`); `keys.unique` sorted lexicographically; column lists inside keys keep source-declared order.
6. Numbers: integers only in v1 (no floats in the schema); booleans and nulls literal.
7. Strings verbatim from source — no trimming, no case folding (except where an engine-canonicalization rule in §5 applies).

## 7. Diff semantics (contract with the sync engine)

The diff engine compares two snapshots of the same `system` by object identity (S-1) and classifies per object:

| Condition | Classification | Sync consequence |
|---|---|---|
| Identity present only in new | **added** | Additive: regenerate/create machine docs; no scan |
| Identity present only in old | **removed** | Breaking: contamination scan + downstream lineage walk |
| Both present, `schema_hash` differs | **changed (structural)** | Field-level sub-diff → severity per table below; scan on breaking |
| Both present, hash equal, bodies differ | **changed (metadata-only)** | Regenerate machine docs; never scans, never contaminates |
| Both present, bodies byte-equal | **unchanged** | No-op (generator idempotency: no diff → no write) |

Structural sub-diff severity:

| Structural change | Severity |
|---|---|
| Column added | additive |
| Column removed / renamed¹ / type changed / nullable tightened (`true→false`) | breaking |
| Nullable loosened (`false→true`), default changed | additive-with-note² |
| Key added | additive |
| Key removed or altered | breaking |
| View/matview `definition` changed | breaking³ (triggers lineage re-derivation + downstream walk) |
| API `data_type`/`scope`/`formula` changed | breaking |

¹ Rename is not directly observable; the diff engine flags a *rename candidate* when a removed and an added column in the same object share `type` + `ordinal`, and presents both interpretations in the drift PR changelog. ² Surfaced in the changelog but does not contaminate. ³ Downgraded to additive-with-note when re-derived lineage shows the output column set and mappings are unchanged.

Removal of an entire *system* from configuration is an administrative action (Connections module), never inferred from a missing snapshot — reinforcing S-6.

## 8. Validation artifacts

### 8.1 JSON Schema (normative)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://contextlayer.dev/schemas/snapshot/v1.json",
  "type": "object",
  "required": ["snapshot_version", "system", "system_class",
               "source_mode", "captured_at", "connector", "objects"],
  "additionalProperties": false,
  "properties": {
    "snapshot_version": { "const": "1" },
    "system": { "type": "string", "minLength": 1 },
    "system_class": { "enum": ["sql", "api"] },
    "source_mode": { "enum": ["ddl-file", "live", "api"] },
    "captured_at": { "type": "string", "format": "date-time" },
    "connector": {
      "type": "object",
      "required": ["name", "version"],
      "additionalProperties": false,
      "properties": { "name": {"type": "string"}, "version": {"type": "string"} }
    },
    "source_properties": { "type": "object" },
    "objects": { "type": "array", "items": { "$ref": "#/$defs/object" } }
  },
  "$defs": {
    "object": {
      "type": "object",
      "required": ["kind", "schema", "name", "description",
                   "schema_hash", "columns", "keys", "stats"],
      "additionalProperties": false,
      "properties": {
        "kind": { "type": "string", "minLength": 1 },
        "schema": { "type": "string", "minLength": 1 },
        "name": { "type": "string", "minLength": 1 },
        "description": { "type": ["string", "null"] },
        "schema_hash": { "type": "string", "pattern": "^sha256:[0-9a-f]{64}$" },
        "columns": { "type": "array", "items": { "$ref": "#/$defs/column" } },
        "keys": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "primary": { "type": "array", "items": {"type": "string"} },
            "foreign": { "type": "array", "items": { "$ref": "#/$defs/fk" } },
            "unique":  { "type": "array",
                         "items": { "type": "array", "items": {"type": "string"} } }
          }
        },
        "stats": { "type": "object" }
      }
    },
    "column": {
      "type": "object",
      "required": ["name", "type", "nullable", "default", "ordinal", "description"],
      "additionalProperties": false,
      "properties": {
        "name": { "type": "string", "minLength": 1 },
        "type": { "type": "string", "minLength": 1 },
        "nullable": { "type": "boolean" },
        "default": { "type": ["string", "null"] },
        "ordinal": { "type": "integer", "minimum": 1 },
        "description": { "type": ["string", "null"] }
      }
    },
    "fk": {
      "type": "object",
      "required": ["columns", "ref", "ref_columns"],
      "additionalProperties": false,
      "properties": {
        "columns": { "type": "array", "items": {"type": "string"}, "minItems": 1 },
        "ref": { "type": "string", "pattern": "^[^.]+\\.[^.]+$" },
        "ref_columns": { "type": "array", "items": {"type": "string"}, "minItems": 1 }
      }
    }
  }
}
```

Note `kind` and `stats` are deliberately open (S-5, §4.5): registry discipline is enforced by connector contract tests, not by the schema, so registry growth never breaks deployed validators.

### 8.2 Required fixtures (task 1.1 exit criterion)

Checked into the platform repo, validated in CI against §8.1:

1. `supabase-ddl.json` — tables + views + a matview, FKs, comments, from the demo customer's DDL.
2. `supabase-live.json` — same source state via live mode; must be canonical-body-identical to (1).
3. `ga4.json` — standard + custom dimensions/metrics, events incl. key events, `source_properties` with property metadata.
4. `gsc.json` — fixed dimension/metric set + `source_properties` with verified properties.
5. `drift-pair/` — before/after snapshots staging one instance of every §7 classification, including a rename candidate.

## 9. Conformance tests (every connector, every version)

| # | Test | Implements |
|---|---|---|
| C-1 | Emitted snapshot validates against §8.1 | — |
| C-2 | Two runs against unchanged source state → byte-identical canonical bodies | S-3 |
| C-3 | Same source state through every supported `source_mode` → identical canonical bodies | S-4, task 1.2 exit |
| C-4 | Recomputing every `schema_hash` from the emitted body reproduces the emitted value | §5 |
| C-5 | Description-only change at source → body differs, no hash differs | S-2 |
| C-6 | Structural change at source → exactly the affected objects' hashes differ | S-2, §7 |
| C-7 | Introspection failure mid-run → no snapshot emitted, job fails to dead-letter | S-6 |
| C-8 | Emitted `stats` contain only registered fields | S-7 |

The SDK ships C-1–C-8 as a reusable test harness; a connector without a green conformance run cannot be released (platform-architecture §2.2).

## 10. Open decisions (spec-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| SS-1 | Type normalization across engines (is `integer` vs `INT64` a "type change" when a source migrates?) | Types are source-native; cross-engine comparison is out of scope for v1 diffing | First customer migrating a source between engines |
| SS-2 | Sample values in snapshots | Not in the snapshot at all in v1; opt-in masked sampling would be a separate `stats` registration | If enrich quality on Level-1 sources proves insufficient |
| SS-3 | `api_property` as an object kind vs. `source_properties` envelope data | Envelope (`source_properties`) — properties are system facts, not queryable objects | If per-property docs need machine ownership/hashing |
| SS-4 | Row-estimate change as a *usage* drift signal | Ignored by diff in v1 (hash-excluded, metadata-only) | When usage-driven enrichment suggestions (spec §7 of product doc) are built |
| SS-5 | CHECK constraints in the snapshot | Dropped at the boundary in v1 (no object-model slot). High-value: they encode semantic facts (value domains, invariants) the KB's human docs exist to explain. Sketched additive path: register `stats.checks` for `table` — engine-canonical expression strings (Postgres: `pg_get_constraintdef`), lexicographically sorted, **hash-included** (a tightened CHECK can contradict documented meanings). **Trigger fired, 2026-07-27 (D-86.3b): first real-world confusion on record** — a platform file and a recorded ruling (D-81) both asserted that `ai_runs.status` was unconstrained free text with an "ungrounded vocabulary", when `ai_runs_status_check` enforces `pending \| completed \| failed`. The absence was ours, not the source's, and it was read as a fact about the estate. Decision scheduled at CP-8; capture is a spec + registry amendment and does not block M3 | **Fired** — the CP-7 enrichment run needed exactly these facts and had to read `pg_constraint` out of band to get them |
| SS-6 | Enum type labels in the snapshot | Dropped at the boundary in v1 (enum-typed columns carry only the type name, e.g. `public.order_status`). High-value: labels are exactly the enum decodings SS-2 leaves open, and carrying them as facts would ground that question without sampling. Sketched additive path: new kind `enum_type` (`schema` = type's schema, `columns` empty, labels as hash-included `stats.labels` in declared order) — additive per S-5 | First customer schema using native enums for report-relevant states |
| SS-7 | Known no-slot gaps: identity/generated column markers (emitted as `default: null`), schema-level and index-level comments, partition key definitions (`pg_partitioned_table`) | Dropped at the boundary in v1, recorded per connector docs. Partition key is the strongest future §4.5 candidate — it tells query-writing agents how to prune | An agent journey measurably fails for lack of one of these facts |
