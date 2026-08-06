# Contract Specification — Capability Interfaces (v1)

Status: v1 draft for implementation. Defines the six capability interfaces of `platform-architecture.md` §2.1 as language-agnostic JSON contracts carried by the job protocol (`job-protocol-spec.md` §4.2 maps each capability to a job type). Snapshot-producing behavior defers to `snapshot-schema-spec.md`; the merged lineage artifact defers to the lineage-format spec; this document owns everything in between: the connector manifest, the request/result shape per capability, identity and guardrail propagation, and per-capability invariants.

---

## 1. Scope

**In scope:** the connector manifest; common envelopes (config, identity, guardrails, errors); request/result contracts and invariants for `MetadataProvider`, `QueryExecutor`, `UsageProvider`, `KnowledgeProvider`, `Publisher` (including the capability-flag registry), `LineageProvider`; conformance tests per capability.

**Out of scope:** transport (job protocol), snapshot format, merged `graph.json` format, MCP tool semantics, and SDK ergonomics (the Python base classes are informative renderings of these contracts, never their source of truth — ruling CI-1).

## 2. Design rulings

| # | Ruling | Rationale |
|---|---|---|
| CI-1 | The normative contract is the JSON `payload`/`result` shape per job type; SDK classes are renderings | Language-agnostic connectors in anything ("any process that emits valid snapshot JSON and speaks the job protocol") |
| CI-2 | Every connector ships a **manifest** declaring capabilities, modes, config schema, credential requirements, rate-limit policy | Claim matching, Connections UI, and the conformance harness all read one file instead of probing code |
| CI-3 | Guardrails: the **gateway is authority** (attaches verdicts pre-enqueue); the executor additionally enforces locally what it can | Defense in depth; neither side trusts the other to have done it |
| CI-4 | Interactive capabilities receive the resolved OIDC **identity**; connectors never re-authenticate the user and never see user credentials | One identity model everywhere; audit and target-side mapping without credential sprawl |
| CI-5 | Effective Publisher capabilities = **manifest flags ∩ tenant probe** (`test_connection` refinement) | Licensing-dependent ability (Power BI Pro vs Fabric) resolved generically, recorded per connection |
| CI-6 | One `execute` envelope, two request dialects discriminated by `system_class` (`sql` statement vs structured `api` request) | Uniform gateway, audit shape, and result handling across Supabase and GA4/GSC |
| CI-7 | Results are inline and capped (job protocol §6.4); `truncated: true` is an explicit result fact, never silent | An agent must be able to tell the user "this is the first 50k rows," not present a truncation as the answer |
| CI-8 | Capability-specific errors ride the job-protocol taxonomy via `error.detail.capability_code` | One outer taxonomy for health/retry logic; per-capability precision preserved underneath |

## 3. Connector manifest (`connector.yaml`, shipped in the connector artifact)

```yaml
name: postgres
version: 0.3.1
protocol_version: 1
snapshot_version: "1"
capabilities:
  metadata:  { modes: [ddl-file, live] }
  query:     { dialect: postgresql }
  usage:     { modes: [live] }             # pg_stat_statements; absent if not implemented
config_schema: ./config.schema.json        # JSON Schema for payload.config
credentials:                               # what the runner will resolve from the vault
  - { key: dsn, required_for: [live, query, usage], description: "read-only role DSN" }
rate_limit: { strategy: none }             # or: {strategy: token-bucket, ...} — SDK primitives
health_probe: builtin                      # implements test_connection
```

A publisher adapter's manifest instead declares `capabilities.publish` with its static flag set (§8.1). The manifest is validated at connector release (conformance CC-1) and re-read by the core when a connection is configured; `config_schema` drives the Connections module's form generation.

### 3.1 Health probe — `health_probe: builtin`, job type `test_connection`

*Additive amendment, authorized by D-110.3c. Documents a surface that shipped at A-3 and had no section here; nothing below changes behaviour.* It is documented under the manifest rather than given a capability section of its own because it **is** a manifest declaration and it spans capabilities: `test_connection` is the one job type that maps to no single provider.

A connector declaring `health_probe: builtin` opts into the SDK's probe; the runner adds `test_connection` to its claim declaration for that connector, and the core's Connections module (dashboard spec §3) is its caller. Adapters that declare nothing are never asked.

**Two rules make the verdict worth trusting.**

1. **It opens no new path to a credential.** Every check reuses a surface that already existed for another reason — the config gate the snapshot engine runs, the introspection-role check at the head of every live snapshot job, the G3 execution-role wall the runner preflights at startup. A probe with its own credential path would be a second thing to keep honest.
2. **It never reports a pass it did not perform.** This is the `unprobed` contract below, and it is the reason the probe exists: a green tick beside a connection nobody has ever successfully used is the failure A-3 was called to prevent.

**Preflight surfaces.** The probe runs the config gate first, then calls `preflight(config)` on each capability in `("metadata", "query", "publish")` that the connector actually registers. A capability the connector does not implement is skipped silently — it was never claimed.

| Capability | Method | What it must do | Default when unimplemented |
|---|---|---|---|
| `metadata` | `MetadataProvider.preflight` | The cheapest real thing that proves the source answers, **through the same credential resolution `introspect` uses**: connect and read the role, or make the one GET the snapshot job would make first | `{"probed": false, "reason": …}` |
| `query` | `QueryExecutor.preflight` | The G3 startup check on demand — for SQL executors, verify the execution role cannot write | `{"probed": false, "reason": …}` |
| `publish` | `Publisher.preflight` | Tenant/licensing probe. CI-5's refinement lives here when built: a probe may only ever **narrow** the manifest's declared flags, never widen them. Unbuilt in v1 | `{"probed": false, "reason": …}` |

**Result shape** (`succeeded`): `{ok, system, connector: {name, version}, checks: [...], unprobed: [...]}`. Each check is `{capability, status, facts?, message?}` with `status` one of `pass` | `warn` | `unprobed`. Facts are `redact_deep`-scrubbed before they leave the runner (JC-8) — a probe exists to touch credentials, so its own report is the likeliest leak site.

**`unprobed` semantics — normative.** A preflight returning `probed: false` puts its capability in the `unprobed` list and gives its check `status: "unprobed"`. **`unprobed` is not a pass, and no consumer may render it as one.** The job still `succeeded`: the probe ran correctly and its honest answer is "this capability was not exercised." Consumers state it as its own third thing — the Connections module shows it beside the health verdict rather than folding it into green (dashboard spec §6). A connection whose every capability is `unprobed` has been *checked*, not *verified*, and the two pilot publisher adapters are exactly that case.

**Failure mapping.** The probe fails with the connector's own error code so the outer taxonomy stays meaningful, and `detail` carries `checks` so far plus the `capability` that failed:

| Raised | Job error | Why it matters |
|---|---|---|
| `ConfigError`, or config invalid against `config_schema` | `config_error`, non-retryable, `detail.capability_code: "config_schema"` | A config that could never work is not a credential problem |
| `AuthError` | `auth_error`, non-retryable | This is what the Connections module turns into the operator's re-auth prompt (A-3 gate clause), naming the credential **reference** and never a value |
| `SourceUnavailable` | `source_unavailable` | The source, not the credential |
| `QuotaExceeded` | **not a failure** — `status: "warn"`, probe continues | Hitting quota proved reachability and authentication, which is what was asked. Never a `defer`: nobody is waiting behind a probe to do real work |
| anything else | `internal`, retryable, traceback in `detail` | Job §6.7 |

**Credential references** resolve exactly as for any other job (job protocol §7, J-4): the probe receives resolved values through the same injection path, holds them for the job's duration only, and the vault stage's own failure is an `auth_error` with `detail.stage: "vault"` — distinguishable from the source refusing valid credentials, which is the distinction the re-auth prompt depends on.

## 4. Common envelopes

**Config** (`payload.config`): connector-specific, valid against the manifest's `config_schema`, containing no secrets (credential *references* travel separately, job protocol §7). Always includes `system` (the deployment-unique name) and, for metadata jobs, `mode`.

**Identity** (interactive payloads only):

```json
"identity": { "subject": "oidc|a.demir@customer.example", "roles": ["sales"],
              "display": "A. Demir", "session_id": "s-…", "intent": "monthly net sales by region" }
```

`intent` is the user's plain-language request as captured by the MCP server — it feeds audit and the query comment tag. Connectors treat identity as data (tagging, target-side mapping), never as an authentication credential (CI-4).

**Guardrails** (attached by the gateway, CI-3):

```json
"guardrails": { "row_cap": 50000, "timeout_s": 60, "statement_class": "select-only",
                "validated_against": "sha256:<snapshot canonical body hash>" }
```

`validated_against` pins which snapshot `validate_sql` passed on — if the executor's connection observes a different schema version mid-flight, that is the race the audit trail can now explain.

**Errors**: outer `error.code` from the job-protocol taxonomy; capability precision in `error.detail.capability_code` (documented per capability below) plus free-form `detail`.

## 5. MetadataProvider — job type `snapshot`

**Payload:** `{config, credentials}` with `config.mode` ∈ the manifest's declared modes.
**Result:** one snapshot document. All invariants are the snapshot spec's (validity, idempotency C-2, mode invariance C-3, hash reproducibility C-4, all-or-nothing S-6); this interface adds only:

- **MP-1:** the connector must emit `source_mode` equal to `config.mode` — no silent mode fallback. If the requested mode is unavailable (e.g. live DSN unreachable in `live` mode), fail `source_unavailable`; never quietly satisfy the job from cached DDL.
- **MP-2:** `source_properties` keys must be documented in the connector's docs and stable across versions (additive only), mirroring snapshot S-7.

## 6. QueryExecutor — job type `execute`

**Payload:**

```json
{ "config": { "system": "supabase" }, "credentials": [ … ],
  "identity": { … }, "guardrails": { … },
  "request": {
    "dialect": "sql",
    "statement": "SELECT region, sum(net) FROM reporting.v_net_sales …",
    "params": []
  } }
```

API dialect (`"dialect": "api"`) carries a structured request instead:

```json
"request": { "dialect": "api", "operation": "runReport",
             "body": { "dimensions": [...], "metrics": [...], "dateRanges": [...] } }
```

`operation` values and `body` schema are declared per connector in its manifest docs (GA4: `runReport`; GSC: `searchAnalytics.query`). The gateway validates API requests against the KB's documented dimension/metric surface exactly as `validate_sql` validates SQL — one guardrail concept, two dialects (CI-6).

**Executor duties (normative):**

- **QE-1 (local enforcement, CI-3):** SQL — open the connection read-only where the engine supports it, set the engine's statement timeout to `guardrails.timeout_s`, and apply the row cap (cursor fetch limit or injected LIMIT, engine-appropriate). API — apply the cap to pagination and stop.
- **QE-2 (comment tagging):** SQL statements are executed with a leading comment `/* contextlayer user=<subject> session=<session_id> intent=<hash> */` — this is the product-spec §7 mechanism by which the system generates its own usage signal post-launch. The full intent text stays in the audit log; only its hash rides the wire.
- **QE-3:** parameterized execution when `params` present; connectors must not interpolate.
- **QE-4 (quota):** API executors surface quota exhaustion as job-protocol `defer` only for batch contexts; in interactive context (this job class) quota is a terminal `guardrail`-class error with `capability_code: quota_exhausted` and the retry-after in detail — the user is waiting, deferral would hang them.
- **QE-5 (result value encoding, D-85 amendment):** `rows` carry JSON values only, and the mapping from source types is normative for **every** QueryExecutor, not one engine's. `columns[].type` continues to carry the source-native type name, so a string value is never ambiguous about what it encodes.

  | Source type | JSON encoding |
  |---|---|
  | date | ISO-8601 text, `YYYY-MM-DD` |
  | timestamp / timestamptz | RFC3339 text, offset preserved as the source returns it |
  | time | text |
  | interval | the source's text rendering |
  | numeric / decimal | **string**, never a float — no silent precision loss |
  | int2/4/8, float4/8, bool | native JSON values; an integer beyond the JSON-safe range becomes a string under the same fidelity rule |
  | uuid | string |
  | bytea / binary | base64 string |
  | json / jsonb | passed through as native JSON |
  | arrays, and every type with no listed mapping | the source's text rendering |

  The catch-all is the point: an unmapped type is rendered, never dropped and never a crash. Rationale is the same fact-fidelity rule the snapshot layer applies to metadata (S-8) — the platform hands over what the source said, and a lossy numeric is a changed fact.
- **QE-6 (serialization failure):** a value that cannot be encoded fails the **job** through the job protocol's standard error envelope (§6.7 `internal`) — no new capability code, because it is our defect and not a source refusal. It must not take the runner process down with it: the SDK's obligation to map exceptions to the §6.7 taxonomy (job spec §6.7) means an unexpected exception anywhere in job execution fails that job and the runner goes on serving the next one.

**Result:**

```json
{ "columns": [ {"name": "region", "type": "text"} ],
  "rows": [ ["EMEA", 1250000] ],
  "row_count": 2140, "truncated": false,
  "duration_ms": 812, "source": {"executed_on": "replica|primary|api", "engine_version": "…"} }
```

`truncated: true` whenever the cap was hit (CI-7). `executed_on` feeds the audit trail's P2-topology evidence.

**Capability codes:** `syntax_error`, `permission_denied_at_source`, `timeout`, `row_cap` (both mapped outer `guardrail`), `quota_exhausted`, `schema_mismatch` (statement referenced an object the live schema lacks — the validate/execute race; triggers a deterministic fault-ledger entry, HLR §6 class 1).

## 7. UsageProvider — job type `usage`

**Payload:** `{config, credentials, window: {from, to}}`.
**Result:**

```json
{ "window": {"from": "…", "to": "…"},
  "objects": [
    { "object": "public.orders", "kind": "table",
      "query_count": 412, "distinct_users": 9, "last_accessed": "…" } ],
  "join_pairs": [
    { "left": "public.orders", "right": "public.users",
      "on": [["user_id","id"]], "observed": 213 } ],
  "metric_candidates": [ ]
}
```

Invariants: **UP-1** — literals are stripped at the source side of the boundary; raw query text never leaves the connector (product-spec §7's in-VPC mining promise is enforced *here*, not downstream). **UP-2** — `join_pairs` and `metric_candidates` are optional, additive sections; `objects` counts are the v1 floor. The sync engine consumes `objects` for hot/stub classification (usage drift, snapshot SS-4 revisit path); `join_pairs` feed enrich as evidence-grade `sources` ("join path observed in N historical queries"). The demo customer does not exercise this capability (`pg_stat_statements` available later if wanted).

## 8. Publisher — job type `publish`

### 8.1 Capability-flag registry (manifest `capabilities.publish`)

| Flag | Values | Meaning |
|---|---|---|
| `create_report` | `full` \| `template_link` \| `api` \| `none` | Terminal state of journey J3 (HLR §8 P5). `api` (amendment, report-authoring spec §12.1 / D-91, 2026-07-29): the report is created programmatically through the two-call `publish_report` mode contract (MCP §6.8) — the adapter delivers the data model (`deliver_model`), the session's report skill authors and deploys the visual definition, and the verified deployment is attested (`attest`) |
| `create_dataset` | `yes` \| `no` | Can the adapter create/point data sources |
| `sql_backing` | `native` \| `views` \| `none` | How agent SQL becomes a data source (`views` = reporting-views pattern) |
| `cross_source` | `native` \| `blending` \| `none` | Cross-system reports; `blending` requires entity blend keys documented (KB spec §7 entity template) |
| `scheduled_refresh` | `yes` \| `no` \| `tenant` | `tenant` = depends on licensing, resolved by probe (CI-5) |
| `git_integration` | `yes` \| `no` | Report definitions can live in git pre-publish (PBIP/TMDL, LookML) |

Reference declarations — Looker Studio: `{create_report: template_link, create_dataset: no, sql_backing: views, cross_source: blending, scheduled_refresh: no, git_integration: no}`. Power BI: `{create_report: full, create_dataset: yes, sql_backing: native, cross_source: native, scheduled_refresh: tenant, git_integration: yes}`.

**Amendment (report-authoring spec §12.1 / D-91, 2026-07-29) — the shipped Power BI declaration.** The Power BI adapter that ships under the report-authoring spec is the **push+PBIR leg** (RA-5/RA-6) and declares `{create_report: api, create_dataset: yes, sql_backing: views, cross_source: native, scheduled_refresh: no, git_integration: no}` — `cross_source: native` because documented blend keys become real semantic-model relationships (D-91.1's cross-source criterion); `sql_backing: views` because the delivered rows are the artifact's reporting-view-backed, gateway-executed results (RA-2); `scheduled_refresh: no` per RA-E (manual/skill-triggered revisions only in v1). The pre-existing Power BI declaration above describes the eventual full native connector (DirectQuery-class) and remains the reference point for the RA-6 escalation, not the shipped adapter.

**Effective capabilities** (CI-5): stored per *connection* as manifest flags refined by the last `test_connection` probe (e.g. Power BI probe downgrades `scheduled_refresh` on Pro-only tenants). The MCP server serves effective flags to the `report` skill so expectations are set at journey start, not at failure (HLR §8 P5 ruling).

### 8.2 Publish contract

**Payload:** `{config, credentials, identity, artifact, target}` where `artifact` is an intermediate report artifact (its format is the report-artifact spec; this contract treats it as opaque-but-versioned: `artifact.artifact_version` gates parsing) and `target` names a configured workspace the caller's role maps to — the MCP server has already enforced role→workspace; the adapter enforces it *again* at the BI side under its service identity where the platform allows (defense in depth, CI-3 spirit).

**Result:**

```json
{ "mode": "full | template_link | instructions",
  "created": [ {"type": "report", "id": "…", "url": "https://…"} ],
  "pending_human_steps": [ "Open the template link and click Create" ],
  "backing": [ {"type": "reporting_view", "ref": "reporting.v_net_sales", "pr_url": "…"} ] }
```

**Invariants: PB-1** — `mode` must be consistent with effective flags; an adapter must not attempt `full` when its effective `create_report` is `template_link` (fail `config_error` instead — this is a core bug, not a runtime surprise). **PB-2** — every created object is returned with a stable id + URL; publishes are idempotent per `(artifact.id, target)`: re-publish updates rather than duplicates where the platform allows, else returns `capability_code: already_published` with the existing URL. **PB-3** — `pending_human_steps` is mandatory whenever `mode ≠ full`; the skill relays it verbatim. **PB-4** — adapters record any visual-kind substitutions (formats spec §4.4) in `PublishResult.detail.visual_substitutions`.

**Capability codes:** `target_not_permitted`, `tenant_capability_missing`, `already_published`, `artifact_version_unsupported`.

**Amendment (report-authoring spec §12.1 / D-91, 2026-07-29) — the `deliver_model`/`attest` contract for `create_report: api` adapters.** For api-class targets, `publish_report` is a two-call contract (MCP §6.8; report-authoring spec §4/§7), and the §8.2 payload/result gain additive members:

- Payload gains `mode`: `"deliver_model" | "attest"`. An api adapter receiving no `mode` (or a non-api adapter receiving one) fails `config_error` — a core/registration bug in PB-1's sense, not a runtime surprise.
- `deliver_model` payload additionally carries `results`: an object mapping each artifact query `name` to its capability §6 execute result — **gateway-executed** under the caller's identity and profile guardrails (report-authoring RA-2: this member is the only thing that may feed a model). A result with `truncated: true` is refused by the core before enqueue — a capped result must never quietly become "the model" (CI-7). The payload may carry `previous`: the prior successful delivery's `results`, which the adapter uses to restore already-replaced tables when a mid-delivery failure would otherwise leave the model half-new (§5 complete-or-previous).
- `attest` payload additionally carries `attestation`: `{report_id, definition_hash}` — the skill-deployed report id and the sha256 of the verified deployed definition (report-authoring RA-7).
- `deliver_model` result: `{mode: "deliver_model", created: [{type: "dataset", id, url}], delivered: {workspace_id, dataset_id, tables: [{name, columns: [{name, type, source_type}], rows_delivered}]}, pending_human_steps: [], backing: […]}` — `delivered.tables[].columns` is the schema **as delivered** (`type` the target-side column type, `source_type` the §6 result's source-native name); the authoring skill generates field references against these names, never against guesses.
- `attest` result: `{mode: "attest", created: [{type: "report", id: <report_id>, url: <workspace report URL>}], pending_human_steps: [], backing: [], detail: {…}}`.
- **PB-2 for api adapters:** idempotency is identity-stability, not result-reuse — one dataset per `artifact.id` (named `cl-<artifact-id-short>`), created once and updated in place; a repeat `deliver_model` at an unchanged content hash is the data-only-revision case (report-authoring RA-8) and re-executes/re-pushes rows under the same revision and ids rather than short-circuiting to a stored result. Re-attesting the same `{artifact_id, revision}` updates the same attestation record.
- **PB-3 for api adapters:** `pending_human_steps` remains mandatory in shape but is expected empty — the remainder of the journey belongs to the authoring session, not a human; the terminal `attest` result carries `[]` or `["open the report"]` alone (ruling D-91.1's zero-manual-wiring measure). Anything more is a defect surfaced, not a step relayed as normal.

Capability codes gain `push_limit_exceeded` (a push-model table/row/rate cap would be exceeded — the error names the limit, the measured value, and the RA-6 Fabric/DirectLake escalation path; never a silent truncation) and `delivery_state_inconsistent` (a mid-delivery failure was followed by a failed restore, so the model may be half-new — the error names the tables in each state; loud by design, because when a double fault defeats complete-or-previous the state must be *reported*, never papered over).

## 9. KnowledgeProvider — job type `harvest`

**Payload:** `{config, credentials, scope?: {paths|folders|labels}, since?: cursor}` (`since` optional; v1 full harvests).
**Result:**

```json
{ "documents": [
    { "id": "gdrive:1AbC…", "title": "Orders service overview",
      "content_markdown": "…", "content_hash": "sha256:…",
      "uri": "https://drive.google.com/…", "modified_at": "…", "author": "…",
      "mentions": ["public.orders", "public.order_items"] } ],
  "cursor": "opaque-for-next-since" }
```

Invariants: **KP-1** — `content_markdown` is a normalization (connectors convert native formats), lossy conversion noted in `detail`; the original stays at the source, referenced by `uri`. **KP-2** — `mentions` is optional best-effort FQN detection to help the enrich skill seed `depends_on`; it is a hint, never authority (mirrors KB spec §6 step 5). **KP-3** — harvested content lands only in the enrich pipeline (drafts with `sources` citing `uri`), never directly into the KB.

## 10. LineageProvider — job type `lineage`

**Payload:** `{config, credentials}`.
**Result — an edge set, not a graph:** merging into `lineage/graph.json` is the core generator's job (lineage-format spec owns the merged artifact):

```json
{ "edges": [
    { "source": "supabase.public.orders", "target": "supabase.reporting.v_net_sales",
      "operation": "aggregate",
      "columns": [ {"from": ["net"], "to": "net_total"} ],
      "evidence": { "tier": "pipeline-tool", "ref": "dbt:model.sales.v_net_sales" } } ] }
```

Invariants: **LP-1** — `operation` is from the fixed taxonomy (product spec §5: `ingest, join, filter, aggregate, derive, cast, rename, dedupe, business-rule`); unknown operations are rejected at delivery (job-protocol J-6 applies beyond snapshots). **LP-2** — `evidence.tier` ∈ `pipeline-tool | sql-parse | human` per HLR §8 P3; connectors emit only the first; the core's SQL parser emits the second; the third exists only via human-owned annotation docs. **LP-3** — node names are snapshot FQNs; an edge referencing an FQN absent from the latest snapshot is delivered but flagged `dangling` by the merger (pipeline tooling often knows about objects before/after our snapshot does — flag, don't reject).

## 11. Conformance tests (capability harness, extends snapshot C-* and job JC-*)

| # | Test | Implements |
|---|---|---|
| CC-1 | Manifest validates; declared capabilities each have a registered job-type handler; `config_schema` is valid JSON Schema | CI-2 |
| CC-2 | `snapshot` with unavailable requested mode fails `source_unavailable` — no fallback snapshot emitted | MP-1 |
| CC-3 | SQL executor: canary DML/DDL statement is refused locally even when guardrails are (maliciously) absent from payload | QE-1, CI-3 |
| CC-4 | Row cap: result rows ≤ cap and `truncated: true` when source has more | QE-1, CI-7 |
| CC-5 | Comment tag present on executed SQL (observed via source-side statement log in the test container) | QE-2 |
| CC-6 | Interactive quota → terminal `guardrail`/`quota_exhausted`, never `defer` | QE-4 |
| CC-7 | Publish idempotency: same `(artifact.id, target)` twice → one object, second returns update/`already_published` | PB-2 |
| CC-8 | Adapter refuses modes beyond effective flags (`config_error`) | PB-1, CI-5 |
| CC-9 | Harvest result carries `content_hash` and `uri` for every document; canary secret in a source doc is not redacted here (content is customer data) but never appears in logs | KP-1, job §7 |
| CC-10 | Lineage edges: unknown operation rejected; dangling FQN delivered and flagged | LP-1, LP-3 |
| CC-11 | Usage result contains no literal values from queries (canary-literal test) | UP-1 |
| CC-12 | Result value encoding: every row of the QE-5 table exercised against a fixture view — temporal as ISO-8601/RFC3339 text, numeric as string, unmapped types rendered rather than dropped, and the whole result `json.dumps`-able | QE-5 |
| CC-13 | Poisoned job (a value the encoder cannot handle staged into a result): the job fails `internal` through the standard envelope, the runner process survives, and the next job on the same runner completes without lease expiry | QE-6, job §6.7 |
| CC-14 | Health probe honesty: a connector declaring a capability whose handler implements no preflight `succeeds` with that capability in `unprobed` and `status: "unprobed"` — never counted as a pass | §3.1 |
| CC-15 | Health probe error mapping: config invalid → `config_error` non-retryable before any credential is touched; a refused credential → `auth_error` non-retryable with the failing `capability` in `detail` | §3.1, A-3 gate |
| CC-16 | Health probe scrubbing: a preflight returning credential-shaped facts yields a result in which the secret does not appear | §3.1, JC-8 |

## 12. Open decisions (spec-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| CI-A | Result streaming for large `execute` results (beyond inline cap) | Not in v1; inline + `truncated` + "narrow your query" guidance; reporting views absorb recurring big pulls | If pilot shows legitimate >cap interactive needs |
| CI-B | `validate_api_request` as a distinct path vs folding into `validate_sql` | **Closed** — resolved by MCP ruling M-1: one tool, dialect-switched | — |
| CI-C | Publisher probes on a schedule vs only on `test_connection` | On configure + manual re-test only; licensing changes are rare | If stale effective flags cause failed journeys |
| CI-D | `KnowledgeProvider` incremental harvest (`since` cursors) | Optional field reserved; v1 connectors full-harvest, dedupe by `content_hash` | First large Drive/Confluence estate |
| CI-E | Per-connector SDK version pinning matrix (SDK ↔ protocol ↔ snapshot versions) | SDK release notes carry the matrix; manifest declares all three versions | First multi-version fleet reality |
| CI-F | Publish depth for Looker Studio — `template_link` only in v1 (filed D-89.6; no register item existed for this posture before, it lived only in the §8.1 reference declaration) | `create_report: template_link`. **Evidence that the cost is real, not theoretical:** PostgreSQL is not a Linking-API-configurable connector, so a database-backed source can never be prefilled by a link — every published report needs a human to re-point that data source and enter the reporting-role password, per report, forever. GA4/GSC prefill fine; the manual step is specific to SQL sources, which are exactly the recurring-report case | A customer for whom per-report manual wiring is unacceptable. Escalation paths, both outside the CP-7 fence: a Looker Studio **community connector** (we host the connector, it authenticates as itself) or the **Data Studio API** for programmatic report creation |
