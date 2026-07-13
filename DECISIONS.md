# DECISIONS — task 1.1 (snapshot layer)

Ambiguities encountered while implementing `spec/snapshot-schema-spec.md`,
with the chosen reading for each. Per the standing change process, entries
marked **[amendment proposed]** should go to the spec's open-decisions
register / an upstream amendment; the code implements the stated reading
until the register rules otherwise.

---

## D-0 — Spec reading implemented (identity, hashing, diff)

Recorded so review can check the implementation against one statement of
intent rather than reverse-engineering it from code.

**Object identity (S-1).** The tuple `(system, kind, schema, name)`. One
snapshot describes one system, so the within-diff key is
`(kind, schema, name)`; the diff engine errors if the two snapshots'
`system` fields differ, and errors on duplicate identities inside one
snapshot (a diff keyed on a non-unique key is ill-defined; see D-6).

**Hash inclusion (S-2, §5).**
`schema_hash = "sha256:" + hex(sha256(utf8(canonical_json(projection))))`
where projection =

- `kind`, `schema`, `name`
- `columns`: each reduced to `{name, type, nullable, default, ordinal}`
  (column `description` excluded), sorted by `ordinal`
- `keys`: complete, ordered per §6 rule 5
- `stats`: only the hash-included §4.5 fields for the object's kind
  (`definition`, `data_type`, `scope`, `formula`, `is_key_event`)

Excluded: object `description`, column `description`s, hash-excluded stats
(`row_estimate`), and every envelope field. Canonical JSON per §6: compact,
UTF-8, keys sorted lexicographically at every nesting level.

**Diff classification (§7).** Keyed on identity: only-in-new → `added`
(additive); only-in-old → `removed` (breaking); both present with different
`schema_hash` → `changed_structural` with field-level sub-diffs; hash equal
but canonical object bodies differ → `changed_metadata_only`; byte-equal →
`unchanged`. Sub-diff severities exactly per the §7 table; rename candidate
flagged when a removed and an added column in the same object share
`type` + `ordinal` (both interpretations surfaced; the removal stays
breaking).

## D-1 — `source_mode` must be excluded from the canonical body **[amendment proposed]**

§3 defines *canonical body* as "the envelope minus `captured_at` and
`connector`", which would leave `source_mode` inside it. But:

- S-4 / envelope table: `source_mode` "MUST NOT affect the canonical body";
- §8.2 fixture 2: `supabase-live.json` "must be canonical-body-identical"
  to `supabase-ddl.json` — impossible if the differing `source_mode` field
  is part of the body;
- C-3 requires byte-identical canonical bodies across modes.

These are satisfiable only if the canonical body excludes `source_mode` as
well. **Chosen reading:** canonical body := envelope minus `captured_at`,
`connector`, **and `source_mode`** (all three are per-run provenance).
Proposed amendment: §3's definition line should name all three exclusions.

## D-2 — Severity of structural changes not listed in the §7 sub-diff table

The §7 severity table does not classify: (a) a column `ordinal` change
(hash-included, so it *is* structural), (b) an `is_key_event` toggle
(hash-included per §4.5, but the API row in §7 names only
`data_type`/`scope`/`formula`), (c) appearance/disappearance of a
hash-included stats field (e.g. a `formula` added to a metric).

**Chosen reading:** any hash-affecting change the table does not name is
classified **breaking**. Rationale: the hash exists precisely to trigger
severity classification + contamination scan (S-2); the safe failure mode
for an unclassified structural change is to scan unnecessarily, never to
skip a scan. Applies to (a), (b), (c). Field appearance/disappearance is
reported as that field "changed" (absent → value / value → absent).

## D-3 — §7 footnote 3 (definition-change downgrade) not implementable in 1.1

A view/matview `definition` change is "downgraded to additive-with-note
when re-derived lineage shows the output column set and mappings are
unchanged." Lineage re-derivation is task 1.9 and a separate artifact
(out of scope per the snapshot spec §1). **Chosen reading:** in task 1.1
the diff engine always reports `definition` changes as **breaking**; the
sync engine (CP-3) applies the downgrade once lineage exists. The sub-diff
carries `downgradable: true` so the sync engine can find the candidates.

## D-4 — Exact shape of the hash projection

§5 lists *what* is included but not the projected document's shape.
**Chosen reading:** the projection is a reduced object document —
hash-included stats stay nested under a `stats` key (empty `{}` when the
kind has none), and `keys` is carried **verbatim-complete** (after §6
ordering), including empty arrays if the producer emitted them.
Consequence worth a connector-contract note: `"keys": {}` and
`"keys": {"primary": []}` hash differently, so a connector must emit key
arrays consistently across runs and modes (C-2/C-3 will catch drift here).
The fixtures in this repo omit empty key arrays (`"keys": {}`).

## D-5 — GA4 key events: `is_key_event` flag, not the `key` schema namespace

§4.2 allows `api_event` `schema` ∈ `standard | custom | key`, *and* §4.5
registers `stats.is_key_event` (hash-included). Both mechanisms at once
would be redundant, and moving an event to `schema: "key"` when it is
promoted would change its identity (S-1) — a key-event toggle would then
diff as a breaking removed+added pair instead of a structural change on one
object. **Chosen reading:** `schema` records the event's origin namespace
(`standard` | `custom`); promotion to key event is the hash-included
`stats.is_key_event` flag (surfaces as `changed_structural`, identity
stable). The `key` namespace is reserved for key events the connector can
enumerate only from the key-events list without a corresponding event
entry. Fixtures use the flag reading.

## D-6 — Diff-engine input contract

(a) The diff engine trusts each object's *stored* `schema_hash` (C-4 makes
producers accountable for it); an optional `verify_hashes` mode recomputes
and raises on mismatch, used in the conformance suite. (b) Snapshots of
different `system`s → error (§7: "two snapshots of the same `system`").
(c) Duplicate identity within one snapshot → error; the validator CLI also
reports this beyond plain JSON-Schema validation. (d) Unknown `kind`s are
skipped with a logged warning per S-5 — in the diff they are invisible,
which is the ruling's stated cost. (e) `source_properties` changes are not
a §7 classification (they are envelope facts, SS-3); the diff reports a
boolean `source_properties_changed` informationally, with no severity.

## D-7 — Fixture set vs spec §8.2

Task instructions require one fixture per system; spec §8.2 lists five for
the 1.1 exit. Shipped: `supabase-ddl.json`, `ga4.json`, `gsc.json`, and
`drift-pair/` (before/after staging every §7 classification incl. a rename
candidate). `supabase-live.json` is included but **hand-derived** from
`supabase-ddl.json` (same body, `source_mode: "live"`, later
`captured_at`): it exercises the canonical-body-identity *machinery*, but
is not evidence of connector mode-invariance — the real C-3 stays skipped
until task 1.2 produces it by live introspection. The suite names these
apart (`test_fixture_pair_canonical_body_identity` vs the skipped C-3).

## D-8 — Stack choice

CLAUDE.md's stack line was an unset placeholder. Chosen: **Python 3.12 +
jsonschema (Draft 2020-12) + pytest + hypothesis** (first suggested option;
jsonschema is needed for §8.1 verbatim, hypothesis for the required
property tests). CLAUDE.md placeholder filled accordingly.

## D-9 — Repo-path discrepancies **[resolved 2026-07-12]**

Originally: specs lived at `spec/` while every document said `specs/`, and
`phase1-supabase-ga4-gsc-plan.md` was absent, so the snapshot spec (which
states it formalizes that plan's §4) was treated as the authority. Both
resolved after task 1.1 landed: the directory was renamed to `specs/` and
the phase-1 plan added. Post-hoc reconciliation confirmed the reading —
see D-10.

## D-10 — Phase-1 plan §4 is the superseded draft of the snapshot schema

`specs/phase1-supabase-ga4-gsc-plan.md` §4 labels itself "draft schema",
and the snapshot spec's header says it *formalizes* that section, so where
they differ the snapshot spec governs. The differences, for the record —
draft-form snapshots are **intentionally rejected** by the §8.1 schema:

- draft columns lack `ordinal`; formal spec requires it (drives §6 order)
- draft FK is three-part `"ref": "public.users.id"` with no `ref_columns`;
  formal spec splits into two-part `ref` + `ref_columns` (the fk `ref`
  pattern `^[^.]+\.[^.]+$` rejects the draft form)
- draft kind list omits `materialized_view`; formal §4.2 registers it
- draft envelope lacks `connector` and `source_properties`; formal spec
  requires `connector`

Everything the plan pins concretely matches the implementation: GSC's
fixed dimension/metric set (§3.3) is byte-for-byte the `gsc.json` fixture;
GA4 custom definitions carry `data_type`/`scope`/`formula` in `stats`
(§3.2/§4); mode-identical snapshots (§1) is S-4/C-3.

One new observation, register-item candidate for task 1.2: plan §3.1 says
live introspection covers **indexes**, but snapshot v1 has no slot for
non-constraint indexes (`keys` holds primary/foreign/unique only; no §4.5
stats registration). Either they are deliberately dropped at the boundary
or a `stats` registration is needed when 1.2 is built — not a 1.1 concern,
recorded so 1.2 doesn't guess silently.

---

# DECISIONS — connector SDK harness (`connectors/sdk/`, shared by 1.2–1.4)

Ambiguities encountered implementing the connector-side halves of
`specs/job-protocol-spec.md`, `specs/capability-interfaces-spec.md`
(manifest + MetadataProvider), and snapshot delivery validation (J-6).

## D-11 — Harness owns the envelope; `introspect` returns facts only

Neither spec states who assembles the snapshot envelope. **Chosen
reading:** the connector's `introspect(config)` returns an
`IntrospectionResult` (`system_class`, `objects` without `schema_hash`,
optional `source_properties`); the harness stamps `snapshot_version`,
`system` (from config), `source_mode` (from `config.mode`),
`captured_at`, and `connector` (from the manifest), and computes every
`schema_hash` via the 1.1 library. Consequences: MP-1
(`source_mode == config.mode`) and C-4 (hashes recompute) hold by
construction for every connector on the harness; a connector-supplied
`schema_hash` is verified against the recomputation and a mismatch
fails emission — supplied hashes are never trusted.

## D-12 — Manifest stays spec-pure; code binding is SDK-local

`connector.yaml` carries exactly the §3 contract shape — no Python
entry-point field was added. Binding a manifest to code is the
SDK-local `Connector` object (manifest + handlers keyed by capability
name), addressed on the CLI as `MODULE:ATTR`. CC-1 splits accordingly:
`load_manifest` proves the file (structure, §4.2 capability→job-type
registry membership, protocol/snapshot version pins per CI-E, valid
Draft 2020-12 `config_schema`); `Connector` assembly proves the code
(declared capabilities ↔ registered handlers, both directions — an
undeclared handler is a release mistake since claim matching reads
only the manifest). `rate_limit.strategy` is an enum of what the SDK
ships (`none`, `token-bucket`); backoff/quota *primitives* land with
the GA4 task.

## D-13 — Emission gate: consumer leniencies are producer errors

J-6 dead-letters invalid deliveries server-side; the harness mirrors
the whole gate connector-side as `EmissionError` (code
`validation_error`, non-retryable) so a bad snapshot fails loudly at
the producer. Producer-side strictness deliberately exceeds the
consumer-side validator: unknown `kind` is an error (S-7 producers may
emit only registered kinds; S-5 skip-with-warning is for consumers),
unregistered `stats` fields are an error (C-8 at emission time, for
every connector), and any validator *warning* is treated as an error.
All-or-nothing (S-6) sits in the runner: introspection is one call,
any exception fails the whole job, and nothing is written on failure
(the CLI write is atomic temp+rename, so no partial file can exist).

## D-14 — Transport seam = `run_job → JobOutcome`; local CLI first

The pluggable-transport requirement is met by keeping the engine pure:
`run_job(connector, job) -> JobOutcome`, where the outcome's three
states mirror the three terminal wire calls (`succeeded`→`complete`,
`failed`→`fail`, `deferred`→`defer` with `retry_after_s`, J-5). A
transport is whatever builds a `Job` and disposes of the outcome; the
local CLI (`python -m connectors.sdk.local`, exit codes 0/1/2/3 =
ok/failed/usage/deferred) is the first, and the job-protocol runner
later maps the same outcome onto HTTP without touching connector code.
Claims, leases, and heartbeats are deliberately absent (task scope
fence); `Job.credentials` carries vault references but resolution is
unimplemented until 1.2 live mode needs it — `introspect(config)`
keeps the task-stated signature, and credential threading is a 1.2
decision, not silently pre-empted here.

## D-15 — Stack and demo-mode notes

PyYAML added as a dependency (manifests are `connector.yaml` per §3;
amends D-8's stack list). The static demo declares metadata mode
`ddl-file` rather than inventing a `static` mode: `source_mode` is a
closed §3 enum and the manifest schema enforces it — a new mode would
be a snapshot-spec amendment, not a connector choice.

---

# DECISIONS — task 1.2 (Postgres connector, `connectors/postgres/`)

Rulings confirmed on the column-by-column mapping review before
implementation; recorded here because future engine connectors inherit
several of them. Resolves the D-10 register-item candidate (indexes).

## D-16 — `stats.indexes` + matview `row_estimate` registered, hash-excluded **[amendment applied]**

Plan §3.1 requires indexes and the KB machine-doc template renders
"Keys & indexes", but snapshot v1 had no slot — the D-10 open item.
**Ruling:** register `indexes` (§4.5) for `table` and
`materialized_view`: lexicographically sorted engine-canonical strings
(`pg_get_indexdef` — the same zero-parsing principle §5 uses for view
definitions), omitting indexes that back declared constraints (those
facts ride `keys`). **Hash-excluded**, because an index cannot break a
dependent or contradict a documented meaning (the S-2 test), and the
hash-included alternative would make every routine `CREATE INDEX` a
breaking change driving contamination scans (D-2's default for
unlisted changes) — drift-pipeline noise that erodes trust, worse than
the edge it protects. The unique-index-without-constraint edge is
handled by convention, not polarity: semantic uniqueness belongs in a
UNIQUE constraint (`keys.unique`, hash-included); the caveat is written
into the §4.5 registration record. Folded into the same amendment:
`row_estimate` extended to `materialized_view`, same polarity —
symmetric and trivially additive. Process followed: spec diff first,
then `snapshot/registry.py`, one PR.

## D-17 — Partition children excluded from the snapshot

Objects with `relispartition = true` are not emitted; the partitioned
parent is a plain `table`. Beyond doc-flooding, the structural
argument: partition children are frequently *runtime* artifacts
(pg_cron/pg_partman creating monthly partitions), so they exist in a
live database but not in the logical DDL — including them would
structurally violate the DDL↔live invariance S-4/C-3 promise. The
parent is the logical estate; children are physical state. The parent's
`reltuples` is carried as-reported — never a synthesized sum across
children (stats are carried facts, not computed ones, S-8). The
partition key definition (`pg_partitioned_table`) joins the SS-7 drop
list as the strongest future §4.5 candidate (it tells query-writing
agents how to prune).

## D-18 — Facts with no v1 slot: dropped loudly, register items filed

Recorded as register items by value, not one undifferentiated note:
**SS-5** CHECK constraints (high-value: they encode exactly the
semantic facts human docs explain; sketched path: hash-included
`stats.checks` from `pg_get_constraintdef`). **SS-6** enum type labels
(high-value: literally SS-2's enum-decoding question, groundable as
facts without sampling; sketched path: an `enum_type` kind with
hash-included `stats.labels`). **SS-7** batched low-value gaps:
identity/generated column markers (both emit `default: null`),
schema-level and index-level comments, partition key definitions.
Nothing implemented in 1.2; entered in the snapshot spec's §10 register
first, then the master register, per process.

## D-19 — Canonical introspection readings (all engine connectors inherit these)

1. **`ordinal` = dense rank** among non-dropped columns, not raw
   `attnum`: a live table that ever had a dropped column keeps catalog
   gaps its logical DDL replay does not; S-4 promises invariance over
   the *logical* state, and dense rank is still the source-reported
   position (§4.3) — what `\d` and `pg_dump` show.
2. **Session `search_path` pinned empty** (pg_dump's own guard) in both
   modes: `pg_get_viewdef`/`pg_get_expr`/`pg_get_indexdef` qualify
   names relative to the session search_path, so a customer database
   with a customized default would otherwise deparse differently than
   the ephemeral container — silent C-3 breakage.
3. **`row_estimate` omitted while `reltuples = -1`** (never analyzed —
   every fresh ddl-file container). Consequence, expected by design:
   the eventual ddl→live switch adds estimates as a *metadata-only*
   diff — fresh information, hash-excluded, never a spurious
   structural change.

## D-20 — ddl-file `image` is required and must match the live major

No default image. `pg_get_viewdef` deparsing can differ across
Postgres major versions and `stats.definition` is hash-included, so
running ddl-file mode on a different major than the live target
manufactures spurious *breaking* diffs at the ddl→live switch —
precisely what S-4 promises never happens. The config schema refuses
`mode: ddl-file` without an explicit `image`; the README states the
rule. Customer 2 (Supabase 15.x): `postgres:15`.

## D-21 — Stack amendment and CI

`psycopg[binary]>=3.2` added (amends D-8/D-15). Ephemeral containers
are plain `docker` subprocess calls in connector code — ddl-file mode
needs them at *runtime*, so no test-oriented dependency
(testcontainers) was taken. Repo-wide GitHub Actions workflow added at
`.github/workflows/tests.yml` (full suite; `postgres`-marked tests run
on ubuntu-latest where Docker is available, skip where it is not) —
tasks 1.3/1.4 must reuse it, not create their own. Error messages
never echo the DSN (JC-8): a malformed-DSN parse error is replaced
wholesale, and libpq redacts passwords from connection errors.

---

# DECISIONS — task 1.3 (GA4 connector, `connectors/ga4/`)

The spec reading confirmed before implementation, recorded per the
D-16 pattern. Sources: plan §3.2/§4, snapshot spec §4–§6 (S-1/S-2/S-8),
capability spec MP-1/MP-2/CC-2, job spec J-5, the §4.5 registry as
implemented in `snapshot/registry.py`, and the 1.1 `fixtures/ga4.json`
(which pins several readings). Nothing here required amending the §4.5
registry; the register-item candidates in D-26 are proposals only —
no spec file was edited by this task.

## D-22 — Client dependency: plain REST via google-auth, not the official client libraries **[stack amendment]**

`google-auth>=2.29` (service-account OAuth2, `AuthorizedSession`) +
`requests>=2.31` added; the generated clients
(`google-analytics-data`, `google-analytics-admin`) deliberately not
taken. Rationale: (a) all five surfaces are plain `GET`s — list/get
endpoints with JSON bodies; (b) S-8/verbatim: the wire format carries
the exact strings the snapshot must emit (`TYPE_INTEGER`, `EVENT`);
the proto clients decode them into Python enums that would need
re-stringification — a translation layer exactly where the contract
wants none; (c) recorded-response testing is trivial against JSON
transports and painful against gRPC stubs; (d) calculated metrics live
in Admin **v1alpha** (not yet v1beta), and plain REST reaches any
version without a second generated client; (e) no protobuf/grpcio
dependency tree. google-auth itself is the one piece not worth
hand-rolling (SA JWT flow, token refresh, clock skew).

## D-23 — One object per definition: Data API metadata enumerates, Admin API decorates

The Data API metadata endpoint already returns every custom definition
(`customDefinition: true`, apiName like `customEvent:plan_tier`) that
the Admin API lists — two views of one definition, so **one snapshot
object**, never two. Emitting both would create duplicate-identity
collisions (same kind/schema/name) or, worse, near-duplicate objects
under different names for the same fact. Division of labor:

- **Data API metadata** is the *enumerating* surface — it defines the
  queryable estate (that is what an agent may put in a `runReport`),
  and owns existence, `name` (= `apiName`, verbatim, prefix included),
  `description`, and metric `data_type` (= `type`, verbatim
  `TYPE_*` string).
- **Admin API** decorates with the registered definition facts the
  metadata endpoint lacks: `scope` for custom metrics
  (`customMetrics`), `formula` for calculated metrics
  (`calculatedMetrics`, matched via the `calcMetric:{id}` apiName).
- The join is validated **both directions** for custom entries; a
  mismatch (a custom definition on one surface but not the other) is a
  torn read across non-atomic API calls — the snapshot must describe
  one moment (S-6 spirit), so the job fails `source_unavailable`
  (retryable) rather than emitting a half-described definition.

**Custom-dimension scope is not emitted.** Plan §3.2 says custom
definitions come "with scope", but §4.5 registers `scope` only for
`api_metric` — and no registration is needed for dimensions: GA4's own
naming rule encodes dimension scope bijectively in the apiName prefix
(`customEvent:` ↔ EVENT, `customUser:` ↔ USER, `customItem:` ↔ ITEM),
so the fact already rides identity (`name`), hash-covered, and a
`stats.scope` copy would be redundant. The 1.1 fixture agrees
(`customUser:crm_id` carries no scope). The Admin scope is still
*used* — it derives the prefix for the join in both directions — just
not emitted. If review wants it as an explicit stats field anyway,
that is a §4.5 amendment (registration on `api_dimension`), not a
connector choice.

## D-24 — `stats.data_type` for dimensions is the constant `"string"`

`DimensionMetadata` carries no type field because the Data API types
every dimension value as a string — that is the API's own type system,
a carried fact about the surface, not synthesized prose (S-8 governs
free text; this is a typed fact slot). §4.2 requires api_dimension
"typing via `stats.data_type`", the field is hash-included in the
registry, and the 1.1 fixture emits `"string"` for every dimension.
Metrics keep the verbatim wire enum (`TYPE_INTEGER`, `TYPE_CURRENCY`,
…) — the two vocabularies are per-kind connector conventions, exactly
like SS-1 treats engine-native SQL types.

## D-25 — Events surface = key events only; namespace from `KeyEvent.custom`; the `key` namespace stays unused

GA4 exposes **no metadata API that enumerates events**: the UI's event
list is report data, and enumerating `eventName` via `runReport` is a
data pull — out of scope by the task fence. So v1 `api_event` objects
come solely from the Admin `keyEvents` list, and consequences follow:

- `schema` is the event's **origin namespace** per D-5, decided by the
  key event's own `custom` flag: `false` → `standard`, `true` →
  `custom`. D-5's reserved `key` namespace stays unused — it exists
  for key events whose origin is *undeterminable*, and `custom` always
  determines it; using `key` would also change object identity if a
  fuller events surface ever lands (the removed+added pair D-5 exists
  to prevent).
- `stats.is_key_event` is `true` for every emitted event in v1 —
  vacuously, since only key events are visible. The flag is still
  emitted (hash-included, registered): it is the fact that makes the
  object meaningful, and it keeps identity/hash stable for the day a
  fuller events surface makes `false` emittable.
- **Demotion** (key event deleted in GA4) therefore surfaces as
  `removed` (breaking) — the object vanishes from the only surface
  that showed it — rather than as D-5's is_key_event flag flip.
  Substantively right (conversion reports depending on it do break),
  but it is a *reduced rendering* of D-5's intent, forced by the API,
  recorded here so the diff behavior doesn't surprise.
- Event **parameters** are not introspectable from any metadata
  surface → `columns: []` always (§4.2 allows parameters "when the
  API exposes them" — it doesn't). The 1.1 fixture's `purchase`
  columns and its non-key events (`page_view`, `session_start`) are
  hand-authored 1.1 artifacts exercising the schema; a real GA4 pull
  cannot produce them, which the fixture-vs-connector distinction in
  D-7 already anticipates.
- Key events carry no description field → `description: null` (S-8:
  verbatim or null, never Google's marketing docs copied in).

## D-26 — Archived/deprecated definitions; facts dropped at the boundary

**Archived custom dimensions/metrics** disappear from both surfaces
(the Admin list returns only active definitions, and the metadata
endpoint drops them); there is no "list archived" parameter. So an
archive lands in the next snapshot as `removed` → **breaking** — the
correct severity: any report or human doc referencing the definition
is broken by archiving, and resurrecting the fact is impossible
anyway (the connector cannot see it). No tombstones, no synthesized
"archived" marker (S-8; and it would need an unregistered stats slot).

**`deprecatedApiNames`** on standard dimensions/metrics (rename
migration windows): the current `apiName` is identity; the deprecated
aliases have no registered slot and are dropped at the boundary.
Register-item candidate (low value: the alias resolves at the API for
the migration window only, and the KB documents the current surface).

**Dropped with registry-candidate value, per the D-18 pattern —
proposed, not entered into any spec file by this task:**
`KeyEvent.countingMethod` (`ONCE_PER_EVENT` vs `ONCE_PER_SESSION`) is
the strongest candidate: it changes what the key-event count *means*,
so it passes the S-2 test ("could contradict human docs") and would
belong hash-**included** on `api_event` — flagged for a register item
rather than silently dropped. Lower-value drops, recorded in the
connector README: `uiName`, `category` (UI taxonomy), custom-metric
`measurementUnit` (already reflected in the Data API `type`),
`restrictedMetricType`, `blockedReasons`,
`disallowAdsPersonalization`, key-event `defaultValue`/`createTime`/
`deletable`, property `industryCategory`/`serviceLevel`/`createTime`.

## D-27 — Envelope: `system_class: "api"`, mode `api`; four documented source_properties keys

The manifest declares metadata mode `[api]` only; `source_mode: "api"`
is stamped by the harness (MP-1 by construction). Documented
`source_properties` keys (MP-2, additive only), all verbatim from the
Admin `properties/{id}` get:

| Key | Source field | Why it is a fact worth carrying |
|---|---|---|
| `property_id` | `name` (resource name, `properties/313459823`) | The stable identifier every cross-reference needs; config carries the numeric id, the emitted value is the API's own resource name |
| `display_name` | `displayName` | The human anchor for KB docs and the Connections UI |
| `time_zone` | `timeZone` | Defines the semantics of every date/hour dimension (GA4 reports are property-timezone-local); required to align GA4 dates with GSC dates and Postgres timestamps in blends/entity docs |
| `currency_code` | `currencyCode` | The unit of every `TYPE_CURRENCY` metric; a revenue figure documented in the wrong currency is precisely S-2's "contradict human docs" risk |

Matches the 1.1 fixture's four keys exactly.

**SS-3 evidence (recorded for the register closure at the 1.4 exit):**
nothing about GA4 properties required per-property document identity
or hashing. One configured system = one property; the property facts
are system-level envelope facts, consumed as provenance, not as
diffable objects — the D-6(e) informational `source_properties_changed`
bit sufficed even for a timezone/currency change. A customer with
several GA4 properties configures several systems (e.g. `ga4-web`,
`ga4-app`), each with its own snapshot and KB subtree, which S-1
handles with no `api_property` kind. Envelope-level
`source_properties` sufficed; no evidence for the SS-3 revisit
trigger.

## D-28 — Quota policy and error taxonomy at the GA4 boundary

The manifest declares `rate_limit: {strategy: token-bucket, …}` and
the SDK now ships the primitives D-12 deferred to this task
(`connectors/sdk/quota.py`): a monotonic-clock token bucket paced from
the manifest values, and a jittered exponential backoff schedule.
Behavior at the boundary, honoring J-5 and the task ruling ("any
other API failure → SourceUnavailable, no fallback"):

- **429 / `RESOURCE_EXHAUSTED`** → in-job backoff retries (manifest
  `max_retries`); still throttled → `QuotaExceeded` with
  `retry_after_s` from the `Retry-After` header when present, else the
  manifest's `default_retry_after_s` — the runner maps it to a J-5
  deferral, never a failure, never a dead-letter.
- **401 / 403 (non-quota)** → `AuthError` (non-retryable, re-auth
  flow) — the postgres precedent (D-21) for credential failures.
- **400 / 404** → `ConfigError` (malformed/unknown property —
  retrying a wrong id forever is noise, and GA returns 403, not 404,
  for unauthorized-but-existing).
- **5xx / network faults** → one backoff pass, then
  `SourceUnavailable` (retryable). Torn reads (D-23) are also
  `SourceUnavailable`.
- Nothing is ever written on failure (S-6; the CLI write stays
  atomic), and no error message carries credential material (JC-8) —
  messages name the endpoint path, HTTP status, and API `status`
  string only.

Config indirection mirrors the postgres `dsn_env` pattern: the config
file carries `credentials_file` (path to the SA JSON key) or
`credentials_env` (env var holding the key JSON) — references only,
never key material; the vault-reference path stays with the job
transport (D-14).

---

# DECISIONS — task 1.4 (GSC connector, `connectors/gsc/`)

The spec reading confirmed before implementation, per the D-16/D-22
pattern. Sources: plan §3.3/§4, snapshot spec §4.2/§4.5/§5
(S-1/S-2/S-8), capability spec MP-1/MP-2/CC-2, the 1.1
`fixtures/gsc.json` (which pins the identities, the data_type
vocabulary, and — via hash reproduction — the whole structural
projection), and the GA4 rulings D-22..D-28. **No §4.5 amendment was
needed:** the only stats field emitted is `data_type`, already
registered hash-included for `api_dimension`/`api_metric`; nothing to
flag against the registry.

## D-29 — Client dependency **[stack amendment]**: the D-22 footprint, zero new dependencies

GSC rides `google-auth` + `requests` exactly as GA4 does; the surface
is one plain read-only GET (`sites.get`), so a generated client
(`google-api-python-client` and its discovery layer) would be pure
overhead. The D-22 rationale carries over wholesale; pyproject gains
no new entry (the dependency comment now names both connectors).
Scope: `webmasters.readonly`. The HTTP layer (transport protocol +
status→taxonomy mapping) deliberately mirrors `connectors/ga4/client.py`
rather than importing it — connectors stay standalone, and promoting
the shared shape into the SDK is a rule-of-three refactor for when a
third API connector appears.

## D-30 — The fixed schema is a provenance-pinned constant table

- **S-1 identity:** `(system, api_dimension|api_metric, "standard",
  name)`. GSC has no custom definitions, so the `standard` logical
  group is total. Names are wire vocabulary verbatim — the
  `searchanalytics.query` dimension request values (`query`, `page`,
  `country`, `device`, `date`, `searchAppearance` — camelCase as sent
  on the wire) and metric response fields (`clicks`, `impressions`,
  `ctr`, `position`). Provenance pinned in the connector source and
  README (Search Analytics API reference).
- **Hash polarity:** the structural projection (identity + empty
  `columns`/`keys` + hash-included `stats.data_type` per §4.5) is a
  compile-time constant, so every `schema_hash` is hash-included *and
  effectively immutable* — byte-identical across runs and properties,
  moving only on a deliberate connector change that mirrors Google
  changing the documented surface, which the diff then correctly
  classifies as structural/breaking. The test suite pins the emitted
  hashes to `fixtures/gsc.json`'s exactly.
- **`data_type` vocabulary:** the declared connector convention
  `{string, integer, double}` (an SS-1-style per-connector type
  system, like GA4's D-24): dimensions are strings; `clicks`/
  `impressions` are counts (integer); `ctr`/`position` are a ratio and
  an average (double). The wire JSON types all four metrics as
  `number` — the semantic reading is the declared convention, and the
  1.1 fixture pins it (deviating would move every metric hash off the
  fixture's).
- **Descriptions are `null` (S-8).** The line drawn: a connector
  constant is emittable iff it is *wire vocabulary* (names, `dataState`
  values, response-field type domains); free text that never crosses
  any wire — Google's reference prose — is not a snapshot fact. This
  is D-25's "never Google's marketing docs copied in" applied to a
  connector whose entire schema is doc-defined. The description
  strings in `fixtures/gsc.json` are hand-authored 1.1 artifacts
  (D-7); a real pull cannot produce them, and since descriptions are
  hash-excluded (S-2) the fixture's hashes still reproduce. The
  human-facing definitions belong to the generator's GSC template
  (task 1.5), where prose is allowed and versioned.

## D-31 — Envelope: one system = one property; documented keys; SS-3 evidence

- **`sites.get`, not `sites.list`:** the snapshot documents one
  system. Emitting every site the service account can see would make
  snapshot content depend on grants unrelated to this system (envelope
  churn) and leak other properties into a customer-visible KB. A
  customer with several GSC properties configures several systems —
  the same shape as GA4's D-27.
- **Documented `source_properties` keys (MP-2, additive only):**
  `properties` — a list (exactly one entry in v1: the configured
  property; list-shaped per the 1.1 fixture so multi-property
  configuration stays additive) of `site_url` (verbatim `siteUrl`),
  `permission_level` (verbatim `permissionLevel`), and `verified`
  (derived: `permissionLevel != "siteUnverifiedUser"` — a typed fact
  mapping like D-25's namespace derivation, and always `true` in an
  emitted snapshot since unverified fails the job). `data_freshness` —
  `{data_states: ["all", "final"]}`, the Search Analytics `dataState`
  request vocabulary: the structured fact behind plan §3.3's "data
  freshness notes" (an agent must know fresh-but-provisional rows are
  requestable); the prose *semantics* of freshness are generator-
  template material, not snapshot facts (S-8). Additive over the 1.1
  fixture's three per-property keys.
- **SS-3 evidence (recorded for the register closure at this task's
  exit, jointly with D-27):** envelope-level property data sufficed.
  Nothing about GSC properties needed per-property document identity,
  hashing, or diff classification — a verification-state or
  permission-level change is covered by the D-6(e) informational
  `source_properties_changed` bit. With both phase-1 API connectors
  landed on the default and no evidence for the revisit trigger,
  SS-3 closes on: envelope `source_properties`, no `api_property`
  kind.

## D-32 — Error taxonomy at the GSC boundary; dropped facts

- **Unverified property** (200 with `permissionLevel:
  siteUnverifiedUser`) → `SourceUnavailable` (*retryable*:
  verification is source-side state a retry can find fixed) — the
  task ruling; job fails, nothing written (S-6).
- **401/403** → `AuthError` (non-retryable, re-auth/re-grant). The
  task bullet grouped auth failure under "SourceUnavailable"; kept
  `auth_error` deliberately and non-silently — D-21/D-28 route
  credential failures there so the re-auth flow can trigger, and both
  readings agree on the observable contract (job fails, no file
  written).
- **400/404** → `ConfigError` (wrong/malformed `site_url`);
  **429 or 403+`RESOURCE_EXHAUSTED`** → jittered backoff
  (`max_retries`), then `QuotaExceeded` with `retry_after_s` from
  `Retry-After` (else the manifest default) — a J-5 deferral, never a
  failure; **5xx/network** → same backoff schedule, then
  `SourceUnavailable`; **malformed/shape-broken 200** →
  `SourceUnavailable`. Messages carry endpoint path, HTTP status, and
  API `status` string only (JC-8). The manifest declares `strategy:
  none` — one GET per job needs no client-side pacing — while the
  backoff fields still drive the retry schedule.
- **Dropped at the boundary** (D-18 pattern, README-recorded; no
  register items proposed — none passes the S-2 test yet): the
  `sites.list` estate beyond the configured property (per D-31), and
  the hourly surface (`dataState: HOURLY_ALL` + `HOUR` dimension, a
  2025 API addition) — outside plan §3.3's fixed set; adopting it
  later is a purely additive constant-table change.

---

# DECISIONS — task 1.5 (generator + templates, `generator/`)

The spec reading confirmed before implementation, per the D-16/D-22/D-30
pattern. Sources: KB repository spec (K-1..K-8, §3/§4/§7/§10), snapshot
spec §4–§6 (S-2/S-3/S-5/S-8), phase-1 plan §5 (superseded draft of KB §3,
same relationship D-10 established for §4), the four real snapshots, and
DECISIONS D-1..D-32. Two spec amendments were applied under explicit
rulings (the D-16 additive-registration precedent): the §4.1 `generated_at`
clarification and the §4.6 `machine-index` registration — spec diff first,
same PR. The KB-F register item entered KB §12 and the master register.

## D-33 — `generated_at` = capture date of the snapshot whose render last changed the file **[amendment applied]**

KB-8 demands byte-level no-op regeneration, but §4.1's `generated_at` had
no defined clock. **Ruling:** the value is the date part of `captured_at`
of the snapshot whose render last *changed the file's content*; never the
generator's wall clock. Mechanically: if a candidate render equals the
existing file modulo the `generated_at` line, the existing bytes stand and
nothing is written; otherwise the file is written with the current
snapshot's capture date. The decisive argument: this makes a full render
byte-identical to what CP-3's KB-C changed-objects-only path will produce,
so the two regeneration routes can never disagree — worth more than any
semantic quibble. Semantics are honest provenance: "the source state this
doc last changed to reflect" (job wall clocks belong to job logs).
**Corollary (single timestamp locus):** machine-doc bodies never embed a
timestamp; the §7 "Row estimate & freshness" section points at the
front-matter field rather than inlining a date. **Recorded interaction,
pinned in the mode-pair test:** a ddl-file → live switch changes the
`source_mode` front-matter line on every machine file of that system —
a content change, so every file restamps. That is expected provenance
("this doc now reflects live introspection"), arriving alongside
D-19.3's metadata-only row-estimate appearance, not churn. Rejected
alternative (restamp `date(captured_at)` unconditionally): re-rendering
from a newer-but-body-identical snapshot would churn every file, full and
incremental paths would diverge, and the S-2 flow-through tests would fail
across `drift-pair/`'s deliberately differing capture dates.

Input model this fixes: render is a deterministic function of
(snapshot set, existing output tree), where the tree contributes only
(a) prior `generated_at` values and (b) existence + front-matter of
human-owned siblings (hot/stub, status roll-ups, `_notes.md` links).
On an empty output dir it is a pure function of the snapshots — what the
golden-tree tests pin.

## D-34 — `machine-index` class registered; root-bootstrap artifacts KB-1-exempt **[amendment applied]**

Per-system and per-schema `index.md` are machine-owned (K-7) but §4
defined no class for them while KB-1 validates every file and K-5 makes
front-matter the trust payload. Registered `doc_class: machine-index`
(`system`, `scope: system|schema`, `schema` iff schema-scoped, plus the
standard provenance fields) as KB spec §4.6. The K-7 bootstrap artifacts
(`kb/index.md`, `kb/conventions.md`, `_notes.md` siblings) are human-owned
docs with no object identity: they carry no front-matter and KB-1 exempts
them by path; the generator writes the two root files only when absent
(existence is the bootstrap latch) and never writes `_notes.md`. The
deliberately-undesigned remainder — whether repo-level human docs need
trust statuses for MCP trust blocks — is register item KB-F, deferred to
the CP-4/M1 session where the consumer exists.

## D-35 — D-30's GSC-template-prose sentence superseded

D-30 (task 1.4) contained: "The human-facing definitions belong to the
generator's GSC template (task 1.5), where prose is allowed and
versioned." That sentence is **superseded** — it was a session-local
decision that overstepped S-8 ("the generator adds structure, never prose
about the data"): a template carrying Google-reference definitions would
put synthesized prose about the data into machine-owned docs. The
generator renders `description: null` as `—`, full stop; the fixture's
hand-authored descriptions (D-7/D-30 artifacts) still render because the
rule is verbatim-or-absent. Consequence recorded for task 1.7: the GSC
group human docs (`systems/gsc/dimensions.md`, `metrics.md`) become the
natural first enrich batch — Google's documented definitions carried with
`sources:` citations — doubling as clean SS-2 evidence (doc-only grounding
for a fixed-schema source).

## D-36 — Canonical readings (confirmed, recorded; no spec change)

1. **Object-level description renders in the Identity section** — §7's
   machine template names no other slot, and the §7-diff metadata-only
   class requires description edits to land somewhere in the machine doc.
2. **Referenced-by is a reverse-FK snapshot fact, not lineage**: computed
   within the snapshot from `keys.foreign[].ref`, sorted canonically. The
   task-1.9 boundary stays exactly as drawn — the generator never reads,
   writes, or links `lineage/graph.json`; §7 requires no lineage section.
3. **Pruning semantics**: the machine-owned file set is exactly what the
   input snapshots define — a machine file whose object vanished is
   deleted (emptied schema dirs removed); human-owned files are never
   written or deleted; systems absent from the input are left untouched
   (system removal is administrative, §7/S-6). Asserted by the
   pruning-safety test, not left as convention.
4. **Layout mapping**: API kinds group as `api_dimension` →
   `dimensions.schema.md`, `api_metric` → `metrics.schema.md`,
   `api_event` → `events.schema.md`; custom definitions fold into their
   kind group (namespace = the `schema` field; phase-1 plan §5's
   `custom-definitions.md` is the superseded draft). A group file exists
   iff the kind has ≥ 1 object — no empty group docs (K-8's spirit).
5. **Verbatim-or-absent rendering**: absent facts render as `—` in tables
   and as nothing elsewhere — never placeholder prose. Table cells escape
   `\` → `\\`, `|` → `\|`, newline → `<br>` (deterministic rendering
   convention, not content change).
6. **Ordering**: stored file order is never trusted — objects re-sorted
   (kind, schema, name) via `snapshot/canonical.py`, columns by ordinal,
   keys per §6 rule 5, `stats.indexes` verbatim (registered pre-sorted),
   `source_properties` keys lexicographic.
7. **Anchors**: group docs carry generator-emitted deterministic anchor
   ids `mangle(schema)--mangle(name)` (the §8 hook); `mangle` is the §3
   path rule (lowercase, `[^a-z0-9_-]` → `-`).
8. **`system_class` ↔ template family**: `sql` → per-object docs +
   per-schema indexes; `api` → grouped docs at system level (K-4).
   Unknown kinds are skipped with a logged warning (S-5), invisible in
   docs and indexes.

## D-37 — Stack amendment: Jinja2

`jinja2>=3.1` added (amends the D-8/D-15/D-21/D-22/D-29 stack chain),
configured deterministically: `StrictUndefined` (a missing fact fails the
render loudly instead of silently emitting a blank), autoescape off
(markdown output), `keep_trailing_newline`. Templates ship as package
data `generator/templates/*.j2`. Front-matter is deliberately *not*
templated — a strict code-side emitter with fixed per-class key order and
fixed quoting rules, because `yaml.dump` style defaults are not a byte
contract. Rejected alternative: stdlib f-string builders (zero deps) —
viable, but templates are a first-class deliverable that 1.6/1.7 and the
KB-C partial-render evolution will iterate on. The validation library
uses `jsonschema` (already in the stack); no other dependency added.

---

# DECISIONS — task 1.9 (SQL lineage parser + graph, `lineage/`)

The spec reading confirmed before implementation, per the D-16/D-22/D-30/
D-33 pattern. Sources: lineage-and-report-artifact-formats spec §3 +
F-1..F-8/FG-1..FG-5, capability spec LP-1..LP-3 (§10) and CC-10, snapshot
spec §4.2/§4.5/§5 (view `stats.definition`, MC-5 authority default), MCP
spec §6.5, the connector rulings D-19/D-20, and the generator boundary
D-36.2 (confirmed from this side: the generator never touches
`lineage/graph.json`; this task owns it exclusively and writes nothing
else into the KB tree). One consolidated formats-spec clarifying
amendment was applied under explicit ruling (D-16 precedent, spec diff
first): F-1 edge-id byte encoding made normative (§3.3), the §3.1
`generated_at` clock rule (D-33 ported), the §3.2 example path corrected
to `.schema.md`, the §3.6 producer failure-semantics note, and register
item FM-6 (entered in formats §7 first, then the master register).

## D-38 — Stack amendment: sqlglot **[amendment applied, two recorded conditions]**

`sqlglot` (pure Python, MIT) added for parse + scope resolution of
Postgres view definitions; floor `sqlglot>=25` in pyproject, **exact pin
in `constraints.txt` and CI** (condition a). Division of labor,
deliberately narrow: the library supplies parsing, alias/CTE/subquery
scope resolution, and star expansion against an externally supplied
schema mapping; **edge extraction, snapshot-inventory resolution, and all
failure semantics are platform code** — the output must be the §3.3 edge
model and the failure behavior the §3.6 ruled one, neither delegated.
Dialect hard-scoped: `dialect="postgres"`, no dialect flag on any
surface; a second dialect is a future task's amendment. Rejected:
`pglast` (libpg_query C extension, version-locked to a PG grammar —
exact-grammar fidelity buys nothing for engine-deparsed SELECTs at the
cost of a native dependency), `sqlparse` (tokenizer, not a parser).
**Condition (b), recorded trust boundary:** sqlglot's Postgres fidelity
is trusted only for the input class D-19.2 guarantees — engine-deparsed
canonical SELECTs from `pg_get_viewdef` under an empty search_path —
never for arbitrary user SQL. **Named revisit path:** on the first parse
failure against a example estate, the decision is libpg_query bindings
(pglast); pre-argued here so it is executed, not re-litigated.

## D-39 — Graph envelope and serialization

- `inputs` for this producer: one `{"kind": "sql-parse", "snapshot_ref":
  {system: hash}}` entry, all systems in the one map, keys sorted;
  the hash is `"sha256:" + hex(sha256(canonical_body_bytes(snapshot)))` —
  the same canonical-body hash the capability spec's `validated_against`
  pins, `captured_at`-independent by S-3.
- `generated_at` = latest `captured_at` among the input snapshots whose
  build last changed the file's content (the D-33 mechanism, now spec
  text in formats §3.1): if a candidate build equals the existing file
  modulo the `generated_at` member, the existing bytes stand and nothing
  is written. Full ISO timestamp per the §3.1 example (KB docs use the
  date part; the graph keeps the envelope's precision).
- Serialization: nodes and edges sorted by `id` (§3.1 verbatim), object
  keys sorted lexicographically at every level (§6 discipline), JSON
  `indent=2` + trailing newline — pretty, because graph diffs must be
  PR-reviewable — written atomically (temp + rename, D-13 precedent).
  Single file; the §3.5 25k-edge shard trigger is recorded, not built.
- Empty-valued optional members are omitted (`columns` when not
  derivable, `annotations` when no lineage-note back-links, `doc` on
  unresolved nodes) — closed schema, additive evolution (F-8).

## D-40 — Edge identity byte encoding **[amendment applied]**

F-1's `‖` concatenation was byte-underspecified (`"a"+"bc"` vs
`"ab"+"c"`). Normative now (formats §3.3): SHA-256 over the UTF-8 of
`source + "\n" + target + "\n" + operation`, rendered
`"sha256:" + lowercase hex`. Newline is safe as delimiter (cannot occur
in an FQN or operation name). Frozen within `graph_version: "1"`:
annotation docs reference edge ids forever — F-1's own rationale.

## D-41 — Failure semantics: dangling markers vs hard parse failure **[ruling]**

Two classes, deliberately asymmetric (now formats §3.6):

- **Unresolved reference** (parse succeeded; referenced FQN absent from
  the snapshot inventory) — the spec-ruled marker path (§3.2 `resolved:
  false`, LP-3 "flag, don't reject", FG-3): dangling node emitted, edge
  kept, never a hard failure, never a silent drop. Real trigger: a view
  referencing a schema excluded from introspection scope. The dangling
  node carries `node_kind: "external"` — recorded nuance: this means
  **"unclassifiable from current snapshots"**, distinct from any future
  legitimately-declared external reference (KB-B's escape hatch);
  `resolved` is the load-bearing flag, `node_kind` is honest ignorance,
  never a guess. Column mappings on a dangling edge are emitted only
  where the definition text itself attests them (explicit `d.col`
  references); a star over a dangling relation has no inventory to bind
  → `columns` omitted (never fabricated).
- **Parse failure** (a `stats.definition` the parser cannot parse) —
  **hard failure of the whole graph build; no graph written** (atomic
  write). Loud and attributable: the error names the object FQN and the
  `view-def sha256:` of the failing definition, so the fix path is
  immediate. Argument: a warning-plus-partial-graph silently omits an
  edge set, which makes the KB §6 contamination scan *skip* downstream
  docs — precisely the polarity D-2 rules out; a dangling FQN is a
  legitimate estate condition with a format slot, a parse failure is our
  defect, and encoding our defect as graph content would launder it into
  downstream false negatives. **What CP-3 inherits, in plain terms: the
  contamination scan runs against a graph that is complete or absent,
  never quietly partial; an absent graph fails the drift run visibly.**

## D-42 — Parser canonical readings (recorded; no spec change)

1. **One edge per (source relation → view)**; `operation` is the
   strongest transformation the defining query applies, by documented
   precedence `aggregate > dedupe > join > derive > cast > rename >
   filter` (`ingest`/`business-rule` never emitted by sql-parse). The
   §3.3 example is the warrant: a GROUP-BY view rendered as one edge,
   `operation: "aggregate"`, mixed mappings attached. Per-column
   derivation kind is not expressible in v1 — register item FM-6.
   **Floor:** a pure passthrough view (bare columns, no predicate, no
   alias) exhibits nothing on the list and emits `rename` — the view's
   one transformation is re-exposing the relation's columns under a new
   relation name; the least-wrong taxonomy member, chosen over inventing
   an unregistered operation (LP-1 rejects unknowns at delivery).
2. **Column mappings**: `from` lists only the edge's source-node columns
   feeding `to`; a target column drawing on several relations appears on
   each contributing edge under the same `to`. Passthrough is a plain
   `{from: ["a"], to: "a"}` entry. **Column-free derivations emit
   `from: []`** (`count(*)` → `order_count`): the mapping is derivable —
   from zero columns — and omitting it would hide the target column from
   FM-1's future column walk. WHERE/JOIN/GROUP-BY-only columns produce
   no mapping (`to` is mandatory; the relation-level edge carries the
   dependency) — FM-6's second gap.
3. **Star expansion binds to the snapshot's recorded `columns` of the
   referenced object, in ordinal order, at the referencing view's parse
   time** — snapshot is authority (MC-5), S-6 guarantees consistency.
   Engine-canonical definitions cannot contain a select-star
   (`pg_get_viewdef` deparses the rewritten query; Postgres expands `*`
   at CREATE VIEW) — the defensive path exists for hand-authored
   fixture SQL.
4. **No transitive collapse**: edges are direct-upstream only;
   transitivity is the walk's job (§3.4). **Because binding reads the
   snapshot inventory (point 3), definitions parse independently — no
   topological ordering, no recursion to get wrong.** Worth stating:
   this is a direct consequence of MC-5, and it is why views-on-views
   need no resolution order.
5. **CTEs and subqueries are scopes, never nodes**; provenance traces
   through them to base relations; a CTE shadowing a real table name
   follows Postgres scoping (the CTE wins inside the query). Edges
   collapse the internal plumbing.
6. **Aliases resolve away everywhere**; a self-join's two aliases of one
   relation collapse to one node and one edge (F-1 identity), `from`
   lists unioned per `to`, de-aliased, deduplicated, sorted.
7. **Unqualified relation names** (hand-authored 1.1 fixtures only; the
   connector's primary path is fully-qualified per D-19.2): resolve iff
   exactly one relation-kind object with that name exists across the
   snapshot's schemas; **ambiguity is never guessed** — it takes the
   D-41 unresolved path. Unqualified column references bind by inventory
   membership; if no in-scope relation carries the column, the mapping
   is omitted with a logged warning (never fabricated).
8. **No isolated nodes**: the node set is exactly the edge endpoints.
   An object with no lineage is absent from the graph; `get_lineage`
   answers for it per D-43.
9. **`doc` paths** are computed from the snapshot + the KB naming rules
   (single-sourced from `generator.naming`; `systems/<system>/
   <mangle(schema)>/<mangle(name)>.schema.md`) — never by reading the KB
   tree. The generator guarantees a machine doc for every SQL object in
   the snapshot, so "when one exists" (§3.2) is decidable snapshot-side.
   The boundary holds in both directions: the generator never touches
   `lineage/graph.json`; lineage never reads or writes KB docs.
10. **Merge entry point shaped for future producers** (provider edge
    sets per LP-1..3, human `declared_edges` blocks) **but only
    sql-parse is wired** — `declared_edges` ingestion is merge-time work
    for a KB tree that does not exist yet (1.6/1.7); the scope fence
    holds.

## D-43 — `get_lineage` walk semantics **[ruling addition folded in]**

Library function (`lineage.get_lineage`), not the MCP tool — CP-4 wraps
it. Edges point in data-flow direction; downstream follows, upstream
reverses, `both` = union of the two walks. **Node-level traversal (FM-1
default) with column-level payload served verbatim**: visitation ignores
`columns`, but every returned edge carries `operation`, full `columns`,
`evidence`/`trust`, `annotations` untouched — the walk API never papers
over the column data (FM-1's own default says mappings are served as
context; D-3's deferred downgrade check needs them). Depth = edge-hops
from the start node, default 3 (MCP §6.5 signature); `depth=None` =
unbounded, supported library-side because the KB §6 contamination scan
is unbounded by design (§3.4) and reuses this walk; **the 10-cap is the
interactive tool's policy and lives in CP-4's wrapper.** Cycles: each
node visited once per walk; a cycle is reported in the result, never
re-traversed (FG-4). Dangling nodes ride the result flagged
(`resolved: false`, FG-3). **Ruled addition: a walk from an FQN absent
from the graph returns an empty result with the root echoed — not an
error.** "No lineage recorded" is a legitimate answer (a base table no
view reads), and CP-4's tool needs the distinction cheap. Doc *trust* is
KB front-matter, which this code never reads — the library returns `doc`
paths; CP-4 joins trust.

## D-44 — Exit evidence: connector-produced customer snapshot **[ruling]**

The task exit criterion's referent is the customer's DDL views, so the
primary e2e evidence runs against a **connector-produced** snapshot —
qualified names, the D-19.2 primary path — not the hand-authored 1.1
fixtures (those stay in the suite as the fallback-path tests, D-42.7).
No live-validated customer snapshot was checked in by 1.2 and the
customer DDL files are not in the repo, so the DDL was **reconstructed
from `fixtures/supabase-ddl.json`'s structural facts** (the §8.2 record
of the customer estate: columns/types/defaults/keys/descriptions/view
definitions, carried verbatim) into `fixtures/supabase-customer.sql`,
and the snapshot regenerated from it via the postgres connector in
ddl-file mode — no credentials needed — with `image: postgres:15` per
D-20 (customer 2 is Supabase 15.x). Checked in as
`fixtures/supabase-customer.json`; envelope provenance (connector
name/version, `source_mode: ddl-file`) rides the file, and the exact
regeneration command is recorded in the fixture-generating test's
docstring. Exit demo: every customer DDL view resolves to its upstream
tables with column mappings on that snapshot, and `get_lineage` walks
both directions.

---

# DECISIONS — task 1.6 (customer KB bootstrap, `AlperCamli/DataAnalyticsTool`)

## D-45 — KB-5 lands in the validation library; scope of the offline CI surface

The 1.5 docstring assigned link/anchor resolution (KB-5) to task 1.6;
it now lives in `generator/validate.py` so the KB CI entry point
(`python -m generator.validate <kb-dir>`) is the complete offline
surface: KB-1 front-matter schemas, §3 layout conformance, the
`faults/` prohibition, and KB-5. Scope rulings: external URLs and
`mailto:` are out of KB-5 scope (the KB attests its own integrity, not
the web's); links inside fenced code blocks are ignored (view-definition
SQL is not hypertext); dot-directories (`.contextlayer/`, `.github/`,
editor state) are not KB docs and are skipped; anchors use the
github-slugger algorithm because the generator's deterministic anchor
IDs are defined by what the git host renders. KB-2 (`depends_on`
resolution) needs the latest snapshot server-side and stays with the
sync engine (CP-3).

## D-46 — KB CI gets the validation library as a vendored wheel **[user ruling, three conditions]**

The KB repo may carry no platform code, KB CI may hold no secrets, and
the platform repo has no reachable remote — so the workflow cannot
check the library out. **Ruling (approved at task 1.6): the KB repo
vendors the library as a built wheel under `.github/vendor/`.**
Conditions, verbatim intent:

1. **Provenance:** the wheel is versioned and sits next to a manifest
   (`.github/vendor/VENDOR-MANIFEST.yaml`) recording the platform-repo
   commit SHA and library version it was built from. Never an
   anonymous binary. (`pyproject.toml` bumped to 0.2.0 so the wheel
   name distinguishes this build class from the pre-generator 0.1.0.)
2. **Update path:** validation-library changes → rebuild wheel → PR to
   the KB repo, manual for now; CP-3's sync PRs can carry wheel bumps
   later. The named failure mode: a stale wheel silently validating
   against old rules — the manifest SHA is what makes staleness
   visible in review.
3. **Fence interpretation:** `.github/vendor/` is CI tooling, not KB
   content. The "no platform code in the KB repo" fence means no
   platform *logic in the KB tree*; this is the one sanctioned
   exception.

The workflow installs the wheel `--no-deps` plus only the three
runtime deps validation imports (jsonschema[format-nongpl], PyYAML,
jinja2), pinned — connector deps (psycopg, google-auth, requests,
sqlglot) never enter KB CI.

## D-47 — KB repo rulings at bootstrap **[user rulings recorded]**

- **Visibility:** `AlperCamli/DataAnalyticsTool` stays **public** for
  this pilot — GitHub Free gates branch protection on private repos,
  and enforced protection (PRs only, KB CI required, code-owner
  review) was ruled to win over privacy for now. May flip private
  later; protection then degrades to convention until a plan or host
  change restores enforcement.
- **Identities:** all five playbook roles (R1–R5) map to
  `AlperCamli` for the pilot; real handles swap in when the KB moves
  to a customer git server.
- **OD-3 closure applied per system** in `.contextlayer/
  sync-policy.yaml`: ga4 3d, gsc 3d, supabase 30d — the register's
  "per customer at onboarding" path, values ruled at this onboarding.
  The master register row itself is spec-fenced and untouched.
- Sync triggers in the policy file are **placeholders armed at CP-3**;
  commits are session-authored via PR until the platform's machine
  identity exists (CP-3). The initial generation PR is merged by the
  R2 steward by hand — deliberately their first review-flow rehearsal.

## D-48 — Live engine version supersedes the D-20 assumption **[flag]**

The task-1.6 brief and D-20 both said "customer 2 is Supabase 15.x";
the live snapshot's envelope says `server_version: "17.6"`. The KB may
not contradict its own snapshot, so `conventions.md` records
PostgreSQL 17 (with the envelope value cited). Left open for the next
fixtures/verify pass: `fixtures/supabase-customer.json` was produced
via the D-20 `postgres:15` ddl-file image — C-3 mode invariance
should be re-checked against a 17-class image before that fixture is
used as live-parity evidence.

---

# DECISIONS — purpose merge (owner ruling issued as "D-38", recorded as D-49)

## D-49 — Purpose enrichment merged into machine renders **[user ruling, applied]**

**Numbering note:** the 2026-07-13 session brief issued this as "RULING
D-38", but D-38 is already the sqlglot stack amendment (task 1.9). It is
recorded here as **D-49**; spec citations say D-49. The subsection
numbers below (D-49.1..7) correspond one-to-one to the brief's D-38.1..7.

**The ruling (condensed; authorizes the KB-spec amendments it names,
fence otherwise unchanged):**

1. Purposes are enrichment → human-owned, additive front-matter:
   `human-object` gains optional `purpose` + `column_purposes`
   (column → one-liner); `human-group` gains `purpose` +
   `object_purposes` (FQN → one-liner); new `doc_class: human-notes`
   for `_notes.md` siblings with optional `purpose`. Unknown keys still
   rejected.
2. Generator inputs amended (KB §3/§7): render = deterministic function
   of (latest accepted snapshot, enrichment front-matter at repo HEAD).
   Columns tables gain a Purpose column; API group docs a Purpose row
   per roster object; per-schema index rows the object's `purpose`;
   per-system index rows the schema/kind-group purposes from
   `_notes.md` / human group docs. `—` when absent.
3. Consistency invariant: machine files at HEAD always equal the render
   of (latest snapshot, HEAD enrichment). KB-8 runs on every PR
   touching enrichment; enrichment PRs include their implied
   re-renders. KB-3 amended: machine diffs CI reproduces exactly by
   regeneration pass without warning.
4. `generated_at` remains Rule B; purpose-driven re-renders never
   change it.
5. New warn-level CI check: dangling `column_purposes`/`object_purposes`
   keys, naming doc and key.
6. JSON structure documentation stays human-doc body content — not
   merged in v1.
7. Register: "purpose-merge scope growth" (entity/metric one-liners
   into indexes) filed and parked → KB spec §12 item KB-G.

**Implementation rulings made under it:**

- **Committed accepted snapshots (`.contextlayer/snapshots/<system>.json`,
  KB §3):** the D-49.3 invariant is a statement about repo HEAD, so
  "latest accepted snapshot" must be part of HEAD for the invariant to
  be well-defined per commit — and KB CI is the offline D-45/D-46
  surface with no server to ask. Sync updates the snapshot in the same
  PR as the renders it implies. No new exposure for the pilot: the
  rendered machine docs already publish every fact the snapshot holds.
  `python -m generator.validate` auto-discovers these (no workflow
  change needed beyond the wheel bump); explicit `--snapshot` still
  overrides.
- **Slot rule (KB §7): purpose renders last and always renders** (`—`
  marks absence; slots never collapse). Consequence: renders are
  line-stable across enrichment changes, which is what makes the date
  rule below exact.
- **Date-rule mechanism (KB §4.1):** on a rewrite, the renderer also
  renders the body with every purpose slot absent and with every slot
  set to a sentinel; the per-line diff of that pair locates each slot
  byte-exactly (no markdown parsing — the K-1 fence stands). If the old
  body differs from the candidate only inside slots, the old
  `generated_at` is kept; any fact-line difference restamps. Mixed
  edits (facts + purposes in one render) restamp — honest, since facts
  did change. One slot per template line by construction; a second slot
  on a line would make the prefix/suffix test unsound — template
  changes must preserve this.
- **Scope of date-neutrality is purpose slots only:** status/hot-stub
  cell changes share the slot's table row but sit in the fact prefix,
  so they restamp exactly as before D-49 — pre-existing Rule-B
  behavior, deliberately untouched.
- **KB-8 runs whenever snapshots are supplied** (a superset of "every
  PR touching enrichment") — so a PR that adds a human doc or flips a
  status must carry the implied index re-renders too. That is the
  invariant read literally; the enrich skill (task 1.7) automates it.
- **KB-10** is the dangling-key check's number; `Finding` gained a
  `level` field and the CLI exits 0 when only warns remain.
- **KB-3's amendment is spec-level for now:** KB CI has no authorship
  check yet; the KB-8 render check already subsumes the
  reproducibility half (a diff CI regenerates exactly is, by
  definition, consistent with snapshot + enrichment).
- **Vendored wheel bumped to 0.3.0** (D-46 condition 1: version names
  the build class) and delivered to the KB repo together with the
  committed snapshots and the one-time estate re-render, in one PR —
  separable pieces would leave intermediate commits red under the new
  KB-8.
- **Follow-up (out of fence here):** the onboarding playbook/skill
  should gain the "commit the accepted snapshot to
  `.contextlayer/snapshots/`" step; next onboarding session.
