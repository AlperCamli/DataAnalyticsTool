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

---

# DECISIONS — task 1.8 (customer entity drafts, `AlperCamli/DataAnalyticsTool`)

The CP-1 exit deliverable: the cross-system routing hubs (`entities/`) an
agent uses to decide which system answers which question and how sources
join. Landed as KB PR #13 (`enrich/entities` → `main`, single commit
`4e47c55`, merge `ccda04f`; +251, 3 files, 0 deletions).

## D-50 — Task 1.8 landed / CP-1 closed

Three entity docs merged: `entities/user.md`, `entities/page.md`,
`entities/conversion.md`. **All three landed `status: draft`,
`last_verified: null` — no mapping was customer-certified to verified.**
The grounded mappings are cited but uncertified: user's
`supabase.public.users` (system-of-record, ✅ structural); page's
`gsc.standard.page` ↔ `ga4.standard.pagePath` path blend (✅ config-derived
— single-domain property `sc-domain:example-estate.com` makes host constant);
conversion's `ga4.standard.purchase`/`keyEvents:purchase` +
`supabase.public.subscriptions` (✅ config + structural). Certification
(draft → verified) is the customer step; it did not run — it is blocked on
five open customer questions (D-52), so every doc stays draft **by design,
not omission**. Review/merge trail: PR #13 opened and merged by `AlperCamli`
(all playbook roles collapse to one in the pilot, D-47) ~3.5 min apart
(11:34→11:37Z), **no reviews, no review comments, never draft-flipped** —
the steward's by-hand merge (D-47's review-flow rehearsal), with no
independent review recorded. Local KB CI on the vendored 0.3.0 wheel: 0
errors, 0 warnings. CP-1 closes here.

## D-51 — OB-2 evidence (skill-drafted / customer-certified path)

OB-2's stated default — "skill-drafted, R5-paired review, always
customer-certified" — was exercised in its **draft half only**; PR #13 is
one register-grade data point toward the "after 2–3 onboardings" revisit.
What the trail evidences:

- **Draft quality is high under strictest grounding.** Every mapping is
  cited to a machine-doc FQN, an app-code config fact, or a customer doc, or
  it is **dropped and recorded** under Ungrounded gaps — nothing
  plausible-but-unattested was asserted (the bodies say so in-line: "Do not
  invent one"). The join keys that do not exist were dropped, not guessed:
  user's Supabase↔GA4 identity (app sends no GA4 `user_id`; User-ID off; no
  `userId`/`clientId` dimension) and conversion's `purchase`↔`subscriptions`
  row join (no shared key). CI clean, 0/0.
- **Gaps flagged honestly, not papered over.** Four ungrounded gaps carry
  explicit unblock notes; five customer questions are posed. This is the
  strong signal: the drafting discipline surfaces its own limits.
- **Mappings needing correction at review: none surfaced — but the trail
  cannot evidence review efficacy.** No reviewer comments, no inline
  corrections, and R5-paired review is untestable in the pilot because R1–R5
  all map to `AlperCamli` (D-47). So this point evidences *drafting*
  discipline, not *review* catch-rate, and does not exercise the
  customer-certification half at all (everything draft). Weigh accordingly
  when OB-2 is revisited — it is data point 1 of the promised 2–3.

## D-52 — Standing gaps at CP-1 close (future ledger / enrich items)

Recorded so they are visible items, not silent losses (the D-18 pattern).
From PR #13's Ungrounded gaps + open questions:

1. **user — Supabase↔GA4 identity.** No cross-system user key exists.
   Unblock: enable GA4 User-ID + app sends `user_id = users.id`, or a
   customer statement that a server-side/GTM identity stitch exists (cited).
2. **page — Supabase leg.** No DB-backed public page found. Unblock: a table
   carrying a slug/URL column, or customer confirmation that all public
   pages are frontend-static (closes it as "intentionally no Supabase leg").
3. **conversion — GA4 `purchase` population.** App emits `payment_completed`,
   not `purchase`; whether `purchase` is produced server-side / GTM /
   provider is unknown. Unblock: customer states the population path + its
   `transaction_id`.
4. **conversion — `purchase`↔subscription row join.** No shared key; only
   aggregate reconciliation supported. Unblock: a shared identifier
   (`checkout_session_id`/`transaction_id` on the subscription row, or GA4
   `user_id = users.id`).

Five open customer questions gate the draft→verified certification of these
docs (GA4 User-ID config; `purchase` population + `transaction_id`;
static-vs-DB public pages; whether `subscriptions` is the only
paid-conversion record / a per-payment ledger exists; any Supabase column
holding a GA4/Stripe checkout id). Answers certify the grounded mappings and
may close gaps 1–4.

**Validation-coverage gap (flagged by PR #13, HARD RULE 4; confirmed in
platform code).** The vendored 0.3.0 validator does not schema-validate
entity front-matter — `generator/schemas.py` registers no `entity`
`doc_class` (only machine-object/group/index + human-object/group/notes)
and `generator/validate.py` skips every path outside `systems/`
(`parts[0] != "systems"`), so entity docs receive KB-5 link/anchor checks
only; `depends_on ⊇ maps[].object` resolution is deferred to the sync engine
(CP-3). The three docs' `maps`/`depends_on` were verified by hand this
session, not by CI — a real gap to close when CP-3 lands the server-side
resolver, or sooner via an additive validator amendment (register-item
candidate).

---

# DECISIONS — task 2 (CP-2 benchmark harness, `benchmark/`)

The CP-2 deliverable: the CVBuilder golden-benchmark harness — suite
ingestion/validation, the three R1 context conditions, a dual-backend
journey runner + journey-prompt v1, R4-R6 scoring, the R7 CI integrity gate,
and the R8/R9 results+report machinery. Landed on branch
`task/2-benchmark-harness` (commits `21c0703`..`143a0b0`). Full platform
suite green (87 benchmark tests + the existing suite).

## D-53 — Suite is execution-deferred; correctness scores same-run goldens

`benchmark-seed-v0.yaml` shipped `execution_status: draft-pending-execution`:
every `verified_result` is a stub (checksum/rows `null`) because the
authoring session had no source access. Resolved **without mutating the
fenced seed**:

- The CP-2 exit criterion "all packet checksums reproduce" has nothing to
  reproduce. Reinterpreted: the canonical-CSV checksum machinery is proven by
  unit test (`tests/test_benchmark_canonical.py`), and byte-stable cases
  produce a reproducible checksum **in-run**, recorded in the results
  artifact — never written back to the seed.
- R5 correctness executes each golden leg **once per run** (`GoldenCache`) and
  compares agent-vs-same-run-golden for every case (the R5 unstable path,
  applied uniformly since no frozen results exist). Byte-stable cases use
  checksum identity; time-unstable cases use shape + tolerant values (exact
  ints, 1e-9 rel floats; live-mutation integer drift flagged, not absorbed).
- Env reconciliation: this machine has live Supabase/GA4/GSC (verified
  2026-07-13, `connections.md`), so the seed's deferral is resolvable — the
  handoff resume-checklist executions run inside the harness.

## D-54 — R3 amended: dual runner backends; baseline runs Backend B **[user ruling, applied]**

The runner supports two backends behind one interface; `JourneyRecord` is the
backend-agnostic contract (carries `backend` id + `cost_usd`; backend joins
the R8 key). **Backend A** (`api`) = direct Anthropic tool loop. **Backend B**
(`claude-code`) = headless Claude Code (`claude -p`, `--output-format
stream-json`, pinned `--model`, fresh session per journey; executors as a
local MCP server `benchmark.mcp_executor`; `--allowedTools` = `Read` +
`mcp__executor` only, no Bash; credentials scoped to the MCP server's
`.mcp.json` env, never in the agent process). Comparability: one backend per
baseline; cross-backend comparison out of scope. Auth via the VS Code
extension's Claude Code binary (`CLAUDE_CODE_EXECPATH`, subscription); the
CLI is not otherwise on PATH here.

- **Subscription-policy note (ruling):** subscription coverage of `claude -p`
  is current Anthropic policy under review (support.claude.com article
  15036540). Re-verify before future large runs.

## D-55 — Smoke evidence; full baseline held

Smoke (RB-01 × 3 conditions × 1 rep, Backend B, `claude-opus-4-8`) —
`results/smoke-2026-07-15/`:

- Selection precision/recall **1.0** and first-try executable **1.0** in all
  three conditions; **cost $0.85** total (~$0.28/journey); **GA4 executions
  0** (RB-01 is Supabase-only); golden executed once.
- Correctness **0** everywhere — a *real grain/window divergence*, not a header
  artifact: golden is daily-over-June (6 rows); agents chose weekly/monthly
  all-time (11 / 4 rows). That resolution lives in the seed
  `resolution_notes` (customer intent), not in schema or either KB, so no
  condition can hit it from context alone. The benchmark is cleanly
  separating "found the right source" (perfect) from "matched the customer's
  exact intent" (context-bounded).
- The full 90-journey baseline is **held pending go** (user, this session).
  Launch: `python -m benchmark.baseline --backend claude-code --reps 3 --out
  results/ --workdir <scratch> --enriched-kb ~/Desktop/kb`.

## D-56 — Evidence pointers (MC-1 / FM-2 / SP-4·FM-4)

From the suite + the smoke report (`results/smoke-2026-07-15/report.md`):

- **MC-1** (retrieval recall, lexical default — no embeddings): per-journey
  selection-recall table, labeled MC-1. Smoke: recall 1.0 on RB-01 in all
  conditions.
- **FM-2** (visual registry): **5/5** registry kinds
  (`table|line|bar|scorecard|pivot`) exercised + one `other:funnel` (RB-07).
- **SP-4 / FM-4** (recurring/parameterized): **10/10** cases `recurring:
  true`; the suite exercises the re-journey path SP-4 leaves as the v1 answer.

## D-57 — Suite-format change proposals (back to the author; seed unchanged)

Surfaced by building/scoring; none applied to the fenced seed (JC — format
changes are proposals, never silent mutations):

1. **Execution-deferred `verified_result`.** The stubs mean the suite cannot
   self-check numeric correctness in CI. Proposal: on the next live session,
   fill `verified_result` (rows/checksum/executed_at) for the byte-stable
   cases (RB-01/06/07) so those gain a frozen anchor; unstable cases stay
   same-run.
2. **API contract-object precision (RB-05).** A golden-faithful agent scores
   selection precision **0.556** on RB-05 because GSC returns 4 metrics by
   contract and the GA4 golden pulls `activeUsers`, while `expected_objects`
   lists a curated subset. Options: (a) list every contract-returned object in
   `expected_objects`, or (b) score API contract metrics as a bundle.
   Reported per-case meanwhile; recommend (a), consistent with R4's "score
   what the executed statement actually pulls."
3. **Customer resolution not in context.** Cases whose golden encodes an
   arbitrary customer grain/window (RB-01) make correctness near-unhittable
   from context. Not a defect; recorded so the baseline's low-correctness rows
   read as *intent-gap*, not *competence-gap*. The full run should show the
   enriched KB's edge on cases where the resolution *is* KB-encoded
   (conventions `dataState`, entity join rules) vs. arbitrary like RB-01.

## D-58 — CP-2 exit-criteria status

**Met:** suite validates; the R7 CI integrity gate is green on the current
suite and the staged-defect (a golden referencing a dropped column against a
doctored snapshot) fails it; the machine-kb builder is deterministic
(byte-identical rebuilds); scoring covers R4-R6 with the four required
fixture paths (perfect / wrong-table / unexecutable / unstable); the
dual-backend runner + prompt v1 exist; results/report machinery emits the
R9 report; GA4-count and golden-execution caching are observable (smoke:
GA4=0, golden executed once). **Pending:** the 90-journey baseline (held by
the user) and its committed results — the harness + the three-journey smoke
prove the path end-to-end.

## D-59 — Manual-baseline kit (operator-driven CP-2 baseline) **[user ruling, applied]**

The CP-2 baseline runs as human-operated *interactive* Claude Code sessions
(one fresh session per journey, subscription-billed), executing through
`benchmark.mcp_executor`. Transport-ruling points applied: **(2)
record-to-file** — the executor's JSONL log is the authoritative trace,
ingested into R3 records; **(3) executor guardrails** — unchanged
(SELECT-only SQL, one API call per tool call, credentials only in the MCP
server env); **(5) isolation** — three sibling condition dirs containing
only an identical `.mcp.json` + `records/` (+ `./kb` for the KB
conditions); **(7) per-journey autonomy** — one paste, no steering, one
sanctioned verbatim nudge max (OPERATOR.md §4). Kit = `benchmark/manual.py`
(+ Makefile targets), dev tooling under the dev-runner boundary; no product
code or spec changed.

- **Condition dirs live OUTSIDE the repo** (default `~/Desktop/cp2-runs`,
  `make conditions RUNS=…` to override), *deviating from the task's literal
  `runs/` path*: interactive Claude Code auto-loads `CLAUDE.md` from the
  cwd's directory ancestry, so an in-repo `runs/` would inject the repo's
  `CLAUDE.md` into every journey — violating the same ruling's isolation
  point. The builder/preflight hard-refuses roots with a `CLAUDE.md`
  ancestor, a `~/.claude/CLAUDE.md`, or stray/nested-memory files;
  `/runs/`+`/cp2-runs/` are git-ignored as belt-and-braces.
- **The identical `.mcp.json`** stays secret-free and per-journey-variable
  via Claude Code `${VAR}` env expansion: `${SUPABASE_DSN}` (operator
  sources `.secrets/env.sh`), `${BENCHMARK_JOURNEY_LOG}` (exported per
  journey; no default, so a forgotten export fails the server loudly
  instead of silently dropping the record), `${PWD}/kb` (context root;
  resolves to nothing in no-kb).
- **Backend id `claude-code-interactive`** joins the R8 key — a distinct
  key from headless `claude-code`, so manual and headless results never
  silently merge (R9: one backend per baseline). Fields the transport
  cannot measure are null (tokens, cost, session id); `tool_calls` counts
  executor calls, not turns; timestamps come from the log file's
  birth/mtime. Scoring is the unchanged harness: R4 selection stays
  parser-extracted from executed statements (test pins that a bogus
  self-declared list cannot leak into the scored set), R5 same-run goldens
  (executed once per scoring run), R6 first-try. `score` refuses to run if
  any condition tree or `.mcp.json` drifted from `manifest.json`
  (machine-kb tree ref, enriched tree sha, mcp sha).
- **Manifest** (`<runs>/manifest.json`) records kb_refs (machine-kb content
  ref `sha256:400e359d…`, enriched pinned at kb_ref
  `ccda04f499fc056ef324b51454d009ad7f8ea0fb`), snapshot_refs, prompt file
  sha, model pin (`claude-opus-4-8`), repo ref. Rebuild reproduces the
  machine-kb ref byte-identically (verified).
- **No-kb discovery path verified (kit deliverable 3):** the SQL guard and
  the live read-only executor both pass `information_schema` SELECTs
  (live: 17 public tables, matching the snapshot); GA4 metadata **is
  exposed** to no-kb via `mcp__executor__discover_schema("ga4")` — 466
  objects (376 dimensions / 89 metrics / 1 event) served from the pinned
  snapshot, the sanctioned introspection stand-in (runner.snapshot_discovery,
  D-53-deterministic); GSC likewise (6 dimensions / 4 fixed metrics, plus
  `run_gsc_query`'s fixed return schema). The live GA4 `getMetadata`
  endpoint is *not* exposed (`run_ga4_report` is runReport-only) and is not
  needed for no-kb — recorded so nobody expects live metadata.
- **Prompt:** `journey-prompt-v1-manual.md` is a v1 *variant* (version
  string stays `v1`; variant filename recorded in run notes). Deltas are
  transport wording only: `mcp__executor__*` names, KB reads via built-in
  `Read` (the server has no `read_context`; v1's kb-variant named a
  nonexistent tool for this transport), `run_sql(statement)` (v1 wrote
  `run_sql(system, statement)` — matches no executor surface; flagged), and
  one added tool-surface-pinning Rules bullet (Backend B equivalent).
  **Leak flags (recorded, not changed — R2 intact):** the shared Finishing
  example FQNs name *real* estate objects — `supabase.public.users` exists
  (17-table estate) and `ga4.standard.keyEvents:purchase` is the live key
  event — pre-seeding two real ids into every condition including no-kb.
  Condition-neutral (identical text in all three, and no-kb gets the full
  schema via discover_schema anyway) but a v2 prompt should use
  non-estate example ids. No KB *structure* (paths, doc layout) leaks into
  any condition; each kb variant describes only its own condition's KB.
- `backends.py` refactor: the JSONL→record fold extracted as
  `apply_journey_log()` (shared by Backend B and `ingest`); Backend B now
  also records `list_context` calls in `context_reads` (was silently
  dropped). Interactive-transport limitation recorded: kb-condition *file*
  reads (built-in `Read`) are not observable from the executor log, so
  `context_reads` under-reports in kb conditions (scoring never consumes
  `context_reads`; unaffected).

## D-60 — Readiness verification; no-kb property-grounding gap found & fixed

Pre-baseline readiness pass (user request). One **correction to D-59's
deliverable-3 verdict**, one empirical verification, both recorded:

- **Gap (fixed):** GA4/GSC *object* metadata was exposed to no-kb via
  `discover_schema`, but the **property identity was not** —
  `snapshot_discovery` omitted the snapshot's `source_properties`, and no
  case request names `properties/000000000` / `sc-domain:example-estate.com`.
  A no-kb agent therefore could not ground the `property` argument of
  `run_ga4_report`/`run_gsc_query` at all: RB-03/04/05/08 were unwinnable
  under no-kb *by construction* (never caught because the D-55 smoke ran
  only supabase-only RB-01). Both KB conditions document the ids (verified
  in the built trees). Fix: the discovery payload now includes
  `source_properties` (`runner.snapshot_discovery`; harness change, uniform
  across Backend A/B/manual — faithful to the introspection stand-in, since
  the service account inherently knows which property it queries). Test
  pins it. Condition trees were **not** rebuilt (the fix is code-side;
  KB trees are unaffected).
- **Interactive MCP path verified end-to-end, empirically** (the "will
  Claude Code run the mcp?" question): (1) pinned binary (VS Code
  extension, Claude Code 2.1.211) supports every OPERATOR.md flag;
  (2) stdio JSON-RPC probe against `benchmark.mcp_executor`, launched
  exactly as `.mcp.json` does from the real `no-kb` dir: handshake OK, all
  6 tools listed, `discover_schema(ga4)` returns the property id,
  `list_context` correctly returns no documents in no-kb, both calls land
  in the journey log; (3) one minimal one-shot `claude -p` probe with the
  exact operator flags (`--model claude-opus-4-8 --mcp-config .mcp.json
  --strict-mcp-config --allowedTools "Read,mcp__executor" …`) from the real
  condition dir: `${VAR}` expansion proven (journey log materialized at the
  exported `BENCHMARK_JOURNEY_LOG` path with the `list_context` entry), the
  agent called the tool and echoed `{"documents": []}`, and the
  `claude-opus-4-8` pin launches on this subscription. Nuance: *without*
  `--mcp-config`, project `.mcp.json` servers sit "pending approval" until
  approved once interactively — the operator command bypasses this via
  `--strict-mcp-config` (verified), and OPERATOR.md covers the
  approve-if-asked case.
- **Starter prompts:** five pre-rendered paste files (per user request:
  a handful, not the full 30) at `<runs>/prompts/{case}.{condition}.prompt.md`
  — RB-01 in all three conditions, RB-04 no-kb (exercises the new property
  grounding), RB-05 enriched-kb (three-system blend). Convenience copies of
  `manual prompt` output; the versioned template stays the source of truth.
  Remaining journeys render on demand.

## D-61 — Five-journey parallel smoke through the manual kit (headless transport)

The five starter journeys ran in parallel (user request; five Sonnet-driven
subagents as orchestrators only — each journey itself was one fresh
headless `claude -p` on the pinned `claude-opus-4-8`, exact operator flags,
real condition dirs, live data). **Not baseline records** — headless, not
the interactive protocol — so after scoring they were moved out of the
grid to `<runs>/smoke-2026-07-16/`; the baseline grid is back to 0/90.
Scored artifact committed: `results/manual-20260716T103207Z/` (sanitized;
its `run.notes` transport line is inaccurate for this one run — these were
headless smoke, recorded here as the authoritative correction).

- **All 5 journeys clean**: correct per-condition tool shapes (no-kb:
  discover→exec→finish; kb: list_context→exec→finish), `finish` in every
  log, zero failed executions, zero secret leakage, all within one 600s
  invocation. **First live GA4 traffic through the harness**: 6 agent
  `runReport`s (RB-04) + 3 more in RB-05, all ok; 2 GA4 golden legs
  executed. The D-60 property fix held in real journeys (no-kb agents
  grounded `properties/000000000` from discovery).
- **Scores** (1 rep, 3 cases): first-try executable **1.00 everywhere**;
  RB-01 selection P/R **1.00 in all three conditions**; correctness 0
  across the board — every zero traces to a *known suite gap*, not the
  harness: RB-01 grain intent-gap (agents chose weekly/monthly vs the
  golden's daily-June; D-57 §3), RB-05 contract-object precision 0.44
  (D-57 §2), and one **new suite finding → RB-04's GA4 golden returns
  (5 cols, 0 rows) live** — the property has Google Signals/demographics
  disabled, so `userAgeBracket`/`userGender` yield no rows; the golden is
  correctness-unwinnable until Signals is enabled or the golden is
  re-scoped (proposal for the seed author, D-57-style; the agent itself
  detected and disclosed the empty demographics).
- **Kit fix from the run:** Finder dropped `.DS_Store` into the KB trees
  and tripped the drift guard (proving it fires); `.DS_Store`/`._*` are OS
  noise, now ignored by `_tree_ref` and the stray-file invariant (test
  added). Grain divergence across conditions (weekly in no-kb vs monthly
  in both KB conditions for RB-01) recorded as an early signal for the
  baseline read.

## D-62 — CP-2 gate amendment: baseline deferred to CP-5 **[user ruling, applied]**

Ruling (2026-07-16), applied to the plan (§4.1 exit gate, §6.1 exit gate),
the open-decisions register (MC-1, SP-4/FM-4, FM-2 re-pointed), and the
committed smoke artifact (non-citability README sidecar):

1. **CP-2 exit criteria amended.** Retained: suite validates + packet
   checksums reproduce; R7 CI integrity green + staged-defect fires;
   harness proven end-to-end on the manual journeys (file-ingested records,
   R4–R6 scoring, both scoring paths, ≥1 journey per condition); FM-2 and
   SP-4/FM-4 evidence from packet fields; results artifact committed keyed
   per R8 with the manual-interactive transport. Removed: the 90-journey
   (and reduced 30-journey) baseline.
2. **The 5 journeys are transport-proof, not baseline numbers** — never
   comparable with future runs (prompt variant differs, n too small), never
   citable as with/without-KB evidence.
   `results/manual-20260716T103207Z/README.md` carries the notice.
3. **Baseline v1 moves to CP-5** as an added exit criterion of the packaged
   benchmark skill (10 × 3 × ≥1 rep, via the skill in Claude Code under
   subscription/Agent SDK credit); MC-1's recall table and the
   enriched-vs-machine-vs-none comparison land there. Until then: **no
   quantitative KB-value claims in any customer or demo material.**
4. **Watch-points recorded as binding for CP-5:** the CP-5 prompt inherits
   R2 fairness, R4–R6 scoring, R8 keying, and the harness's file-ingestion
   path unchanged; CP-6's JP-2 latency measurement unaffected.
5. **Coverage check (ruling pt 5) — nothing unexercised; no additional
   journeys required.** Evidence mapping against the retained gate, all
   from committed artifacts:
   - Suite validates (D-58); checksum-reproduction stands on D-53's
     recorded reading (execution-deferred stubs → machinery unit-proven;
     in-run checksums recorded: 13 draft checksums + golden checksums in
     the artifact).
   - R7 green + staged-defect fires (D-58).
   - End-to-end: 5 file-ingested records scored R4–R6; **both** correctness
     paths exercised (RB-01 = checksum mode ×3 conditions; RB-04/RB-05 =
     structural same-run-golden mode); **≥1 journey per condition**
     (no-kb 2, machine-kb 1, enriched-kb 2) (D-61).
   - FM-2 + SP-4/FM-4 sections emitted from packet fields (D-56; present
     in the committed report).
   - Artifact committed keyed per R8: `results/manual-20260716T103207Z`,
     backend key `claude-code-interactive` — read as the ruling's
     "manual-interactive" transport key (the kit's R8 id for
     operator-driven runs). D-61's honesty caveat stands: these five ran
     headless over the identical executor/record/scoring path; the
     interactive session leg itself was verified by the D-60 probe. If the
     gate is read to require journeys through literal interactive sessions,
     the minimum top-up is 3 (one per condition) — flagged, not assumed.

**CP-2 status: exit criteria met under the amended gate** (supersedes
D-58's "Pending: the 90-journey baseline").

---

# DECISIONS — CP-3a core bootstrap (`core/`)

## D-63 — CP-3a core bootstrap: job API + queue + runner (implementation decisions)

**Numbering note:** D-50..D-62 were allocated on the then-unmerged
`task/2-benchmark-harness` branch (CP-2 work), so this entry took D-63 to
avoid collision. That branch merged into `cp5-skills` at CP-5 start; the
CP-2 records now sit above this one, in number order, and the numbering
is collision-free as intended.

Scope: the CP-3a pre-rulings (A1 stack, B1 protocol scope, C1 no-ports,
D1 thin Python runner, E1 ops schema) executed as issued. Everything
below is an implementation decision *under* those rulings, or a flagged
deferral. Fence note: `specs/sync-orchestrator-spec.md` was present but
**untracked** at task start; it is not committed by this task's PR —
it needs its own spec commit (its only consumer here is the `runs`
table shape, §5.11).

**C1 wrapper added (flagged per the ruling):**

- `snapshot/accept.py` — the J-6 delivery gate as a CLI:
  `python -m snapshot.accept BODY.json [--key result] [--out FILE]`.
  Composes the existing `validate_snapshot` (schema + S-1 + C-4 hash
  recomputation) and the §6 canonical serialization exactly as
  `connectors.sdk.emission` builds it; zero new validation or
  canonicalization logic. Emits a one-line JSON verdict (+ metadata,
  sha256, canonical-body sha256) and writes the canonical bytes the
  core stores verbatim.

**Byte-fidelity transport design (the load-bearing one):** the runner
splices the SDK's canonical snapshot bytes verbatim into the §6.4
complete body; the core parses JSON for `lease_token` only and hands
the **raw request bytes** to the Python gate (`--key result`), storing
the gate's canonical output. JavaScript never re-serializes snapshot
JSON anywhere on the path, so accepted snapshots are byte-identical to
local CLI harness output (verified live: supabase/ga4/gsc canonical
bodies hash-equal across transport vs. direct CLI pulls; envelopes
equal modulo `captured_at`, which is per-run by §6/D-1). "Byte-identical
to the CLI harness" in the exit criterion is read exactly so.

**Protocol/queue decisions:**

- **Claim declaration `types` field (additive, §9):** runners declare,
  per connector, the job types they can execute
  (`{"name","version","types":["snapshot"]}`); the core skips
  non-declared types. Absent field = no filter (older clients).
- **Follower absorption on requeue:** when a leased/running batch job
  must requeue (retryable failure or lease expiry) while a §8 follower
  is already queued, the follower is deleted and its trigger history
  merges into the retrying job (entries marked `merged_from`). Both
  rows describe identical work (snapshots are absolute states);
  absorption preserves attempt count and backoff so persistent failures
  still dead-letter instead of resetting via the follower. The spec's
  state machine does not cover this corner; recorded here rather than
  invented silently as spec text.
- **Deadline enforcement is lease-derived:** heartbeats never extend a
  lease past `started_at + deadline_s`; past the deadline the lease
  lapses and the standard expiry path (requeue/dead-letter) applies. No
  separate deadline reaper.
- **Cancel of a non-running job:** `cancel` on `queued` is immediate;
  on `leased/running` it sets `cancel_requested` (runner acks per
  JC-7); a requeue/defer of a cancel-requested job terminalizes to
  `cancelled` instead of retrying.
- **Non-snapshot completes** (registered-but-unimplemented §4.2 types)
  store `result` inline on the job row; no validation pipeline until
  their capability consumers exist.
- **Interactive `deadline_s` default = 120 s fixed** — normatively it
  derives from the gateway guardrail, which doesn't exist until CP-6.

**Runner (D1) decisions:**

- **Credential injection convention:** manifest credential key → the
  connector's shipped env-indirection config field
  (`dsn → dsn_env`, `service_account → credentials_env`). The runner
  resolves `env://NAME` refs (process-env or env-file resolver behind
  the `CredentialResolver` seam), holds each value in a job-scoped
  environment variable, passes only the variable name in config, and
  deletes it after the job. Connectors and their config schemas are
  byte-unchanged.
- **Secret scrubbing (§7 defense in depth):** resolved values are
  string-replaced with `[REDACTED]` in any outgoing error envelope.
  JC-8 canary test drives a real postgres live job whose DSN password
  is a canary and asserts absence across protocol traffic, core+runner
  logs, and every ops row.
- **Cancellation abandons the work thread:** Python can't preempt a
  blocking introspection; on cancel/lease-loss the runner detaches the
  worker (daemon thread), reports within one heartbeat interval, and
  discards any late outcome — safe by J-7 (read-only, idempotent).

**Ops surface decisions (scope-fenced):**

- Enqueue/cancel/read endpoints (`POST /v1/jobs`, `GET /v1/jobs[/:id]`,
  `POST /v1/jobs/:id/cancel`, `GET /v1/snapshots*`,
  `GET /v1/health-events`) authenticate with the same per-runner bearer
  token set — no second auth system before SSO (CP-4). Producers are
  core-internal per J-1; these endpoints are the operator path (the
  exit criterion's "one command" is `node dist/cli.js enqueue --wait`).
- Tokens: `CORE_RUNNER_TOKENS="runner-id=token,…"`; binding a token to
  a `runner_id` is enforced at claim.

**Stack choices under A1:** fastify 5 + pg 8 + semver 7 (range matching
for `version_constraint`); vitest 2 + fast-check 3 for tests; ULID and
the migrations runner (numbered .sql, sha256-checksummed,
advisory-locked) hand-rolled rather than added as dependencies; config
is env-only. Core image carries a minimal python3 venv
(jsonschema only) + the `snapshot/` package for the delivery gate.

**Compose demo shape:** the stack's Postgres also hosts a `cl_demo`
database seeded from `fixtures/supabase-customer.sql`, so the postgres
connector exercises **live** mode in-stack with a
credential-reference-resolved DSN; ddl-file mode is unavailable inside
the runner container (it spins Docker containers) and stays a local-CLI
concern. Live mode against the example estate is a git-ignored overlay
(`deploy/compose.live.yml` + `.secrets/runner.env` +
`.secrets/core-live/*.json`).

**Conformance status (job spec §10):** JC-1..JC-9 implemented and green
(JC-2/JC-9 also as fast-check properties; JC-4/JC-8 with real runner
processes — SIGKILL mid-job → second-replica reclaim → canonical body
hash-equal to the CLI harness). **Deferred: JC-10** (interactive result
relay to a blocked producer — no producer exists until the CP-6
gateway; the interactive lane itself is implemented) and the §8
interactive per-system concurrency limits (same reason: the limits come
from execution policy the gateway owns).

**Exit-criteria evidence (2026-07-16, this machine):** compose demo
2/2 systems accepted; live overlay 3/3 (supabase 17, ga4 466, gsc 10
objects) accepted with J-6 validation and canonical-body hashes equal
to direct CLI pulls; dedupe, kill-reclaim, and staged-invalid →
dead-letter+health all asserted in the committed suites (TS 28 tests,
Python 359).

## D-64 — CP-3b sync orchestrator (implementation decisions)

Scope: the CP-3b pre-rulings (C2 language split, D2 git/PR mechanics,
E2 secrets & policy, F2 drill fixture) executed as issued. Everything
below is an implementation decision *under* those rulings, a flagged
interpretive reading, or a register proposal. The spec set was not
touched (amendment fence); proposals below name the diffs an authorized
spec PR would carry.

**C2 additions (flagged per the ruling):**

- `lineage/severity.py` — snapshot §7 note ³ finalization as a CLI.
  "Output column set and mappings unchanged" is implemented as: no
  column-set-shaping sub-diffs on the object, and incoming edges
  (F-1 identity + column mappings, evidence excluded — the ref embeds
  the definition hash and always differs) equal across old/new graphs.
- `lineage/scan.py` — the KB §6 scan (new implementation, authorized by
  C2; beside the graph code). Declaration surfaces: `depends_on`,
  entity `maps[].object`, the doc's own `object`, and the machine
  sibling's roster (K-4 uniformity); `external: true` excluded (KB-B).
  The §3.4 walk records min-hop edge-id paths; per (doc, breaking
  object) one reason is kept — direct declaration outranks a walk route,
  shorter routes outrank longer; the front-matter `contamination` value
  is the (path-length, object)-first reason, the changelog carries all.
- `generator/statuses.py` — front-matter-only writes as a
  formatting-preserving line edit (only the `status:` line and the
  `contamination:` line/block change; body and every other line
  byte-preserved; all-or-nothing with a post-edit re-parse guard). KB-4
  holds by construction.
- No logic changes to `snapshot/diff.py`, `lineage/{parser,graph,
  walk,writer}.py`, or `generator/{render,validate,frontmatter}.py`.

**Interpretive rulings (flagged; spec-amendment proposals below):**

1. **Diff baseline = the snapshot pinned at KB merged HEAD**
   (`.contextlayer/snapshots/<system>.json` in the stage-1 clone), not
   the previous ops-store acceptance. Forcing argument: SY-3 ("complete
   currently-true picture versus merged KB HEAD") and SO-7 (a second run
   *restates the still-true picture* while a PR is unmerged) are only
   satisfiable against the HEAD pin — a previous-acceptance baseline
   yields an empty diff exactly when restatement is required, and loses
   the superseded PR's contamination writes. JP-3 retention still backs
   recovery; a system with no pin diffs against an empty baseline
   (first sync = all-added).
2. **SY-3 restatement:** a run also carries, on their stored latest
   acceptance, all configured systems whose acceptance differs from
   their HEAD pin (no new job). Without this, supersede would close a
   PR whose systems the new run was not triggered for and drop their
   unmerged drift statement. SY-6 exclusion is unchanged and recorded;
   an excluded system's *previous* acceptance may still ride as
   restatement (the fresh acquisition failed; the last accepted state
   is still the latest truth).
3. **Status writes before renders** (spec §5 numbers them 8 then 9):
   machine index rows render the human sibling's `status`, so KB-8 at
   the PR head is only satisfiable when renders see the final statuses.
   Both land in the same atomic PR; nothing externally observable
   differs from the spec's numbering.
4. **KB-C executed as full render:** D-33 Rule B makes a full render
   byte-identical to the ideal subset render (SUBSET-RENDER-DESIGN.md's
   own analysis: subset scoping is purely a cost optimization), so the
   PR contains exactly the changed files either way. The example estate
   makes the cost negligible; the design note remains the plan if it
   ever isn't. Zero generator changes, which also keeps the vendored
   wheel's render behavior byte-stable across 0.3.0 → 0.4.0.
5. Pin files are updated only for systems with a non-empty diff ("sync
   updates it in the same PR as the renders it implies", KB §3);
   lineage re-derivation reads the full post-update pin set (matching
   how the 1.6 bootstrap built the HEAD graph). Re-derivation is
   "required" iff a `definition_changed` sub-diff exists, a
   definition-bearing kind (view/materialized_view) was added/removed,
   or an added/removed FQN is a current-graph node.
6. **Wheel carry details (§10):** the wheel commit also repoints the
   `kb-ci.yml` install line from the old wheel filename to the new one —
   without it the PR's own KB CI cannot run the new wheel (SO-10);
   recorded as within the D-46 exception boundary (wheel + manifest +
   the CI pin). Manifest rewrite preserves the KB-owned comment header
   and the `source`/`runtime_deps_pinned_in` values; `built` comes from
   config or the wheel file's mtime, never the run's wall clock
   (SY-1/SO-12 determinism). Wheel-only runs title as
   `sync: 0 breaking, 0 additive (wheel-only update to <v>)` — a
   deliberate, flagged deviation from the KB §9 title grammar for a PR
   that states no drift.
7. **Webhook mechanics (§4.2):** any content type is accepted and
   discarded on hook paths (CI vendors vary); the JSON parser never
   parses or retains hook bodies; secrets compare as fixed-length
   sha256 digests via `timingSafeEqual`; Content-Length over the cap
   is 413 before the body is read; unknown and unregistered systems
   both 404 with an identical body (M-4 spirit).
8. **Ops surfaces:** admin CLI works direct-DB (E2's Connections-UI
   stand-in; same trust position as `migrate`); manual triggers record
   the acting OS user. Single-flight is a Postgres advisory lock; a
   deployment restart marks torso `running` runs `failed
   (interrupted)` with a health event — exercised for real during the
   live gate demo.
9. **Live-demo auth:** the sync PRs on the customer KB were opened with
   the steward's own PAT (gh keyring) because the `contextlayer-sync`
   machine account does not exist yet; commits are authored as
   `contextlayer-sync` regardless (KB-3/KB-4/blame read correctly).
   Deployment shape remains D2's fine-grained machine-account PAT.

**Register proposals (specs untouched; spec diff leads any
authorized PR):**

- *sync spec §3/§5.1 clarifying amendment:* define "baseline (previous
  accepted snapshot ref)" as the acceptance pinned at merged KB HEAD
  (ruling 1 above), and note the SY-3 restatement set (ruling 2) in §5.1.
- *sync spec §5 stage-order note:* §5.9 front-matter writes are applied
  to the worktree before the §5.8 renders (ruling 3); KB-8 forces it.
- *master register, new item:* GitHub App identity for sync PR authoring
  (parked per D2); interim = fine-grained PAT for a `contextlayer-sync`
  machine account, which should be created before the next onboarding.
- *SO-B note:* label emitted is `sync:additive-only`, applied whenever
  the breaking count is zero (including metadata-only and wheel-only
  PRs).

**Stack under A1:** `yaml` (npm) added to the core for sync-policy and
manifest parsing; everything else unchanged. Python package 0.4.0 (new
stage modules; no validation-rule changes — KB-8 renders byte-stable).

**Conformance status (sync spec §11):** SO-1..SO-12 all implemented and
green in `core/test/sync-{triggers,run,drill}.test.ts` (SO-4/SO-8 drive
the drill fixture through a real runner + ephemeral Postgres against a
local scratch KB repo; SO-4's live variant is the deployment gate
below). CP-3a JC suite and the 359-test Python suite unchanged green;
+31 Python tests for the new stage CLIs.

**Exit-criteria evidence (2026-07-17, this machine):**

- *SO conformance:* 12/12 green — `core` suite 45 tests (7 files) incl.
  `sync-triggers` (SO-1/2/9 + rotation), `sync-run` (SO-3/5/6/7/10/11/
  12), `sync-drill` (SO-4/8 through a real runner + ephemeral Postgres
  against a local scratch KB repo, byte-exact golden changelog); Python
  390 passed.
- *Live gate (a) — drill:* `make drill` / `sync-drill.test.ts`: trigger
  (§4.3 DDL re-handover) → snapshot job → real runner → diff → lineage →
  scan → front-matter-only writes → renders → PR, producing exactly the
  fixture's expected contamination set (incl. the depth-2 lineage path
  to `metrics/net-sales.md`), statuses, and changelog; KB-4 asserted
  byte-wise; `generator.validate` 0 errors on the PR tree.
- *Live gate (b) — customer KB:* real drift (`supabase.public.imports`
  row-estimate) flowed end-to-end through the real core + runner
  against github.com/AlperCamli/DataAnalyticsTool: run
  `01KXQXCX1G…` → PR #14 (ga4/gsc excluded per SY-6 — their
  pre-restart jobs had dead-lettered — with health events and the
  changelog's exclusion section); run `01KXQXGXGX…` → PR #15, all
  three systems, wheel commit `0.3.0 → 0.4.0` first, superseding #14
  with a successor comment and branch deletion; two webhook triggers
  then produced run C (PR #16 ⊃ #15) and a coalesced follow-up run D
  (PR #17 ⊃ #16) — live single-flight + coalescing. End state: exactly
  one open PR (#17), KB CI **pass** on every PR running the carried
  0.4.0 wheel unmodified; `generator.validate` on the PR tree: 0
  errors, 0 warnings (SO-8). A mid-demo core restart marked the torso
  run `failed (interrupted)` — the crash-recovery path exercised live.
- *Rotation:* `sync hook set supabase` → 202; rotate → old secret 401,
  new secret 202, unknown system 404 — same core process throughout.
- *SO-2/SO-9 demos:* policy edits merged to a scratch KB HEAD picked up
  on the next tick, and freshness warnings raised by a shrunk threshold
  then cleared by the next acceptance, are the committed
  `sync-triggers` tests; `sync freshness` against the customer KB HEAD
  policy read 3d/3d/30d thresholds live.

---

# DECISIONS — pre-CP-4 hardening (task 4.0)

## D-67 — Security review #1 findings F2/F3/F4 landed **[closes D-66 point 2]**

Ruling **D-66** accepted security review #1 (P-B/P-C/P-D as code fixes,
landing pre-CP-4 as the live-pilot-facing hardening task 4.0). This
record closes **D-66 point 2** — findings **F2, F3, F4** — with tests as
the definition of done. No spec change; the amendment fence held. P-A
(auth split) is CP-4 and is untouched here.

**F2 — webhook socket cap enforced during read.** The hook route now
carries a route-level `bodyLimit = cfg.sync.hookBodyMaxBytes`
(`server.ts`), so Fastify enforces the 64 KB cap while reading the body,
chunked or not — an absent/understated `Content-Length` can no longer
stream past it to the global result limit before the (unauthenticated)
secret check. The `onRequest` header pre-check stays as a fast reject for
an honest oversized `Content-Length`. *Test:* a ~640 KB chunked body with
no `Content-Length` and no secret is rejected at the cap (Fastify
`FST_ERR_CTP_BODY_TOO_LARGE`, distinct from the pre-check), nothing
enqueued (`sync-triggers.test.ts` F2).

**F3 — job-spec §7 redaction implemented, both sides.** A new
pattern-based scrub (connection URIs with userinfo, `password=…` keyword
secrets, bearer tokens → `[redacted:credential]`) exists as
`core/src/redact.ts` and `connectors/sdk/redact.py`. Runner side: every
`JobError` is built through `_job_error`, scrubbing the exception message
+ detail (incl. the traceback) before it can travel the `fail` wire call;
the `warning` log lines that echo the exception are scrubbed too
(`runner.py`). Core side (defense in depth, since the core holds only
references — J-4 — not values): `failJob`/`deferJob` scrub the
runner-supplied envelope and `recordHealthEvent` scrubs every detail
before storage in `jobs.error` / `health_events.detail`, the rows any
bearer-token holder can read. *Tests:* a live-shaped DSN in a staged
connector exception → the marker, never the value, in
`outcome.error.message`/traceback (`test_sdk_runner.py`) and in
`GET /v1/jobs/:id` + `GET /v1/health-events`
(`conformance.test.ts` JC-8 redaction). The existing happy-path JC-8
(`e2e.test.ts`) still passes; references (`env://…`) are never redacted.

**F4 — sync PR title/body neutralize interpolated snapshot text.**
`changelog.ts` gains `neutralize()`, applied to every snapshot-derived
interpolation (FQNs, view-diff detail, rename interpretations, contaminated
docs, lineage-path elements, excluded reasons, system names, wheel
versions): newlines collapse, code-span backticks are defused, and inline
markdown metacharacters (`< > @ [ ] * |`) are HTML-encoded, so a crafted
object name cannot break out of its code span, forge a heading, or fire an
`@mention` in the PR a human reviewer trusts. It is a **strict no-op on
ordinary identifiers**, so the deterministic changelog holds: SO-4's
byte-exact golden (`fixtures/drill/expected/changelog.md`) is unchanged.
*Test:* a backtick + `@mention` + newline-heading object name renders inert
(`changelog.test.ts` F4), plus a golden-determinism no-op assertion.

**Scope note.** Map-lookup keys (`contaminatedByObject`, breaking-fqn
lookups) keep the raw string; only display values are neutralized. Full TS
suite 50 passing (incl. drill golden, both JC-8 paths, SO-1 413), Python
391 passing.

---

# DECISIONS — CP-4 (M1): MCP server, fault ledger, P-A split

## D-68 — CP-4 build decisions, KB-F resolution, register closures

Scope: the CP-4/M1 build under ruling D-66 — per-call OIDC identity,
profile enforcement, content tools with trust blocks, validate_sql with
signed validation tokens (issuance + verification library; enforcement
at an executor is CP-6), fault ledger with flag_gap/list_gaps, audit,
rate limits, and the P-A auth split. The four authorized spec
amendments led the diff (job spec §6 + JP-6 [P-A/D-66.1], MCP spec §4
[MCP-R9/D-66.4], MCP spec §6.5 [P-E/D-66.3], ledger spec §3.3/§10
[LED-R2/D-66.5]); the amendment fence held otherwise.

**KB-F resolved (register updated):** repo-level human docs
(`index.md`, `conventions.md`, `_notes.md`) keep the default — no
`status` front-matter, no trust block. They are search-indexed and
visibility-checked exactly like every doc (MCP-R15), their search
one-liners derive from title/first line only (matched body text is
never echoed), and no v1 tool serves their full body — so absence of a
trust block cannot mislead an agent about repo-level content it never
receives wholesale. Test: `mcp-conformance.test.ts` MCP-R15 pair.

**Register closures (per D-66.8):** MC-5 **closed** — MCP-R9 landed
(trust-block `snapshot_ref` + `render_lag` + warn-user; test MCP-R9).
FL-E **closed** — LED-R2 (storage scrub + visibility + length bounds)
and LED-R5 (render neutralization via the F4 `neutralize()`) landed
with named tests. SP-2 **closed conditional on the M1 live demo**: the
benchmark waiver keys on the server-resolved profile only — MCP-R2 +
MT-1 + the SP-2 closure test are green (client asserting `benchmark`
without the role → connection refused, audited).

**Implementation decisions (flagged):**

1. **Dev IdP is an in-repo minimal OIDC provider** (`core/src/devidp.ts`,
   compose service `devidp`, marked DEV ONLY), not Keycloak: Claude
   Code's remote-MCP OAuth needs RFC 8414 discovery + RFC 7591 dynamic
   client registration + PKCE, which Keycloak only allows after
   client-registration-policy surgery, and MT-9 needs a deterministic
   role-revocation lever (`POST /admin/roles`, introspection reads live
   roles). The deployment shape is unchanged — a real customer IdP via
   `CORE_OIDC_ISSUER`; the pilot has no customer IdP, so the dev
   provider *is* the pilot IdP. Tests run it in-process.
2. **Identity is per-call token introspection** (RFC 7662) at the IdP,
   never local JWT verification alone — forced by MCP §3 ("revocation
   takes effect immediately") and the MT-9 live variant. Discovery-doc
   caching only; nothing token-derived is cached.
3. **P-A ops surface** accepts two platform identities per D-66.1's
   "OIDC user or service identity": OIDC roles ∩ `CORE_OPS_ROLES`
   (default `ops,steward`), or a static service-token set
   `CORE_OPS_TOKENS` — distinct from runner tokens, hash-compared with
   the same no-early-break discipline. A valid runner token on the ops
   surface is 403 (authenticated, insufficient); garbage is 401. The
   compose CLI (`enqueue`) now authenticates with the ops token.
4. **Profile binding** rides `?profile=` on `/mcp` (the compiled-config
   convenience); the transport is stateless (one SDK server+transport
   per request), so identity and the roles→profile check re-run on
   every request — MCP-R2's "fails the connection" is the 403 on
   initialize and on every later call alike, and MCP-R3 session
   fixation is impossible by construction (no session state exists).
5. **MCP-R2's "roles ⊇ profiles roles:"** is implemented as non-empty
   intersection — platform-architecture §5 defines `roles:` as "who may
   use it (OIDC groups)", so any listed group suffices.
6. **KB read consistency:** merged-HEAD is re-checked at most every
   `CORE_KB_REFRESH_MS` (default 5000; tests 0 = the §3 letter). A
   pilot-scale concession, env-tunable to strict.
7. **Facts serving (MC-5):** the workspace is a HEAD clone with the
   latest accepted snapshots written over the pins and the generator
   re-run (full render — the D-64.4 KB-C precedent). KB-8 makes the
   workspace byte-identical to HEAD when there is no lag; render-lag is
   pin-bytes ≠ latest accepted body, and lagging systems serve facts
   from the new snapshot with `render_lag: true` + warn-user (MCP-R9).
8. **Validation tokens:** HMAC-SHA256, keys in ops Postgres
   (`signing_keys`, kid-rotating, old keys verify until expiry);
   `core/src/vtoken.ts` is issuance *and* the verification library the
   CP-6 gateway must call — every §5 binding check lives there once.
9. **sqlval** is a new Python package (0.5.0): the validate_sql SQL
   dialect as a C1/C2-pattern stage CLI (sqlglot 30.12.0, the D-38 pin;
   AST-decided refusals, never regex). No KB-CI validation-rule
   changes; the version bump makes the §10 wheel carry honest — the
   next sync PR carries 0.5.0 automatically (SO-10).
10. **Ledger mechanics:** `distinct_subjects` recomputed from events on
    ingest; reopen preserves the prior `resolution` (LED-R6 "history"
    on the spec's fixed DDL); flag_gap's "per session" rate limit keys
    per identity/hour on the stateless transport; CL-Resolves detection
    is a merged-PR poll through the PR provider (GitHub API / local
    store; cursor in `mcp_state`) on the ledger sweep cadence — the
    ledger spec's "webhook it already has" does not exist yet, and the
    poll is provider-uniform. list_gaps is server-gated to the
    steward/benchmark **server-resolved profiles** over and above the
    profile allowlist (LED-R1 cannot be widened by a mis-authored
    custom profile).
11. **Rate limits** are in-memory per core process (single-process
    deployment shape; MC-4 stays open on pilot telemetry).
12. **Search (M-6):** tiered deterministic ranking (exact FQN/alias ≫
    title ≫ front-matter tokens ≫ body), query stopwords dropped,
    entity/metric routing boost, total order with path tie-break.

**Conformance status:** MT-1..MT-9 green (`core/test/mcp-*.test.ts`);
MT-3/MT-4 exercised at the verification-library level plus the
never-executes tool path (execution is CP-6; MT-5 adapted to the
validate-time guardrail echo); MT-10 is CP-6/CP-7 scope (publish).
FL-4/5/6/7/10 green. Every MCP-R1..R15 and LED-R1..R7 item has a named
test — the requirement→test map is in `PR-CP4-M1.md`. Full suites: TS
168 (11 files + 3 MCP files), Python 406. Customer-KB profiles landed
as PR #18 (reporter/steward + roles.yaml OIDC wiring; steward merges).

**Open for the M1 gate (not code):** the live two-machine demo (OAuth
as reporter, contamination surfacing, token issue/refusals, flag_gap /
list_gaps split, MT-9 live revocation, render-lag live, audit review)
— runbook in `PR-CP4-M1.md`; and P-H (the `contextlayer-sync` PAT
least-privilege assertion, D-66.7 — recorded with the SP-2 sign-off).

## D-69 — CP-6/M2 governed execution: build decisions, JP-1/JP-2 closure

**Context.** M2 is the direct-on-OLTP checkpoint the plan classes as the
pilot-ending risk (plan §6.2). The pre-rulings adopted for the build were
G1 (contract path first — `execute` jobs through the queue), G2 (defense
in depth at gateway *and* executor), G3 (OLTP protection by database
role), G4 (full MCP-R5 token enforcement). All four are implemented as
stated; no relaxation was needed anywhere, and no scope-fence item was
touched.

### Closures

1. **JP-2 — closed, measured, passes.** Budget: ≤500 ms p95 claim-to-start
   on a warm runner. Measured over 100 warm validated executes against a
   real Postgres through the real Python runner
   (`core/test/execute-e2e.test.ts`, which asserts the budget so a
   regression fails CI):

   | metric | p50 | p95 | max |
   |---|---|---|---|
   | claim-to-start (normative JP-2) | 7.2 ms | **10.9 ms** | 23.1 ms |
   | end-to-end `execute_sql` (non-normative) | 220 ms | 288 ms | — |

   Both numbers are recorded because they measure different things and
   only the first is the committed budget: JP-2 is defined (job spec §11,
   plan §6.5) as *claim-to-start overhead excluding query time*, which is
   `jobs.created_at → jobs.started_at`. End-to-end wall time additionally
   includes the `validate_sql` call (which spawns the `sqlval` stage CLI —
   the dominant term), HTTP, and the query itself. Reporting only the
   end-to-end figure against a claim-to-start budget would have been a
   category error in our favor, which is why it is labelled.

2. **JP-1 — closed: runner routing stands; no short-circuit built.** The
   pre-ruling pre-authorized the core-native Postgres short-circuit *if*
   the queue path missed budget. It does not miss: 10.9 ms against a
   500 ms budget is a 46× margin, and the LISTEN/NOTIFY claim path (CP-3a)
   plus the new JOB_DONE producer wake are what make it so. Building the
   alternative transport would have added a second execution path, a
   second audit shape, and a second thing to security-review, to buy
   latency headroom already there by two orders of magnitude. One path.

### Implementation decisions

3. **Producer wake is LISTEN/NOTIFY (`cl_job_done`), not an in-process
   emitter.** §6.4 says the core "relays the result to the blocked
   producer via internal notification" without specifying the mechanism.
   An `EventEmitter` would be simpler and would work today, on one core
   replica — and would silently stall the moment a second replica exists,
   because the runner delivers to whichever replica it claimed against,
   not necessarily the one holding the waiting MCP request.
   `awaitJobResult` waits on the notification but re-reads job state on
   every wake *and* on a 250 ms poll, so a dropped or coalesced
   notification costs latency, never correctness.

4. **Interactive `deadline_s` derived, per §4.2** (`interactiveDeadlineS`
   = guardrail `timeout_s` + 30 s margin). The margin covers claim,
   connect, and delivery — everything the statement timeout does not
   bound. Without it a query using its full budget would race its own job
   deadline and surface as a lease expiry rather than the honest
   `timeout` guardrail.

5. **G2 in practice: `Guardrails.parse` floors, never trusts.** The
   executor's guardrail parsing treats an absent, partial, or oversized
   payload envelope as a request for the *conservative default*
   (row_cap 1000, timeout 30 s), with hard ceilings above. `statement_class`
   is never read from the payload as a widening signal — select-only is
   the only class this SDK executes, so a forged value cannot unlock DML.
   This is what makes CC-3 pass rather than being a comment claiming it
   would.

6. **One parser, two call sites.** `sqlval.check_statement_class` was
   extracted from `validate_statement` so the executor re-runs the
   *identical* refusal set locally (QE-1) without needing a snapshot. A
   second implementation in the executor would have been the obvious
   place for the two layers to drift apart.

7. **G3 role wall, checked twice.** `check_role_is_readonly` verifies role
   attributes (SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS), every table write
   grant reachable through role membership, and schema CREATE. It runs at
   runner startup (`execution_preflight` in the runner config) *and*
   before every query — grants can change under a long-lived runner, and
   the per-query check is the one that cannot be stale. On startup failure
   the runner **withholds `execute` from its claim declaration**: it does
   not offer to do the work at all, while metadata sync for the same
   connector continues. Provisioning SQL + verification queries:
   `deploy/execution-role.sql` (applied by the operator, not by us).

8. **Row cap enforced during streaming.** A named (server-side) cursor
   fetches in batches to `row_cap + 1`; the extra row is how truncation is
   *detected* without pulling the remainder, and it is dropped rather than
   returned. A post-hoc trim would have satisfied CC-4's assertion while
   leaving memory unbounded — the property worth having is the bounded
   fetch, not the trimmed list.

9. **API dialect: two different honest guarantees.** GSC's vocabulary is a
   fixed constant table (D-30), so its executor does the full MT-8 check
   locally and an undocumented dimension never reaches the wire. GA4's
   surface is property-specific and lives in the snapshot, which the
   executor does not hold; there the local check is the documented
   *operation* allowlist, and GA4's own rejection of an unknown field is
   mapped to `schema_mismatch` rather than surfacing as an opaque 400.
   Between gateway and source, an undocumented GA4 dimension is refused
   twice; it is not claimed to be refused locally when it is not.

10. **Connectors 0.1.0 → 0.2.0** (postgres, ga4, gsc) for the additive
    `query` capability. Canonical snapshot bodies exclude `connector`
    (S-3), so C-2/C-4 hashes and every fixture are unaffected — the bump
    is invisible to determinism by design. Job version constraints in
    `deploy/jobs/*` updated to `>=0.2 <0.3`.

11. **GA4/GSC `api.py` extraction.** Both connectors' shared manifest,
    endpoints, credentials, and status mapping moved out of `connector.py`
    so the executor can import them without a cycle (the connector module
    registers the executor). `connector.py` re-exports every moved name;
    no caller changed.

### Interpretive rulings (flagged, not silent)

12. **Fault-ledger §5 contradicts itself on `schema_mismatch_at_execute`**,
    calling it a "shipped-but-disabled rule" and then, in the same
    sentence, "enabled by default actually — it is deterministic and
    severe." Taken as **enabled**, following the parenthetical and its
    stated rationale. This is not a new choice: migration 0006 already
    seeded it `enabled = true` at M1, so the ruling confirms the shipped
    reading rather than changing behavior. The gateway honors the row's
    flag, so an operator can still disable it. **Recommend the spec
    sentence be amended to say one thing** — filed as a proposal, not
    fixed here (amendment fence).

13. **`statement_class` used as a capability code.** Capability §6
    enumerates `syntax_error, permission_denied_at_source, timeout,
    row_cap, quota_exhausted, schema_mismatch`. A local statement-class
    refusal (the CC-3 canary) is none of these: calling it `syntax_error`
    would misreport a policy refusal as malformed SQL. Emitted as
    `capability_code: statement_class` under the unchanged outer
    `guardrail` code, consistent with CI-8 (outer taxonomy fixed,
    capability precision underneath) and the additive-growth norm.
    **Proposed as an additive entry to the §6 capability-code list.**

### Bug found and fixed in M1 code

14. **Audit dropped the statement text for execute.** `mcp.ts` wrote
    `statementText` only when `tool === "validate_sql"`, but spec §8
    requires full statement/intent text for **validate, execute, and
    publish** (reads carry `args_digest` only). Correct while execute was
    stubbed, wrong the moment it landed — and it would have produced an
    audit trail that looked complete while omitting exactly the calls that
    touch customer data. Now keyed on a named `STATEMENT_TEXT_TOOLS` set.

15. **Credential scoping for execute jobs (found in self-review).** The
    connection registry (`sync_systems`) is shared with snapshot jobs and
    therefore holds the *introspection* credential. The gateway initially
    passed the registration's credential list through verbatim, which
    handed the introspection DSN to every execute job. Nothing read it —
    the postgres executor resolves `execute_dsn` only — but it widened
    what a compromised execute job could reach for no benefit, and it is
    exactly the kind of latent hole G3's role wall exists to close.
    The gateway now passes only credentials the registration marks
    `required_for: ["query"]` (the manifest's own vocabulary, capability
    §3), and **fails closed** with an actionable message when none is
    marked — rather than silently falling back to the broader credential.
    Regression test in `core/test/mcp-execute.test.ts`.

16. **`deploy/execution-role.sql` shipped with a syntax error**
    (`GRANT CONNECT ON DATABASE current_database()` — GRANT needs a
    literal identifier), caught by the operator in the Supabase SQL
    editor. Root cause: the file had never been executed. Fixed with a
    `DO`/`format(%I)` block that works whatever the database is called,
    and the file is now **run as a test**
    (`test_deploy_execution_role_sql_provisions_a_role_that_cannot_write`)
    rather than being documentation that resembles SQL.

    Running it surfaced a second, more interesting point: with the script
    applied, *every* write was refused by `ReadOnlySqlTransaction` — the
    `default_transaction_read_only` session setting — which is the
    barrier the role can switch off itself. The test now defeats that
    flag first and then asserts the GRANTs refuse writes with
    `InsufficientPrivilege`, because the grants are what G3 actually
    rests on. A check that stopped at the first refusal would have passed
    while leaving a write path one `SET` away. The file now says so in
    the comment at step 5. Also corrected there: the
    `ALTER DEFAULT PRIVILEGES` note (default privileges are recorded per
    *creating role*, not per schema — the original comment overclaimed),
    and an explicit warning not to grant Supabase's `auth`, `vault`, or
    `storage` schemas.

### Conformance status

MT-3/MT-4 upgraded from issuance-only to **enforcement**: no token,
tampered statement, forged signature, re-signed payload, expired token,
foreign subject, and superseded snapshot each return
`revalidate_required` *and* are asserted to enqueue no job
(`core/test/mcp-execute.test.ts`). MT-5 asserts client-supplied guardrails
are dropped and the profile's appear in the job payload. CC-3 (canary
DML/DDL/CTE-write/multi-statement/locking refused with guardrails stripped
from the payload), CC-4 (streaming cap + `truncated`), CC-5 (QE-2 comment
tag observed in Postgres' own statement log), CC-6 (interactive quota
terminal, never deferred) green in `tests/test_postgres_executor.py` and
`tests/test_api_executors.py`. The staged-bypass test drives the driver
directly, past every parser, and the role still refuses the write.

Full suites: Python 447 + 13 skipped, TypeScript 127 (13 files).

**Live evidence captured.** GA4 `runReport` and GSC `searchAnalytics.query`
execute against the real example estate for documented fields, and an
undocumented dimension is refused on both
(`tests/test_live_execute.py`, env-gated).

### Live evidence against the example estate (2026-07-20)

`deploy/execution-role.sql` was applied to the pilot Supabase by the
operator (with a syntax fix — see D-70). Verified live:

- **G3 startup check passes**: role `example_exec`, engine 17.6.
- **Role posture confirmed through the introspection connection**: zero
  write grants reachable through role membership; `public` is the only
  schema with USAGE — `auth`, `vault`, `storage`, `realtime`, and
  `extensions` are all closed, so the Supabase schemas holding password
  hashes, refresh tokens, and decrypted secrets are unreachable by any
  agent query; role holds none of SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS;
  all three session defaults applied.
- **Real SELECT over live customer data**: 17 rows from
  `pg_stat_user_tables`, executed under the execution role, 1021 ms.
- **Write refused at the role** driven straight at the driver, past every
  parser we own; **row cap truncates** on an over-cap query.
- **Startup refusal demonstrated live**: pointing execution at the
  introspection DSN is refused — *"execution role 'postgres' holds
  CREATEDB, CREATEROLE, BYPASSRLS; execution requires a role with none of
  these (G3). Refusing to serve execution."* — at startup **and** per
  query. At the runner level the effect is the declaration itself: with
  the execution role it offers `['execute', 'snapshot']`; with the
  write-capable role it offers `['snapshot']` only. Execution is withheld
  while metadata sync continues, as designed.
- **GA4 `runReport` and GSC `searchAnalytics.query`** return live data for
  documented fields; undocumented dimensions refused on both.

**Finding raised, not fixed here (out of M2 scope).** The *introspection*
connection runs as `postgres`, which holds CREATEDB, CREATEROLE, and
BYPASSRLS. Snapshot introspection reads catalogs and needs none of those.
G3 scoped the execution role because that is the path an agent drives,
but the same least-privilege argument applies to introspection — and
BYPASSRLS in particular means the introspection role sees through row
level security. **Proposed as a register item**: a dedicated
least-privilege introspection role, with the same provisioning-file
treatment. Not changed under the M2 fence.

**Open for the M2 gate (not code):** the two-machine reporter demo
against the customer Supabase (needs the second machine; M1's live demo
is still open too and shares the setup), and security review #2 (plan
task 6.6).

## D-70 — `deploy/execution-role.sql` shipped broken; the artifact is now executed by tests

**What happened.** The first version of the execution-role provisioning
script contained `GRANT CONNECT ON DATABASE current_database()`, which is
not valid SQL — `GRANT ... ON DATABASE` takes a literal identifier. The
file was written, reviewed, committed, and handed to the operator without
ever being run. The operator hit the error in the Supabase SQL editor and
fixed it with a `DO` block using `format(%I, current_database())`.

**Why the M2 suite did not catch it.** Every other execution test
provisions its roles with inline SQL written in the test — precise, fast,
and completely disconnected from the artifact a human actually runs. The
tests proved the *executor* enforces G3; nothing proved the *file that
creates the role G3 depends on* would execute. The shipped artifact was
the one piece of the checkpoint with no coverage, and it was also the
piece with the highest blast radius, since it runs as a superuser against
the customer's production database.

**Fix (`tests/test_execution_role_sql.py`).** The real file is applied to
a real Postgres through `psql`, with only the documented `<PASSWORD>`
placeholder substituted, and the resulting role is then held to the
executor's own check: it can read business data; it cannot write by any
of five routes driven straight at the driver; its session defaults are
set; later tables created by the provisioning role stay readable; and the
three VERIFY queries the file instructs the operator to run are parsed
back **out of the file** and asserted empty — so the instructions are
tested, not just the statements. Confirmed as a genuine regression test
by restoring the broken `GRANT`: 13 errors before the fix, 13 passes
after.

**The general lesson, recorded because it will recur.** Operator-run
artifacts — provisioning SQL, runbooks, migration scripts, compose files
— are code, and shipping them untested is shipping untested code. The
convenience of writing setup inline in a test is exactly what leaves the
real artifact uncovered. Where a file is meant to be run by a human
against something that matters, a test should run that file.

**Secondary defect, same class (mine).** The `.secrets/wire-exec-dsn.sh`
helper built the DSN by re-encoding an already-encoded password, so a
literal `%` became `%25` and the stored credential silently did not match
the role; it also wrote the value without testing it, so the failure
surfaced two layers later as an opaque `AuthError`. Both are fixed: the
helper now carries the Supabase pooler's tenant suffix (which lives in
the username as `<role>.<project_ref>` and is required by the pooler),
tests the connection *before* writing, and a companion
`reset-exec-password.sh` generates a URL-safe password and writes both
sides from that one value — the two-sided secret is never hand-carried,
which removes the encoding-mismatch class rather than documenting it.

## D-71 — Security review #2 F2/F3 landed: visibility governs execution; introspection gets its own role

Ruling **D-71** (owner, 2026-07-21) disposed of security review #2. This
record closes its **points 1 and 2** — findings **F2** and **F3** — with
tests as the definition of done. Points 3–8 are recorded there and are
not touched here.

**Numbering note.** The ruling was handed down labelled *D-67*, which was
already taken by the security-review-**#1** landing record (also its
F2/F3/F4 — the collision is a genuine hazard, since both entries are
"security review, findings F2/F3"). Renumbered to **D-71** on the owner's
call; the review #1 record keeps D-67 because landed commits and code
comments already point at it. Every reference this work introduced reads
`D-71.1` / `D-71.2`.

### F2 — the visibility map now governs validate_sql and execute_sql

**Spec first, per the fence.** One additive amendment to the MCP tool
reference, in three places: §3 strikes the words "for content tools" from
the per-call decision; §6.6 specifies resolution against the caller's
visible surface; §5 adds the `objects` allow-set to the validation token.
Conformance rows MT-11/MT-12/MT-13 added. No other spec touched.

**The implementation choice that carries the non-disclosure property.**
The visible surface is the *input* to resolution, not a filter over its
output: `valsql.ts` builds the object list handed to `sqlval` from the
objects the caller can see, so a hidden table is refused by the same code
path, with the same `unknown_object` finding, as a table that was never
there. There is no second error message to keep in sync and no branch
that could leak which case occurred. The alternative — resolve against
everything, then reject hits that are hidden — needs the two messages to
stay byte-identical forever, and would have been a plausible way to ship
an enumeration oracle. The same ordering applies to the API dialect and,
importantly, to column resolution: a hidden object's columns are hidden
with it, so no column check can confirm a hidden object's shape.

The true reason is recovered afterwards, server-side only, by asking
whether a refused ref resolves in the *full* snapshot. That feeds the
audit record (`decision: filtered`, `hidden_objects`) and nothing else —
M-4's second half, the one that keeps this debuggable for a steward while
opaque to the caller.

**Carrying the decision to execute, and which check catches what.** The
token now carries `objects`, the allow-set validation resolved against,
and `execute_sql` re-checks every member against the caller's *current*
scopes before enqueue. This is not redundant with the `snapshot_ref` pin
and does not overlap it: `snapshot_ref` pins the **facts** surface, and
visibility is not in the snapshot — the map lives in the KB at `kb_ref`.
A revocation therefore moves no snapshot, advances no `snapshot_ref`, and
a token minted a moment earlier verifies against every other §5 binding
cleanly. **The allow-set recheck is the only mechanism that catches a
mid-token visibility change.** MT-13 asserts exactly that, and asserts
the snapshot rows are unchanged across the case so the claim cannot be
satisfied accidentally by the pin.

Refusal at execute is `not_found` with validation's wording, not
`revalidate_required` — holding a token must not become a way to learn
that an object exists. It is built without the module's `fail()` helper,
which copies its extras into the caller-visible `detail` as well as the
audit `meta`; the hidden FQNs go to the audit only. A token with no
`objects` claim is refused (`revalidate_required`) rather than trusted:
fail-closed, bounded by the 300 s TTL to one re-validation.

*Tests* (`core/test/mcp-visibility.test.ts`, 12): hidden-table SELECT
refused with no token; **the hidden and the absent responses compared
field-by-field after normalising the object name**, which is the actual
property rather than a proxy for it; the identical statement passing for
a steward; a JOIN with one hidden side refused, asserting the visible
side is not mentioned at all; a hidden GA4 custom dimension refused in
the same words an undocumented one gets; both audited as `filtered` with
the true reason; the mid-token revocation case above; a still-visible
statement getting *past* the check (so the case above is not a blanket
refusal); and the missing-allow-set token refused. Confirmed as genuine
regression tests by mutation: disabling the surface filter fails 6 of 12,
disabling the allow-set recheck fails MT-13 alone.

### F3 — introspection moves to `contextlayer_introspect`

`deploy/introspection-role.sql` provisions LOGIN + CONNECT + USAGE on the
introspected schemas and **no SELECT on anything**, with none of the four
role attributes. That looks too narrow until the reason lands: the
connector reads `pg_catalog` only, and `pg_catalog` is world-readable and
*not* privilege-filtered — so the role reads the full shape of the estate
and the contents of none of it. That asymmetry is also why the swap is
snapshot-neutral: the catalog answers the same regardless of who asks.

`check_introspection_role` refuses SUPERUSER or BYPASSRLS at the start of
every **live** snapshot job (not ddl-file mode — that container is ours
and applying customer DDL requires the superuser the check would refuse).
Failing the whole job is correct under S-6.

**A fact worth recording, measured rather than assumed.** The review
described the pilot's `postgres` as superuser-class. It is not: on
Supabase `rolsuper = false`, while `rolcreatedb`, `rolcreaterole` and
**`rolbypassrls`** are all true. A check written to look only for
SUPERUSER — the obvious way to write it — would have passed the exact
connection F3 was filed about. Both attributes are tested for that
reason, and it is BYPASSRLS that actually fires on the pilot.

*Tests.* `tests/test_introspection_role_sql.py` (15) applies the real
file through `psql` per D-70 and holds it to both claims: introspection
through the provisioned role is **byte-identical** to introspection as
the container superuser on the same database, and all four read paths
raise `InsufficientPrivilege`. The file's own VERIFY queries are parsed
back out of it and asserted empty. Controls: a superuser connection and a
BYPASSRLS-only role are each refused.

Beyond the new file, the connector's own live-mode fixtures now run
through this role (`tests/test_postgres_connector.py`), which upgrades
**C-3 mode invariance** into direct evidence for the swap: ddl-file mode
introspects as superuser, live mode as a role with no table privileges,
and the canonical bodies must still match byte for byte. Provisioning
goes through one shared helper that runs the shipped artifact — there is
no test-only variant of this role.

**Config swap.** `env://SUPABASE_DSN` → `env://CL_INTROSPECT_DSN` in the
example job and connection registrations and in the onboarding skill. The
rename is the point, not cosmetics: the old name said which *database* it
reached while the value behind it was the estate's BYPASSRLS role, and
renaming forces the operator to set a new variable to a new credential
rather than leave the old one in place under a name that no longer
describes it.

**Not done, and why.** The live example swap is unfinished: applying
`introspection-role.sql` is DDL against the customer estate and is the
operator's to run, never ours. The pilot is wired and **fails closed**
today — verified end-to-end through the real CLI, which now exits
`config_error` naming the file to run. The byte-identity comparison is
pre-loaded for that moment: baseline `canonical_body_sha256 =
6fcfc976ce104e33ca56a16670d78e57ab44950bdf6ee4b106dad8c20ce3463c` (29
objects, last pull under `postgres`, 2026-07-20T21:24:54Z), recorded in
`.secrets/connections.md` with the two remaining steps. This is D-71
point 8(c), already named there as an M2 sign-off condition.

*Suites at landing:* Python 486 passed / 13 skipped; core 140 passed
across 14 files (MT, FL, SO, drill, JP-2); `tsc --noEmit` clean.

## D-72 — Task 6.1 accepted; playbook deploy-gate amendment authorized

Ruling **D-72** (owner, 2026-07-21) accepted the D-71 points 1–2 build,
authorized one additive playbook amendment, and filed the pairing motion.

**1. Renumbering affirmed.** Review #1's landing record keeps **D-67**;
the review-#2 dispositions ruling is **D-71** everywhere, including in
the owner's own prior references.

**2. F2 accepted as landed** — the resolution-input design and the
allow-set answer for mid-token revocation both, the latter noted as
consistent with MCP-R1's per-call re-resolution (roles are resolved from
the token on every call and never session-cached; the allow-set recheck
is that same principle reaching the objects a token authorized rather
than the identity holding it). MT-13 plus the mutation evidence are
recorded as the property's tests: disabling the surface filter fails 6 of
12 in `mcp-visibility.test.ts`, disabling the recheck fails MT-13 alone.

*Design rationale recorded at the owner's instruction — the `fail()`
near-miss.* The first draft of the execute-side refusal was built with
`execute.ts`'s local `fail()` helper, which spreads its `extra` argument
into **both** `meta` (the audit record) and `detail` (the caller-visible
error payload). Passing the hidden FQNs through it would have shipped, in
the one refusal whose entire purpose is non-disclosure, a response naming
exactly what was hidden and why. Caught before it ran, but it is worth
recording *why* it was easy to write: the helper's two sinks are a
convenience that reads as one, and every prior refusal in that function
wanted both. The shipped refusal is constructed inline for that reason,
with a comment saying so at the call site. **General shape:** a helper
that fans one input out to an internal sink and an external sink is
comfortable until the first value that may only reach one of them —
non-disclosure paths should not use fan-out helpers.

**3. F3 accepted as landed:** the dual-attribute startup check
(`rolsuper`, `rolbypassrls`), the catalog-only introspection role, and
C-3 mode invariance upgraded from a determinism check into evidence for
the swap (ddl-file as superuser vs live as a role with no table
privileges, canonical bodies byte-identical).

**4. Playbook amendment authorized (additive) — applied here.**
`customer-onboarding-playbook.md` §13 gains gate item 9: three
role/credential assertions — `example_exec` read-only at the
database level, `contextlayer_introspect` neither SUPERUSER nor
BYPASSRLS, and the `contextlayer-sync` PAT fine-grained/single-repo/
contents+PR-write-only (P-H, D-66.7) — as three distinct identities with
distinct secrets, none of them the estate's default `postgres`. The
item's closing note makes the Supabase finding normative guidance:
**check attributes, not role names**, because `rolsuper = false` alongside
`rolbypassrls = true` is a real configuration and a name-based check
passes exactly the connection the item exists to catch. Draft text from
`PR-D71-F2-F3.md` adopted; spec diff leads its own PR
(`PR-D72-PLAYBOOK-GATE.md`). No other spec touched.

**5. Pairing motion filed** as playbook register item **OB-5**: a profile
granting `execute_sql` must be paired with a database role scoped no
wider than that profile's visible surface. Stated as a deployment
obligation, not yet a mechanical gate item — D-71.1 made the KB map
govern the execution surface, but the map is the gate and the database
role is the wall, and nothing checks that the wall matches the gate.
Wording at the next playbook revision; **load-bearing at the first
customer with more than one execute-granted profile**, which is the first
point at which the two surfaces can diverge.

**6. M2 sign-off conditions restated.** (a) The two flagged spec
contradictions pasted back for ruling — **still outstanding**, and the
only one of the three that is neither landed nor an operator action; the
items are D-69 interpretive rulings 12 (fault-ledger §5 self-contradiction
on `schema_mismatch_at_execute`) and 13 (`statement_class` proposed as an
additive capability §6 code). (b) Task 6.1 landed — **cleared** by D-71
points 1–2. (c) Introspection role swapped live with byte-identity
verified — **on the owner**; the pilot fails closed until then, and the
baseline hash is recorded in `.secrets/connections.md`.

---

# DECISIONS — CP-5 (the loop closes): shipped skills + baseline v1

## D-74 — CP-5 premise resolution: branch, integration debt, condition realization

**Numbering note:** D-73 is unallocated. The owner's ruling arrived
labelled D-74 and is recorded under that number rather than renumbered —
a gap in the sequence is cheaper than a label that disagrees with the
ruling it records.

**1. The premise did not hold on `cp4-m1-mcp`.** CP-5's deliverables 4, 6
and 7 build on the CP-2 harness. That harness had never left
`task/2-benchmark-harness`: neither `main` nor `cp4-m1-mcp` carried
`benchmark/`, `benchmark/suite/benchmark-seed-v0.yaml`, the eleven
`tests/test_benchmark_*.py` modules, or **ruling D-62** — the CP-2 gate
amendment that defers baseline v1 into CP-5 and is the authority for
CP-5's added exit criterion. On `cp4-m1-mcp` the plan still listed the
baseline under task 2.3 at CP-2, and the register's MC-1 trigger still
read without its CP-5 re-point. What made this hard to see from the
working tree: `benchmark/` existed on disk containing **only a stale
`__pycache__/`** left by an earlier checkout of that branch, so the
directory looked present while `git ls-files benchmark` was empty.

Flagged rather than patched, per the CP-5 fence. Resolution accepted:
`cp5-skills` cut from `cp4-m1-mcp`, `task/2-benchmark-harness` merged in.
Six conflicts, all append-shaped, resolved as unions; CI keeps the `core`
job and gains `benchmark-integrity` (R7); `DECISIONS.md`'s CP-2 records
(D-50..D-62) reordered ahead of D-63..D-72 so the file runs in number
order.

**The fence is now verifiable and holds.** `benchmark/`,
`tests/test_benchmark_*.py` and `results/` diff clean against
`task/2-benchmark-harness` — harness code is byte-identical, not merely
believed unchanged. Suites green post-merge: 588 Python (486 + 102
benchmark), 140 core, R7 integrity GREEN.

**2. Integration debt — standing convention (process ruling).** At CP-5
completion `cp5-skills` PRs to `main`, and `main` becomes current through
M2 + CP-5 in one reviewed landing. From then on: **every checkpoint
sign-off includes its branch landing on `main` — a checkpoint is not
closed while its work is unmerged.** The plan's gate definitions read
accordingly (§1, "The checkpoint model").

The convention exists because of what point 1 cost. Five task branches
had accumulated unmerged; the CP-2 work sat unmerged for the whole of
CP-3/CP-4/CP-6 and was silently absent from the branch that depended on
it. The failure mode is not lost work — it is a *premise* believed true
because the work was done, when the branch doing the depending never
received it.

**3. Uncommitted D-71/D-72 work committed** (`6041bb9`, `e5910c5`) as a
precondition of the merge — `DECISIONS.md` was the one dirty file the
merge touched. Affirmed by the owner as the correct call on the evidence
(finished PR bodies, both suites green, described as live in the task
premise). `DECISIONS.md`'s addition covers both rulings and rides in the
D-71 commit rather than being split across the two: interactive staging
is unavailable in this environment. **Accepted as-is by ruling — history
purity is not load-bearing; the DECISIONS text is.**

**4. Condition realization (deliverable 5).** The three benchmark
conditions are realized as **three dev-core instances**, one per
condition, each pointed at a different KB remote, with the profile fixing
the tool surface. R2 holds: identical journey prompt, identical execution
access, context access the only difference.

The load-bearing correction to the owner's sketch: the varying axis must
be the **core instance**, not the profile. `kb_ref` is per-instance
config (`SYNC_GIT_REMOTE`, `core/src/config.ts`), not a profile field, so
three profiles against one core would all resolve against the same KB and
the conditions would be indistinguishable — the experiment would report a
difference it never actually created.

| Condition | KB the instance serves | Tool surface |
|---|---|---|
| `enriched-kb` | customer KB clone at pinned `kb_ref` | full read set + validate + execute |
| `machine-kb` | `benchmark.conditions` render (deterministic, byte-stable → keys cleanly under R8) pushed to a scratch repo | full read set + validate + execute |
| `no-kb` | scratch repo containing **only the profile files** | validate + execute only |

Three additions by ruling:

- **(a) `no-kb` spans all three systems.** The seed suite has GA4 and GSC
  cases, and CP-2's R1 defined no-kb discovery as `information_schema` +
  the GA4 metadata endpoint + GSC's fixed schema. Grant validate/execute
  for supabase, ga4 *and* gsc — a supabase-only grant would score the
  GA4/GSC cases as failures of the condition rather than of the KB.
- **(b) Visibility must be verified permissive for `no-kb`.** D-71.1 made
  `validate_sql` visibility-governed. A default-hidden visibility map
  would refuse every statement and **silently destroy the condition** —
  it would look like a no-kb agent that cannot write valid SQL, which is
  exactly the headline finding the baseline is meant to produce honestly.
  Guarded by a fixture test: the no-kb profile validates a statement
  against a example estate table successfully.
- **(c) The `no-kb` instance's KB carries no content.** The tool surface
  already prevents content reads; pointing the instance at content it
  must not serve is a second thing that has to stay true. Defense in
  depth, and it makes the R8 condition keying honest.

**5. Baseline spend gated.** Return before the baseline run with: smoke
journey evidence (one case, one condition), on-subscription billing
verified per the preflight (`ANTHROPIC_API_KEY` unset, auth route
checked), the pinned model id, and the three instances' R8 keys
(`kb_ref` / render hash / profile) for the owner's check.

## D-78 — AS-9/10/12 conformance layering; the falsifiability rule

**The question.** The three CP-5 conformance items (AS-9 gap-vs-guess,
AS-10 contamination reaching the artifact, AS-12 CP-E4 front-matter) all
assert on what an agent *did*. They could be built as rule validators
over staged artifacts — cheap, deterministic, CI-resident — or as
behavioral scenarios against a fixture deployment, which is what
skill-spec SK-1 ("verified behaviorally through the audit stream") and §9
("executed against a fixture deployment") actually specify.

**Ruling: both, layered.** (a) Validators ship as CI-resident regression
tests over staged good/bad artifacts; they pin the rules cheaply and
permanently. (b) The three behavioral scenarios run against the fixture
deployment — fixture KB, fixture snapshots, stub connectors — asserting
on the audit stream and the resulting files. **(b), not (a), is the
AS-9/10/12 conformance evidence for the CP-5 gate.**

**The standing rule this establishes** — general, not CP-5-local, and
recorded alongside the fan-out-helper rule above:

> **A conformance item may only be reported green on evidence that could
> have failed if the behavior were absent.**

Validators over staged artifacts cannot fail when the skill misbehaves:
the fixtures are hand-written, so the test would stay green if the enrich
skill never wrote a purpose in its life. It tests the checker, not the
skill. Reporting such a suite as "AS-9/10/12 green" would claim
behavioral conformance that was never observed — the failure is not a
weak test but a **false claim about what was verified**.

The same principle, wearing different clothes, is why the CP-5 benchmark
driver refuses to synthesize a journey record when the skill emitted
none (deliverable 4): a fabricated record would be ingested and scored as
though a real journey happened, and the resulting number would look
exactly like a real one. Evidence that cannot fail, and evidence that was
manufactured, are the same defect at different points in the pipeline.

**Re-runnability.** The scenarios ship as an invocable target against the
fixture deployment, with their journey records and audit extracts
committed as gate evidence. Re-run on any skill edit — cheap enough to be
the norm, since the fixture deployment needs no example estate and no
credentials. CI marks them gate-evidence tests, not per-commit tests.

**Sequencing** (correcting D-76.4's "in parallel", which was wrong on the
spec): fixture deployment → three scenarios → rig prep per D-76.3 →
smoke journey → packet. The scenarios precede the baseline instances and
need neither pilot credentials nor the scratch repos.

## D-79 — CP-5 behavioral scenarios accepted; fixture reporter refreshed

**Gate evidence accepted.** The AS-9/10/12 behavioral scenarios (D-78
layer (b)) are the CP-5 conformance evidence: real skills in real headless
Claude Code sessions against the standalone fixture deployment, asserting
on the audit stream and produced files. Both journeys pass under
`claude-opus-4-8`; the agent-produced `enrich-orders.md` and
`report-artifact.json` are committed verbatim under `results/cp5-scenarios/`.

**The falsifiability demonstration D-78.2 required is on record, observed
not presumed.** The AS-10 journey *failed* on its first run: the profile
in use exposed no `execute_sql`, the loop stopped at validation, and the
"validated and executed" assertion went red. The suite has now been seen
to discriminate — a conformance item reported green because its assertion
could, and once did, fail. This is the general rule from D-78 made
concrete: evidence that cannot fail cannot green an item.

**Fixture reporter refreshed to the product shape (D-79.2).** The first
AS-10 pass ran under the steward profile, because the fixture's reporter
was frozen at its M1 read+validate shape while the product Reporter gained
`execute_sql` at CP-6/M2. Accepted for that run (AS-10 asserts disclosure
reaching the artifact, not profile identity), but the root cause was
fixed: `REPORTER_PROFILE` now carries `execute_sql:drill`, `REPORTER_TOOLS`
gains `execute_sql`, and the stale MT-3 assertion ("execute never runs at
M1 — profile-denied for reporters") was rewritten to the CP-6 reality (the
reporter passes the profile gate; token binding still turns away a
non-matching request). AS-10 re-run under the refreshed reporter: pass.

**Watch-note filed (register-style, home: skill spec / test fixtures):**
*fixture profiles must track product profiles.* Silent divergence makes
scenario evidence quietly weaker — a scenario can pass against a profile
the product no longer ships, and nobody is told. There is no mechanism
today that fails when a fixture profile drifts from its KB counterpart;
until there is, the coupling is a review responsibility.

**Two fixture-side choices, both accepted (D-79.2/3).** The report
scenario seeds the reporting-view chain (`v_order_totals` → `v_net_sales`)
so execution returns real rows rather than a `schema_mismatch`; the
seeding is fixture-side only. And `helpers.ts` loads vitest `inject`
lazily (gated on `CORE_TEST_DATABASE_URL`) so the module also loads
outside vitest under vite-node for the standalone launcher — vitest path
unchanged, suite green.

## D-80 — CP-5 closure by amendment + CP-7 entry (owner ruling)

**1. BASELINE v1 SKIPPED by explicit decision.** CP-5's gate is amended:
deliverable 6 removed; gate evidence = the AS-9/10/12 behavioral
scenarios + the smoke journey (full-loop proof, RB-01 enriched).
Consequences recorded, not relitigated: the three-condition comparison
remains unmeasured; MC-1's trigger ("recall is the accuracy bottleneck")
cannot be evaluated and stays open; the standing constraint from the
CP-2 deferral PERSISTS — **no quantitative KB-value claims in any
customer or demo material until a baseline exists.** Register item
BASELINE-1 filed (master register, plan-level section; home ruling =
this entry): full baseline via the benchmark skill; trigger: before CP-8
go/no-go, or before the first external customer conversation that would
benefit from numbers, whichever first. The built rig makes this cheap to
revive (driver + preflight + conditions all landed and re-runnable).

**2. RISK ACCEPTANCES recorded, owner: AlperCamli.** (a) Customer KB
remains public by choice — owner's own data, confidentiality waived;
revisit before any real second customer. (b) Leaked exec DSN +
service-account key: rotation deferred; trigger: before CP-8 sign-off or
any non-localhost exposure of the estate, whichever first.

**3. EMPTY-TABLE CAUSE CONFIRMED:** RLS on base tables; example_exec
correctly lacks BYPASSRLS. The CP-6 "reporting views over RLS" decision
is activated as CP-7 task 7.0 (views drafted by the session, applied by
the owner as customer DBA).

**4. CP-5 CLOSES on:** rig + both `cl-baseline-*` scratch repos torn
down; AS-10 re-run under the refreshed execute-granted reporter
(D-79.2); `cp5-skills` landed on `main` per the D-74.2 convention.

**5. CP-7 ENTRY CONDITION:** task 7.0 views applied and flowing through
the product path (snapshot → additive drift PR → merged) before the
publisher demo depends on them.

**Execution record (2026-07-24):**
- AS-10 re-run: already on record as pass under the refreshed reporter
  (D-79) — nothing further to run.
- Baseline rig: no `compose.baseline` containers or volumes remain on
  the pilot machine (`cl-fixture-pg` stays — it is the fixture
  deployment, gate-evidence infrastructure per D-78, not the rig).
- Scratch repos: **pending one operator action.** The `gh` token lacks
  the `delete_repo` scope and the refresh flow is interactive. Owner
  runbook: `gh auth refresh -h github.com -s delete_repo` then
  `gh repo delete AlperCamli/cl-baseline-machine-kb --yes` and
  `gh repo delete AlperCamli/cl-baseline-nokb --yes`.
- `cp5-skills` landed on `main`: merge `48ea11c` (no-ff), main current
  through M2 + CP-5 in one landing.
- BASELINE-1 added to the master register; MC-1's revisit trigger
  re-pointed at it (was "Baseline v1 … CP-5 per D-62", which D-80.1
  amends away).

## D-81 — Task 7.0: reporting views scoped to the seed packet; security model ruled

**Ruling (owner, 2026-07-24): definer + barrier.** The task 7.0 views
declare `WITH (security_invoker = false, security_barrier = true)`.
Definer because it is the mechanism: a view evaluates RLS as its owner
(`postgres` — which on the pilot both holds BYPASSRLS, the measured
D-71/F3 fact (`rolsuper = false`, `rolbypassrls = true`), and owns the
base tables, so the exemption holds twice over), which is the entire
point of the file — the reviewed view text is the access policy,
aggregates-only columns are the containment. Invoker was rejected on
two grounds: RLS would evaluate as `example_exec` (`auth.uid()`
NULL → zero rows from every view, reproducing exactly the emptiness
D-80.3 diagnosed), and making invoker work would require base-table
SELECT grants plus permissive policies for the exec role — the grant
the CP-7 scope fence forbids outright. `security_barrier` fences
non-leakproof predicate pushdown below the aggregation; cost is nil at
this scale. The ruling retroactively names the model the twelve CP-6
views already use (default definer); they are left byte-untouched.
Expected side effect, accepted: Supabase's advisor flags every view in
`reporting` as "security definer view" — that flag is this design,
not a finding.

**Scope (— no broader).** Five views close exactly what
`benchmark-seed-v0` needs and the CP-6 twelve cannot serve:
`v_user_signups_by_day` (RB-01, the smoke-journey case; RB-05 stage 4),
`v_job_status_transitions` (RB-06; raw NULL from_status, actor column
deliberately unexposed), `v_subscriptions_new_by_month` (RB-08 Supabase
leg), `v_ai_runs_by_day` (RB-09 — status kept a *dimension* because its
vocabulary is ungrounded text; baking in `status = 'failed'` would
hardcode the value the KB cannot confirm), and
`v_activation_funnel_monthly` (RB-07 — the one view that row-joins
inside, which is precisely why it must be a view;
`count(*) FILTER (WHERE EXISTS …)` ≡ the golden's
`count(DISTINCT user_id)` over a cohort join). RB-02 and RB-10 already
resolve through `v_subscriptions_by_plan`, recorded in the file. The
plan's other scoping input, certified metrics, contributes nothing:
the KB has no `metrics/` catalog (the benchmark's recorded KB defect
stands — a candidate for the post-sync enrichment pass, not for DDL).
New buckets pin UTC explicitly (`(col AT TIME ZONE 'UTC')::date`),
putting the goldens' semantics in the SQL text rather than the server
TimeZone setting.

**Also under this entry.** (a) The shipped guard query was
newline-poisoned: its identifying-column pattern was split across
comment lines, embedding literal newlines that disarmed every branch
after `full_name`. Fixed to a single-line pattern; the file says so.
(b) `tests/test_reporting_views_sql.py` extended: the miniature estate
gains `job_status_history` (RLS keyed on the acting user) and the
base-table read-denial loop covers it; a new lineage-parse test feeds
every reporting view through `lineage.parser.snapshot_attestations`
exactly as the connector will carry it (`pg_get_viewdef(oid, true)`,
empty search_path, D-19.2) and asserts each task 7.0 view attests
exactly its base tables, all resolved — guarding the D-41 all-or-nothing
graph build the product-path sync depends on. Suite 8/8.
**Boundary unchanged:** the owner applies the DDL as customer DBA (we
never run DDL against the customer estate); `example_exec` gains
SELECT on views only; no default privileges exist in `reporting`, so a
future view is exposed only by deliberately re-running the grant.

## D-82 — Platform repo commits directly to main (owner ruling, 2026-07-24)

The platform repo is local-git-only — no remote, no PR machinery — so
the branch-and-land convention collapses: work commits to `main` at the
latest version, small reviewable commits in place of PRs. What D-74.2
protected ("a checkpoint is not closed while its work is unmerged") is
preserved trivially, since work is always on `main`; checkpoint
sign-off still requires green suites at the sign-off commit. The KB
repo is unchanged: PRs + KB CI + code-owner review remain (it has the
remote and the enforcement). `cp7-m3` fast-forwarded into `main`
(`15f7b72`) and deleted under this ruling.

## D-83 — CP-7 publisher build decisions (M3, 2026-07-24)

Publisher capability + Looker Studio template-link adapter +
`publish_report` + report-skill S7, built per capability §8, formats
§4/§4.6, MCP §6.8. The decisions that were genuinely mine to make, on
record:

**1. Publish payload members are first-class `Job` fields** (`artifact`,
`target`) — additive on the SDK dataclass and the service's payload
mapping, mirroring how `execute` carries `request`/`guardrails`.

**2. Template-link "created" identity.** In template_link mode nothing
exists at Google until a human clicks, so `created[0]` is
`{type: "template_link", id: "tl-<sha256(artifact.id ‖ target)[:16]>", url}` —
deterministic, stable per (artifact.id, target) (PB-2), revision-blind
(a revised artifact updates the same identity, F-5). The F-4 report
node is `<target>.report.<that id>`: it represents the published link
artifact, the only stable object this platform tier yields. Honest,
recorded, revisit if a full-mode adapter arrives.

**3. Linking API parameter names are pinned in one table**
(`connectors/looker_studio/publisher.py _SOURCE_PARAMS`), from the
published Linking API docs. They are externally owned facts; the live
M3 gate verifies them by opening a real link, and a drifted name
degrades softly — the human completes that field in the Looker UI,
which template_link journeys already require (PB-3 steps say so).

**4. MT-10 carries a certification-honesty check:** an artifact
claiming `certified: true` against a doc whose status is not
`verified` is refused (`config_error`). Reading of MT-10's "may not
cite context that doesn't exist" — certification the KB never granted
is exactly such a citation.

**5. Undocumented-blend-key ledger path.** The server refuses with the
actionable error naming the entity doc and its documented keys; the
LEDGER entry arrives via the report skill's
`flag_gap(kind: missing_join_path)` (SKILL.md S7.4), class-2 provenance
honest — the server does not synthesize a class-2 event no agent
filed, and no new class-1 rule is invented (the CP-7 fence: existing
classes only). `guardrail_pattern`'s sweep now also reads
`publish_report` audit rows — same rule, honest inclusion.

**6. F-7 re-validation is token-less** (`validateRequest`
`issueToken: false`): a publish re-validates every query against the
caller's visible surface but never mints an execution right.

**7. Publish responses are §8.2-verbatim plus additive envelope
fields:** `artifact: {id, revision, content_hash}` (so the skill can
cite the server-assigned revision) and the house `refs` envelope.

**8. Graph-only drift runs.** Gateway attestations pending with no
snapshot change lift the pipeline's no-op short-circuit and run the
lineage stage alone — F-4 nodes land as their own KB PR. `graph.json`
gains an additive `inputs` entry `{kind: "gateway", attestations: N}`;
report nodes are `resolved: true` with no `doc` (the `_node` doc path
now keys on schema presence). Determinism: the attestation export is
ordered, `generated_at` stays a function of snapshots alone (FG-1
re-asserted by test).

**FM-2 note (which visual kinds the shipped template exercises):** the
mechanism is config-declared — `template_visual_kinds` on the
connection is what the adapter enforces substitutions against (PB-4).
The pilot template should exercise all five registry kinds (the seed
slate needs: line RB-01/09, pivot RB-02/06 (+RB-04), table RB-03, bar
RB-05, scorecard RB-08/10; RB-07's `other:funnel` maps to bar/pivot
with a recorded substitution). To be filled with the template's actual
id + kinds at operator template creation; the deploy example
(`deploy/jobs/live-example/looker-studio-connection.json`) declares all
five as the target state.

**Rollout state:** product reporter profile grant = KB PR #23 (steward
merges); fixture reporter already tracks it (D-79 watch-note). Suites
at this entry: python 578 passed (+13 env-gated skips; docker-gated
postgres suites deselected, run separately and green incl.
`test_reporting_views_sql.py` 8/8), TS 167 passed across 17 files.

## D-84 — Drift PR #25, rotation trigger honored, compose precedence (owner ruling, 2026-07-27)

Task 7.0's product path completed and the M3 prerequisites re-verified
after a step-0 check found two of four claimed-done items untrue: the
additive views drift PR had never been opened, and the `looker_studio`
connection had never been registered. Both are now real. What was
already true: the five views applied with `security_invoker = false,
security_barrier = true` and `example_exec` holding SELECT on all
five (D-81 as ruled), and KB PR #23 merged (`reporter` carries
`publish_report:looker_studio` — confirmed live in the running server's
reporter toolset).

**1. ROTATION: D-80.2(b)'s trigger fired and was honored.** Part B's
second-machine reporter session is non-localhost exposure of the estate,
which is the stated trigger; deferral conditions that fire get honored,
which is what makes a recorded risk acceptance mean anything. Chain:
trigger fired → `reset-exec-password.sh` generated a fresh
URL-safe password and wrote both sides from the one value → owner
applied `ALTER ROLE example_exec PASSWORD …` in the Supabase SQL
editor as customer DBA (we never run DDL/DCL against the estate) →
agent re-wired `.secrets/runner.env` from `env.sh` and recreated the
runner → **verified**: startup preflight `role=example_exec
engine_version=17.6`, then one governed execute through
`reporting.v_subscriptions_by_plan` returning 3 real rows
(`source.role = example_exec`, `executed_on = primary`,
`truncated = false`), audited under the reporter identity. The
service-account key half (GSC/GA4) is the owner's console recycle and
is **pending** at this entry; it does not gate the exec path.

**Also verified along the way (D-80.3's emptiness is genuinely gone):**
governed execution through a reporting view returns real rows, live, on
the example estate. That is the fact M2 could not demonstrate.

**2. COMPOSE PRECEDENCE, fixed.** `docker-compose.yml` declares the sync
vars under `environment:` as `${SYNC_*:-}`, and compose ranks
`environment:` above the live overlay's `env_file:` — so a populated
`.secrets/sync.env` that is not *exported* yields `SYNC_ENABLED=0` and
a stack that is healthy and silently never syncs. Measured consequence:
the pilot ran that way for two days; the 2026-07-25 snapshot
(`d4908bbb…`, taken after the DDL apply) was accepted and never became
a PR. `make stack-live` now sources the file itself and passes
`SYNC_PLATFORM_COMMIT=$(git rev-parse HEAD)` for §10 provenance;
`CORE_MCP_ENABLED=1 make stack-live` arms /mcp on top.
**Register motion filed, no build:** sync spec §13 **SO-F** —
configured-but-disabled sync is silent in single-instance ops;
`/healthz` already reports `sync_enabled`, the gap is that nothing
consumes it where there is no dashboard. (Noted, not fixed: the master
register has no SO-* section at all — SO-A..E were never carried over
at consolidation.)

**3. SUPERSEDE (SY-3) observed in production.** Arming sync fired a
scheduled tick that opened PR #24; the manual `sync now supabase`
trigger raced it and its run superseded #24 — auto-closed with the
successor link, PR #25 open. One metadata-only delta between the two
(`files.schema.md` row_estimate churn). SO-7's behavior, unrehearsed,
on a real remote.

**Drift PR #25 content, verified:** "0 breaking, 5 additive across
supabase", label `sync:additive-only`, `REVIEW_REQUIRED`, KB CI **pass**,
not merged (SO-B: the product never merges). Five `*.schema.md` machine
docs with view definitions and `status: machine`; `lineage/graph.json`
22→28 nodes, 16→25 edges, every view a `resolved: true` node pointing at
its doc with edges parsed from the view definitions at `trust:
sql-parse` — `v_activation_funnel_monthly` fanning in on all five of its
bases with composite column maps. The pre-existing unresolved
`supabase.` external node predates this run (it is in the CP-6 graph on
`main`).

**4. INTROSPECTION SWAP (F3 / D-71.2) verified cleared.** Measured
`contextlayer_introspect`: `rolsuper=f`, `rolbypassrls=f`. The stale
"PENDING OPERATOR ACTION" comments in `.secrets/env.sh` and
`.secrets/connections.md` are removed. The runbook's demanded
comparison is done, with the confound named: the first introspect-role
pull post-dates the DDL, so whole-body hashes cannot be compared —
per-object comparison instead shows all **29** pre-existing objects
byte-identical by `schema_hash` and the only delta being the five new
views. The swap changed nothing we can see.

**5. WHEEL: A.3 not triggered, with a reason.** Carry is version-keyed
and both sides are 0.5.0. `snapshot/` and `generator/` are byte-
unchanged since the vendored commit `ce8c646`; only `lineage/` moved
(bbaf5d7), and KB CI runs `generator.validate`, which never reads
`lineage/graph.json`. So the vendored wheel is honestly current for what
CI does — including for part B's graph-only PR, which will not re-raise
this.

## D-85 — Execute result value encoding + runner job isolation (owner ruling, 2026-07-27)

Found by the first governed query through a task 7.0 view: a `date`
reached the SDK's secret-scrubber, `json.dumps` raised, and the **runner
process died** — every job queued behind it then hung to lease expiry.
Four of the five task 7.0 views return date buckets, so the M3 gate
demo would have hit it on essentially every seed case. It stayed hidden
for two checkpoints because RLS emptiness meant no row value ever
reached the serializer; fixing the views is what exposed it.

**Amendment (authorized, additive):** capability spec §6 gains **QE-5**
(the value-encoding table, normative for *every* QueryExecutor) and
**QE-6** (serialization failure semantics). Also touched, and called out
rather than buried: two rows in the same spec's §11 conformance table
(CC-12, CC-13) — the table is where "definition of done" is stated, and
the ruling asked for the coverage. Nothing else in `specs/` changed.

**1. ENCODING** as ruled: temporal → ISO-8601/RFC3339 text; numeric →
string, never float; int/float/bool native, with out-of-safe-range
integers taking the string treatment under the same fidelity rule;
uuid → string; bytea → base64; json/jsonb native; arrays and unmapped
types → the source's text rendering, never dropped and never a crash.
`columns[].type` still carries the source-native name, so no string is
ambiguous about what it encodes.

Two implementation notes worth recording, both inside the ruling:
(a) **Non-finite floats** (`NaN`, `Infinity`) become text. They have no
JSON literal, and `json.dumps` would otherwise emit tokens the core's
`JSON.parse` rejects — text keeps the value *and* keeps the result
parseable, which is the same fidelity rule the numeric row states.
(b) **"The source's text rendering" had to be written out for two
Postgres types**, because psycopg parses them into Python objects whose
`str()` is Python's rendering, not the source's: arrays (`{a,"b,c",NULL}`,
quoting and all) and intervals (`1 day 02:03:04`, not
`1 day, 2:03:04`). Engine-specific rendering lives in the connector,
which knows the column type; the SDK holds the mapping. A `jsonb` array
and an `int[]` both arrive as Python lists and are told apart by the
column type — jsonb passes through as native JSON, the array renders.

**2. FAILURE SEMANTICS:** job protocol §6.7 already had the slot, so no
new capability code and no second amendment — `internal`, retryable,
message carrying the exception *type* only (a value that failed to
encode is exactly the value not to put in an error string, JC-8).

**3. RUNNER JOB ISOLATION — the actual defect.** `result.to_json()` sat
*outside* `_run_execute`'s try block, so an encoding failure bypassed
the taxonomy mapping, killed the worker thread, and left the delivery
path to take the process down. Fixed at three depths: serialization
guarded inside `_run_execute` (and `_run_publish`, same shape), a
job-level `except` in `Runner.execute` that fails the job rather than
the runner, and a last-line guard in `run_forever`. The SDK's stated
obligation in job §6.7 ("the SDK maps exceptions to this taxonomy") is
now true rather than aspirational.

**4. CONFORMANCE.** **CC-12**: a fixture view holding one column per
QE-5 row — every mapping asserted against real Postgres types, on the
executor's own output rather than through the boundary net, plus a
`json.dumps` of the whole result. **CC-13**: a poisoned job (a value
whose rendering raises) fails `internal`, the runner survives, and the
next job on the same runner completes — driven through the real
`run_forever` loop, not a unit stub. GA4/GSC executors **verified, not
assumed**: both build rows from parsed-JSON scalars, so they are
conformant by construction, and `ExecuteResult.to_json` now enforces
QE-5 at the boundary for any executor that forgets.

**Live re-verification (the point of all of it):**
`reporting.v_user_signups_by_day` through the full governed path —
`signup_day` as `"2026-07-23"` with `columns[].type = "date"`,
`role = example_exec`, real rows; and the row-joining
`v_activation_funnel_monthly` likewise (`cohort_month` `"2026-07-01"`,
9 signed up / 6 master CVs / 0 subscribed). Runner alive after both.

**5. FORWARD NOTE for BASELINE-1:** this encoding is now normative for
result canonicalization. When the deferred baseline runs, R5 golden
comparison must canonicalize under QE-5 — numerics as strings, dates as
ISO text — and the frozen `verified_results` may need one re-execution
pass. Recorded here so the mismatch surprises no one; the register row
itself is untouched (no ruling to edit it).

**Suites at this entry:** python **661 passed, 13 skipped** (includes
the docker-gated postgres suites, run in the same pass). TS **166/167**
— the one failure, `JC-4` (runner killed mid-job → reclaim), is
**pre-existing and load-related, verified by counterfactual**: it fails
identically with these changes stashed (35.3 s, same lease-expiry
error) and passes in isolation (21 s). Not caused by D-85; worth its
own look before CP-8 signs anything off.

## D-86 — D-85 accepted; PR #26 findings dispositioned (owner ruling, 2026-07-27)

**1. D-85 ACCEPTED as landed**, CC-12/CC-13 in the §11 conformance table
affirmed as the correct location — the table is where definition-of-done
lives. The NaN/Infinity→text encoding and the written-out array/interval
renderings are affirmed as within the ruling's "text rendering" clause.

**Standing practice recorded (the `re.subn` near-miss).** Re-wiring the
recycled service-account key with `re.subn` corrupted the file: Python
processes escapes in the *replacement* string, so the key's `\n`
sequences became real newlines and split one env var across eight lines.
Caught by read-back, not by the write. **Mutating a credentials file by
regex replacement is a known trap; read-back verification after any
secrets-file write is the standing practice** — parse the file again,
assert the value round-trips, and assert the variable set is unchanged.
This is cheap and it is the only thing that would have caught it, since
the write itself succeeded and reported success.

**2. JC-4 — named watch item, CP-8 blocker class.** `JC-4` (runner
killed mid-job → reclaim by a second runner) fails under full-suite load
and passes in isolation; the counterfactual (identical failure with the
D-85 changes stashed) is the evidence that it is not ours.
**Checked as instructed and the answer is no:** there is no earlier
flake on record. `DECISIONS.md`, the four `PR-*.md` sign-off documents,
and the commit history contain no CP-6/D-71-era note of an
unreproducible failure — the only prior JC-4 mentions are its
implementation (`df62a05`) and D-85's own entry. So this is the first
record rather than a recurrence, and it arrives with a reproduction
condition (concurrent load) instead of a shrug. To be looked at before
CP-8 signs anything off; suspicion is lease TTL versus process-start
latency when the suite saturates the machine.

**3. `ai_runs.status` — DDL beats prose, two consequences.**

(a) **D-81 correction.** The comment in `deploy/reporting-views.sql`
("`ai_runs.status` is free text with no CHECK constraint", "its
vocabulary is ungrounded") and the sentence repeating it in D-81's
rationale are **wrong as written**. `ai_runs_status_check` enforces
`pending | completed | failed`, and `ai_runs_completion_consistency_check`
ties that vocabulary to `completed_at`. Read from the estate's
`pg_constraint` on 2026-07-27. The **view design stands** — keeping
`status` as a dimension lets a report ground the actual spelling and
derive `failure_pct` itself, which is good practice regardless — but its
stated reason was false. KB PR #26 publishes the enforced enum. The file
comment is corrected at next touch; no dedicated PR for a comment.

(b) **SS-5 elevated** (snapshot spec §10 register + master register).
The item is no longer hypothetical: CHECK constraints being dropped at
the snapshot boundary produced a false claim about the customer's
estate, because a reader working only from the KB saw no constraint and
took our blind spot for the source's vocabulary being open. The CP-7
enrichment run also had to read `pg_constraint` out of band to write
grounded enum documentation. Decision scheduled at **CP-8** — capture is
a snapshot-spec and registry amendment, so it does not block M3.

**4. SMALL-CELL SUPPRESSION — deferred with a trigger.** Register item
**SUPPRESS-1** filed (master register, plan-level section, since the
home spec is genuinely undecided between the formats spec and the MCP
profile limits — settled at the trigger, and this entry is its home
ruling per that section's convention). Default in force: the docs warn,
nothing enforces. Trigger: **before any report reaches an audience
outside the team.** The M3 demo's audience is the owner reading their
own estate, so M3 proceeds without a threshold.

**5. The four other named gaps** — `subscriptions.status` open
vocabulary, no revenue column anywhere, `pending` runs indistinguishable
from abandoned ones, the non-monotonic funnel — **stand as honest KB
gaps.** They are the product working: `flag_gap` and future enrichment
are what they exist for. No action.

**6. GO for part B preparation** (the live M3 gate demo).

**KB PR #26 merged** 2026-07-27T13:07:58Z — the five task 7.0 views now
carry human semantics, so the gate demo has a grounding surface.

## D-88 — Setup delivery resolved; setup-export filed as a product gap (owner ruling, 2026-07-27)

**1. Delivery resolved by D-87.4's own fallback clause.** There is no
route that serves the compiled bundle over an already-listening port:
the core exposes `/mcp`, `/.well-known/*` and `/v1/*`, its MCP surface
implements `tools/*` only (no `resources/*`), and a static route would be
new HTTP surface that platform-architecture §6 assigns to the dashboard's
Agent Profiles module — excluded by the CP-7 scope fence. Flag-don't-patch
was the right call. **Delivery for the demo** is the product's own
compiled bundle (`cli.js compile reporter --kb … --url …` → `.mcp.json`
+ `CLAUDE.md` + `.claude/skills/report/SKILL.md`) copied with `scp.exe`
or a USB volume. Safe because the bundle carries no credential — the
token is minted by the login flow on machine 2, never packaged.

**2. Register motion filed: PA-1, one-click setup export.** Home is
platform-architecture §5/§6. That document carries **no spec-local
register**, so the item is tracked directly in the master register under
a new `Platform architecture (PA-*)` section — the same situation as the
sync spec's SO-* items, which were never carried over at consolidation.
(Say the word if you would rather the architecture spec grew a §-register
of its own and PA-1 moved there; that is a structural spec change and I
did not make it unasked.) Evidence recorded with the item: the first
second-machine onboarding hit the gap immediately. Trigger: dashboard
build, or the first real customer onboarding.

**3. Runbook revision accepted**, and the two watch points are adopted
into the owner's run: **Act 1 returning empty rows = stop** (it means the
query reached a base table rather than a reporting view, and everything
after it would be measuring nothing); **either Act 3 case succeeding =
gate failure** — stop and keep the output, since a publish that should
have been denied is the one result that cannot be retried away.

**4. Demo gate:** the `entities/page.md` certification PR (D-87.2) is the
only remaining prerequisite.

## D-89 — Linking API postgres wiring: watch-item outcome, root cause, fix (owner ruling, 2026-07-27)

**The watch item resolved, and not the way it was written.** D-83.3 pinned
the Linking API parameter names in one table and recorded that the live
M3 gate would verify them, with the assumption that "a drifted name
degrades softly — the human completes that field in the Looker UI". The
first opened link falsified the assumption: **PostgreSQL is not a
Linking-API-configurable connector at all**, and an invalid
`ds.<alias>.connector` value does not degrade — Looker Studio **rejects
the whole report-creation request**. Soft degradation is real for a
drifted *parameter* name; it is not real for an invalid *connector*.
The corrected sentence is now in the module.

**Root cause: adapter defect.** Verified independently against Google's
Linking API connector reference (retrieved 2026-07-27): the configurable
set is `bigQuery`, `cloudSpanner`, `community`, `googleAnalytics`,
`googleCloudStorage`, `googleSheets`, `looker`, `searchConsole`. There is
no `postgreSQL` id and no `host`/`port`/`database`/`username` parameters.
Our table invented them. **GA4 and GSC check out verbatim**:
`googleAnalytics` takes `propertyId` (and `viewId`, which is Universal
Analytics only and which we correctly never send), `searchConsole` takes
`siteUrl` and `tableType`.

**Fix.** Postgres-backed sources emit **no `ds.*` parameters whatsoever**
— not `connector`, not `tableName`. Update-mode semantics carry the
template's own embedded data source into the copy, and the returned
`pending_human_steps` names the alias, the view, and where to do it:
"Point the `<alias>` data source at `<schema.view>` in the editor
(Resource → manage added data sources), entering the reporting-role
password when prompted…". For the pilot the emitted URL is now exactly
`create?c.reportId=<template>&r.reportName=<title>` — which is also the
hand-stripped URL that works. GA4/GSC wiring is unchanged.

**Guardrail (D-89.3).** The module now pins its source of truth (the
reference URL + retrieval date) and carries the Linking API's supported
connector-id set. Emitting a `connector` value outside that set raises
`ConfigError` at **our** validation with an actionable message rather
than shipping a parameter Google will reject — a guessed connector is
worse than a refusal, because its failure surfaces as an opaque rejected
`create` in a browser, minutes later, to a customer. Two conformance
tests: every id in the pinned table is a real Linking API connector (so a
future source kind added carelessly fails here, not at Google), and an
unsupported source kind is refused naming what is supported.

**Honesty fix (D-89.4).** The final human step now says a revision
publishes as a **new link and therefore a new copy** — an already-saved
copy is never updated in place. The previous wording let a reader assume
otherwise.

**Register (D-89.6): CI-F filed** — publish depth for Looker Studio,
`template_link` only in v1. **No register item for that posture existed**;
it lived only in the §8.1 reference declaration, so this is a new item
rather than an amended one. Its evidence is this defect's permanent
consequence: a database-backed source can never be prefilled by a link,
so **every published report carries a manual re-point and password step,
per report, forever** — and SQL sources are exactly the recurring-report
case. Escalation paths, both outside the CP-7 fence: a Looker Studio
community connector, or the Data Studio API for programmatic creation.

**Gate status: PAUSED, not failed.** Everything the platform owns
succeeded — grounding, validation, governed execution against the
reporting views, publish authorization, audit. The defect sat at the
external-API boundary, which is precisely what opening a real link
existed to test. Act 1 resumes with a republish (≈4 report creations per
hour) or the stripped URL; the runbook says to record which was used.

**Suites at this entry:** python **663 passed, 13 skipped** (adapter
suite 16/16). Runner image rebuilt so the live publish path carries the
fix.


RULING D-90 — resume authorization

1. D-89 fix ACCEPTED as landed: independent reference verification,
   update-mode URL, honest pending steps, pinned source-of-truth +
   CI guardrail (both tests noted — the pinned-set-is-real check is the
   one that catches the next careless source kind).
2. CI-F filing ACCEPTED as a new register item rather than an amendment —
   correct call, no home existed. Evidence statement affirmed: per-report
   manual re-point + password entry is a standing cost of template_link
   for database-backed sources; escalation paths (community connector /
   Data Studio API) stay outside the fence, trigger: first customer for
   whom the manual step is a real adoption blocker.
3. DEMO RESUMES at Act 1 via republish through the fixed adapter (fresh
   Claude Code session on machine 2; same bundle, no re-compile).
   Record: which route produced the opened link (republish vs
   hand-stripped — expected: republish), whether GA4/GSC sources arrived
   prefilled (a hand-completion field THERE is a real finding; the
   supabase manual pointing is the documented limit), chart kinds
   rendered, UTC start timestamp, and Act 3's two refusal messages
   verbatim.
4. Rate-limit note honored: batch any republishing; ≈4 creations/hour.


RULING D-91 — M3 target replaced: text-to-report via Power BI

1. GATE REDEFINED. CP-7/M3 closes when: a reporter on machine 2, using only
   the compiled one-line setup, types a plain-language report request — and
   a finished, AI-designed, trust-annotated Power BI report exists in the
   customer workspace. "Zero manual wiring," measured: the reporter
   configures no data source, enters no credential, builds no chart;
   pending_human_steps is empty or "open the link" alone. Cross-source
   criterion restated for the new target: a report whose semantic model
   carries a relationship on documented entity keys (entity_ref resolving
   to the certified entity doc); the undocumented-blend refusal criterion
   is unchanged and publisher-agnostic.
2. LOOKER DISPOSITION. All landed CP-7 Looker work REMAINS on main: the
   adapter, D-89 guardrails, template-link path — registered as a
   secondary target with its limits documented (CI-F evidence stands).
   Nothing is deleted; profiles choose targets. The paused demo's Act 1
   evidence is KEPT and committed as CI-F/D-89 evidence; Acts 2–4 will
   run against the Power BI target under the amended gate, not resumed
   on Looker.
3. ENTRY CONDITION (spec-first, the JP-4/sync pattern): a REPORT
   AUTHORING SPEC is authored and merged before build. It owns: the
   two-MCP orchestration contract (context-layer MCP + Microsoft Power
   BI MCPs in one Claude Code session); the data-plane/visual-plane
   boundary; the artifact's new layout/design section; the attestation
   flow through publish_report; the trust-rendering rule; failure and
   revision semantics. It authorizes the additive amendments it needs
   (capability spec publisher flags, formats spec artifact section, MCP
   spec publish_report contract, skill spec report-skill authoring
   flow) — each diff leading per the fence.
4. PRE-RULED INVARIANTS the spec is written to (the product's spine,
   not open questions):
   (a) No LLM in the product: all authoring intelligence runs in the
       customer's Claude Code session via the skill. The core stays
       deterministic.
   (b) Data plane is ours: the semantic model's data is delivered by a
       deterministic core publisher leg from the artifact's validated,
       reporting-view-backed SQL results. The agent NEVER holds
       database credentials; SK-6 survives as the rule on what may
       feed a model. Republish updates the model in place.
   (c) Visual plane is the agent's: design decided per-request within
       the five-kind registry as guidance (FM-2 becomes advisory for
       this target); the chosen design is written back into the
       artifact before attestation, so AI-designed output remains
       reproducible and auditable.
   (d) Trust disclosures render as a visible element OF the report.
   (e) PBIR authoring is OUR thin tooling in the skill (JSON
       generation + Fabric API deploy) — no third-party community MCP
       dependency in the product. Microsoft's official MCPs (remote +
       local modeling) are the only external agentic surfaces, and
       every Microsoft API we emit against gets the D-89 treatment:
       pinned reference + retrieval date + CI conformance check.
5. RISK ACCEPTANCES, recorded: Microsoft preview surfaces may change
   (mitigated per 4e); Entra/workspace/licensing is net-new customer
   cost, accepted; GA4/GSC data delivery becomes our refresh
   responsibility under this target (register item: refresh cadence
   rides sync-policy); Power BI MCP under service-principal auth does
   not enforce PBI-side RLS — acceptable because delivered data is
   exec-role reporting-view aggregates, noted in the threat model.
6. REGISTER: CI-F escalation CLOSED-BY-SUPERSESSION (this ruling is the
   escalation); new items filed per 5. CP-8 remains after CP-7 in
   sequence (no dates by design). BASELINE-1 unaffected.
7. MY SIDE (parallelizable now, the customer-DBA pattern): Entra app
   registration + service principal; Power BI workspace with the SP as
   member; tenant admin setting "Users can use the Power BI MCP server
   endpoint (preview)" enabled; licensing/capacity confirmed; the SP
   credential lands in .secrets under the existing reference
   discipline. Machine 2 (Windows) may optionally carry Power BI
   Desktop for visual verification, but the gate is service-side: the
   report exists in the workspace.

   RULING D-92 — pre-demo bookkeeping

1. CI-F: master register folded — Closed by supersession per D-91.6,
   evidence pointer to the authoring spec. (My miss; the session was
   right to flag rather than touch it.)
2. RA-6 REGISTER ROW AMENDED: the push surface's dated deprecation
   (new-model creation ends 2027-10-31; existing models unaffected)
   becomes the row's explicit trigger — the Fabric/DirectLake escalation
   now has a DEADLINE, not just a scale condition. Decision scheduled no
   later than the first onboarding after mid-2027 or CP-8 of the next
   phase, whichever first.
3. The docker-heavy sync-test flake joins JC-4's watch item (same class:
   load-sensitive, non-reproducing; two consecutive green re-runs is the
   accepted evidence standard for now). Both remain CP-8 look-at items.
4. MCP topology confirmed as built: no Microsoft MCP in the v1 session
   (RA-A/RA-B defaults); escalation triggers unchanged.

RULING D-93 — demo interruption disposition

1. Transcript KEPT and committed as unplanned gate evidence: ungranted
   api-class target refused server-side; capability_gap 6473a5f1 filed
   with routing; CP-R4 held against an operator publish request; spine
   design rule applied unprompted to a novel dataset (token-trend
   interpolation refused). Field notes to DECISIONS.
2. Cause: prerequisite #1 (reporter publish_report:powerbi KB PR) not in
   effect at run time. Fix: merge carrying CL-Resolves: 6473a5f1 —
   demonstrating the L-5 resolution lifecycle live; verify kb_ref at
   /healthz; no machine-2 recompile (allow-set is server-side per call).
3. Act 1 re-runs in a fresh session; CP-R4 answered when asked. Remaining
   prerequisites unchanged: entities/page.md certification before Act 2;
   GA4 query wiring confirmed.

   CORRECTION NOTE (D-94.2, 2026-07-29) to D-93.1 — history kept, wording
   amended. "Ungranted api-class target refused SERVER-SIDE" overstates
   what the July 29 window holds. The refusal was AGENT-SIDE, taken from
   the compiled bundle's allow-set; the audit chain for that window
   contains no publish_report call at all, so server-side enforcement is
   unproven THERE (it is separately evidenced by execute_sql denials of
   2026-07-20 and 2026-07-27, which are not this run). The transcript
   stays committed; what it demonstrates is re-titled: an honest
   agent-side ceiling, a gap filed and routed, CP-R4 held, and the spine
   design rule generalised unprompted to a novel dataset. The other three
   demonstrations in D-93.1 are unaffected.

   CORRECTION NOTE (D-94.3, 2026-07-29) to D-93.2 — the "no machine-2
   recompile" conclusion is WRONG and is corrected: recompile the setup
   bundle and re-copy it to machine 2 after any profile change. The
   premise stands — the server allow-set is authoritative per call and no
   client file can widen it — but the bundle's CLAUDE.md tool list is
   what the session reads as its permissions, so a stale bundle NARROWS
   what the session will attempt. That is what ended the July 29 run. A
   register item is filed against the setup-export design (see D-94.3).

RULING D-94 — prep-report flag dispositions + demo readiness
(owner ruling, 2026-07-29; recorded verbatim)

1. FLAG ① — RA-F CONFIRMED as filed (letters = open decisions, per the
   spec's own convention); D-92.2's dated trigger rides it. The two
   remaining §12.5 items are AUTHORIZED for filing now: GA4/GSC refresh
   cadence under api-class targets (home: sync-policy register) and
   report lifecycle/teardown (home: authoring spec §13). Additive only.
2. FLAG ② — ACCEPTED. D-93.1's wording is amended: the July 29 refusal
   was AGENT-SIDE from the compiled allow-set; no publish_report call
   exists in that window; server-side enforcement is unproven there.
   The transcript stays committed; its README re-titles what it shows:
   honest agent-side ceiling, gap filed and routed, CP-R4 held, spine
   rule generalized to a novel dataset.
3. FLAG ③ — ACCEPTED. D-93.2's "no recompile" conclusion is corrected:
   recompile and re-copy the bundle after any profile change; the
   premise (server allow-set authoritative per call) stands. REGISTER
   ITEM filed (home: the setup-export item, platform-architecture §5):
   compiled-bundle staleness — the bundle's tool list acts as de facto
   client-side permissions; compile-on-profile-change or a staleness
   warning belongs in the setup-export design. Evidence: July 29.
4. FLAG ④ — ACCEPTED. Act 3a passes in EITHER shape: agent-side refusal
   citing the profile ceiling, or a server denied audit row. Coaching
   forbidden. The runbook may include an optional operator-run direct
   probe producing a genuine server denial as supplementary evidence.
   AUTHORIZED CODE CHANGE (one line + read-back test):
   CORE_MCP_PUBLISH_PER_HOUR passthrough in docker-compose.yml; runbook
   4.3 simplified accordingly.
5. CERTIFICATION DELEGATION (OB-2 pattern): the session gathers the
   entities/page.md evidence pack and DRAFTS the certification PR; the
   certification judgment and both merges remain the operator's. If the
   evidence fails the doc's stated normalization rule, that is a
   finding — no flip.
6. The publish_report:powerbi KB PR: session AUTHORS it, body carrying
   the FULL 36-char trailer CL-Resolves:
   6473a5f1-f4f7-4dfd-b702-a15ba760ce14; operator merges as R2; session
   verifies propagation and resolved_by: pr via the 5-minute sweep.

RULING D-95 — M3 SIGN-OFF (amended target, D-91.1)
(owner ruling, 2026-07-30; recorded verbatim)

1. M3 SIGNED OFF on the operator's attestation: all four acts passed on
   machine 2 under the amended gate (plain-language → finished
   AI-designed trust-annotated Power BI report, operator labor absent;
   cross-source on certified entity keys; both refusals held; audit
   chain extracted). EVIDENCE NOT INSPECTED BY THE RULING PARTY —
   recorded as an explicit owner acceptance, same class as D-80.2. The
   committed results/cp7-gate/ evidence stands as the record; if part C
   bookkeeping is not yet written, it rides the CP-8 session.
2. Checkpoint-landing convention (D-74.2): CP-7 closes with all work on
   main and registers current. CP-7/M3 marked CLOSED in the plan.
3. The build phase of the pilot is complete: every spec-set component is
   live — snapshots, generator, sync, MCP+SSO, gateway, skills,
   publisher (two targets), ledger, audit.

## D-95 part C — CP-7/M3 closure bookkeeping (written at CP-8, 2026-07-30)

Written under the CP-8 session's Part-0 authorization. D-95.1 records the
sign-off as an **owner acceptance on attestation**, so nothing below
revisits the ruling. What follows is the bookkeeping the ruling says
rides this session: what the record holds, what it does not, and the FM-2
note D-83 left open. Claims are tagged with where they can be checked.

**Correction to D-95.1's own premise, stated plainly.** The committed
`results/cp7-gate/` evidence does **not** contain the gate demo. Its
files are preparation artifacts: `READINESS-2026-07-29.md` (a **NO-GO**
verdict written at 10:46 UTC — the runner did not yet host the `powerbi`
connector), the runbook, the extraction script, the interrupted-run
transcript evidence from 09:13–09:21 UTC, the L-5 closure note, and the
page-certification pack. `extract-audit.sh` was never run for the gate
window, so no audit chain, publish trail, or ledger dump from the demo is
committed. The demo's record exists **only in the live ops database on
machine 1**, read read-only for this entry.

**The gate run, as the server recorded it** (`cl_ops`, read-only queries,
2026-07-30). Window `2026-07-29T11:11:49Z` → `12:05:16Z`, subject
`reporter`, profile `reporter`; `max(ts)` over `audit_records` is
`12:05:16Z`, so nothing followed it.

- Four `publish` jobs, `connector_name = powerbi`, all `succeeded`
  (11:41:50, 11:54:13, 12:03:44, 12:05:16) — the uncommitted
  `deploy/runner-config.yaml` line the readiness report recommended was
  applied and worked.
- `publish_report` audit rows: `deliver_model` ×3 (11:39:53, 11:41:02,
  11:41:55), `attest` (11:54:13), `attest` (12:02:49), `deliver_model`
  (12:03:50), `attest` (12:05:16) — all `allowed`, all against artifact
  `ra-85561dbe-8572-4391-95c9-4e1b897d8325`.
- `report_attestations`: two rows, revisions 1 and 2, **same**
  `report_id bae55769-0cb3-41ba-877a-e9cd77a964d8`, **different**
  `definition_hash` (`sha256:fe42d64d…` → `sha256:25f870e9…`). That is
  **AT-6's layout-change path, live at the gate** on a configured workspace.
- `model_deliveries`: one row, revision 2, workspace `5d8eeeff…`, dataset
  `0e208ebc…`. No dangling delivery (every delivery's revision carries an
  attestation).
- `lineage_attestations`: three rows written at attest time (11:54:13)
  binding `powerbi.report.bae55769…` to `reporting.v_ai_runs_by_flow`,
  `v_ai_tokens_by_month`, `v_daily_activity` — F-4 provenance captured.
- `report_artifacts`: two revisions, `kb_ref d946511e…`, twelve
  `trust_notes` including an explicit *SMALL CELLS — NOT FOR EXTERNAL
  DISTRIBUTION* line naming the two-and-three-run flows. The report
  discloses that it models a daily series it cannot measure, and says so
  in its own title.

**What that record supports.** Act 1, in a harder form than the runbook
scripted: the operator asked about AI token usage rather than the
rehearsed signups case, and the journey ran ground → validate → execute →
deliver → author → deploy → verify → attest → revise, with the design
rules holding on unrehearsed ground.

**What the record does not support** — flagged, not asserted away:

1. **Act 2 (cross-source on certified entity keys) has no server-side
   trace.** The gate artifact carries `"blend": null` and three queries,
   all `system: supabase`. No `execute_sql` against `ga4` or `gsc` under
   the reporter identity appears anywhere in the window (the only GA4/GSC
   executions that day are the 10:35 prep checks under the `benchmark`
   profile). One artifact, one dataset, one report. The prerequisites for
   Act 2 were in place — KB PR #29 merged at 10:48 and `entities/page.md`
   is `status: verified` on `origin/main` — so this reads as an act that
   was not run or not completed, not one that was blocked.
2. **Act 3b (undocumented-blend refusal) has no ledger entry.** Per
   D-83.5/RA-9 the refusal's ledger half arrives as
   `flag_gap(kind: missing_join_path)`. No such event exists; the
   window's three `flag_gap` calls are all `capability_gap`.
3. **Act 3a's server-side denial is not in the gate window.** The only
   `publish_report` denial on record is `2026-07-29T10:13:48Z`
   (`granted only for looker_studio, not google_sheets`) — the
   operator-run probe from the prep session, an hour before the demo
   started. D-94.4 permits Act 3a to pass in its agent-side shape, which
   only the transcript can show.
4. **Act 4 was not extracted.** No `audit-chain.txt`,
   `publish-trail.txt`, `publish-results.json` or ledger dump from the
   window is committed. The rows still exist; the extraction is one
   command (`results/cp7-gate/extract-audit.sh '2026-07-29T11:00:00Z'`)
   and is **operator-runnable now**. Until it runs, the gate's record
   depends on a running container.
5. **No machine-2 transcript is committed**, for this run or for the
   interrupted one (that directory's own README already asks for it).
   Acts 2 and 3 are exactly the claims only a transcript can settle.
6. **CP-7 exit gate item 2 is pending, not failed.** The F-4 attestations
   exist in ops (above), but no graph-only drift run has carried them
   into the KB: `origin/main`'s `lineage/graph.json` holds 28 nodes / 25
   edges, no `powerbi.report.*` or `looker_studio.report.*` node, and no
   `{kind: "gateway"}` input. `get_lineage` therefore cannot yet walk
   from the report node. One sync run + one additive KB PR closes it.
7. **The configuration the gate ran on is not on `main`.**
   `deploy/runner-config.yaml`'s `connectors.powerbi.connector` line is
   still an uncommitted working-tree change. Under D-74.2/D-82 a
   checkpoint does not close while its work is unlanded; a clean checkout
   of `main` today rebuilds a runner that cannot serve a Power BI publish
   — the exact blocker the readiness report found.

**FM-2 note — the real evidence** (D-83's note said "to be filled with
the template's actual id + kinds at operator template creation"; under
the D-91 target there is no template, so the honest fill is the kinds the
AI actually authored):

| Revision | Registry kinds authored | Source |
|---|---|---|
| 1 | `line`, `bar`, `table` | `report_artifacts.body.layout.pages[].visuals[]` |
| 2 | `bar`, `table` | same, after the layout revision |

`scorecard` and `pivot` were **not** exercised by the gate report.
Revision 2's `line` → `bar` substitution is recorded in the artifact's
own trust notes: the delivered date column on a push dataset cannot back
a continuous axis, and bars do not interpolate. That is the registry
behaving as **advisory** for an api-class target exactly as the authoring
spec's §12.2 amendment intended — one substitution, recorded with its
reason, no inexpressible report. **No register change is proposed here**
(the amendment fence); FM-2's row stays Open with this as its CP-7
evidence, and the CP-8 report carries the disposition motion.

**Suites/state at this entry:** unchanged since `2f646f9` — no code, spec,
or KB change was made by the CP-8 session. The last committed suite
figures stand (python 724 passed / 14 skipped; core 185 passed across two
consecutive full runs, `READINESS-2026-07-29.md`).

RULING D-96 — CP-8 dispositions and Phase-2 authorization
(owner ruling, 2026-07-31; recorded verbatim)

1. VERDICT ACCEPTED as written: GO-with-conditions for vendor-assisted
   onboarding; NO-GO unassisted. CP-8 closes on this report. The
   two-track Phase-2 shape is ADOPTED as the planning basis.
2. D-95 CORRECTION (appended note): Act 1 confirmed over-evidenced;
   Act 3a passes under D-94.4's either-shape; Act 2 and Act 3b
   reclassified NOT DEMONSTRATED and re-run under Track A-0 with
   server evidence extracted same-day. Extraction-same-day becomes a
   standing runbook rule.
3. REGISTER-DISPOSITION BLOCK: every row RULED AS RECOMMENDED, with
   these modifications and confirmations:
   a. R-2 CLOSES NOW by bookkeeping, not confirmation-pending: the SA
      key recycle WAS completed and live-verified (GSC pull canonical
      body a40d0fab, byte-identical to prior pulls — session record,
      D-85 era). The gap was a missing DECISIONS line; write it.
   b. R-1: the pilot KB REMAINS PUBLIC by explicit owner choice, as a
      reference estate, with the one-line index.md note; the playbook
      gains the line "customer KBs are private from bootstrap." Next
      customer inherits the rule, not the exception.
   c. REVIEW-SYNC: BUILD (Track A-1), not despecify. It is named in
      two shipped profiles; amending the spec to match the gap would
      close the finding by lowering the bar.
   d. SS-5: capture authorized exactly as scoped (hash-included
      stats.checks, verbatim pg_get_constraintdef, Postgres-only,
      sorted; SS-6 explicitly untouched). Registry amendment under
      the fence, spec diff leads, wheel rebuilt per D-46.
   e. RA-F decision re-dated: 2027-01-31, or first
      push_limit_exceeded, or second Power BI customer — whichever
      first; the 80%-of-limit telemetry warning is a Track-A chore.
   f. JC-4: test-only diff accepted; verification = three consecutive
      full-suite runs UNDER DELIBERATE LOAD. Docker flake:
      quarantine-with-trigger — next occurrence captured with full
      output before any re-run green.
   g. OB-4: BUILD the instrumentation (Track A-6). "Cannot close" is
      not an acceptable state for a gate item the playbook cites.
4. IMMEDIATE CHORES, before Phase-2 build starts: C-1 (commit
   runner-config — CP-7 is closed over unlanded work until this
   lands); C-6 (run extract-audit for the demo window, commit;
   graph-only sync run carries F-4 nodes into the KB; verify
   get_lineage walks from the report node — CP-7 exit item 2);
   bookkeeping batch (OB-3/JP-4 master reconcile, SO-* section added
   to master, D-95 correction note, R-2 line, R-3 close-clean note).
5. STANDING CONSTRAINT carried into Phase 2, verbatim in its plan: no
   quantitative KB-value claim in any customer or demo material until
   BASELINE-1 lands.
6. PHASE-2 DOCUMENTS: authored next in the planning session — the
   Phase-2 development plan (Tracks A/B as checkpoints with gates)
   and the dashboard/UI spec (spec-first; Part 5's inventory,
   role→view matrix, and the no-UI boundary list are its requirements
   inventory; the API-client-only rule is its first design ruling).

## D-96 application record — the bookkeeping batch (2026-07-31)

Written by the session D-96 authorizes. Every claim below is checkable
against a commit, a row, or a file; nothing here is a summary standing in
for evidence that was not produced.

### D-95 CORRECTION (D-96.2) — appended to D-95, not replacing it

D-95.1's sign-off stands as an owner acceptance on attestation. What
changes is the **evidentiary classification of two of its four acts**,
now that the rows exist (`results/cp7-gate/EVIDENCE-2026-07-29.md`,
extracted 2026-07-31 from the window `2026-07-29T11:11:49Z`–`12:05:16Z`):

| Act | Classification | On what |
|---|---|---|
| 1 — plain-language → finished report | **CONFIRMED, over-evidenced** | 39 audit rows, all `allowed`, all `subject=reporter`; ground → validate → execute → publish, on an *unrehearsed* question (AI token usage, not the runbook's signups case). The journey held on ground it had not been walked over |
| 2 — cross-source on certified entity keys | **NOT DEMONSTRATED** | All 12 `validate_sql`/`execute_sql` rows carry `system: supabase`. No `ga4`/`gsc` execution exists under the reporter identity anywhere in the window. Its prerequisites were in place (KB PR #29 merged 10:48; `entities/page.md` `status: verified`), so this is an act not run, not an act blocked |
| 3a — publish-target denial | **PASSES**, under D-94.4's either-shape | Zero `denied` rows in the window. The only `publish_report` denial on record is the operator's 10:13:48Z prep probe, an hour earlier. D-94.4 permits the agent-side refusal, which only a transcript can show; accepted on that basis and not re-classified |
| 3b — undocumented-blend refusal | **NOT DEMONSTRATED** | Both ledger events in the window are `capability_gap`. No `missing_join_path` event exists, which is the ledger half RA-9/D-83.5 requires of this refusal |

Acts 2 and 3b **re-run under Track A-0**, with server evidence extracted
the same day. A re-reading cannot fix them: the rows that would evidence
them were never written.

**Standing runbook rule created here** (D-96.2, applied to
`results/cp7-gate/RUNBOOK.md` §9): **extraction runs the same day as the
demo**, before the session that ran it ends. The 2026-07-29 gate is the
reason — extraction slipped two days, the demo's entire record lived in a
running container meanwhile, and by the time anyone read the rows two
acts had already been signed off on attestation.

**A correction to D-95 part C's own arithmetic, while here:** part C says
"the window's three `flag_gap` calls are all `capability_gap`". The
extracted window holds **two** (11:34:29 and 11:43:26), both
`capability_gap`. The conclusion is unchanged and slightly strengthened —
the third call was outside 11:00Z, so an even smaller set of ledger
activity carries the demo.

### R-2 CLOSED (D-96.3a) — the missing line, written

`D-80.2(b)` accepted deferred rotation of a leaked exec DSN **and** a
leaked GA4/GSC service-account key. D-84.1 recorded the exec-DSN half
rotated and live-verified. The **service-account half was also completed
and live-verified** in the D-85-era session; no `DECISIONS` entry ever
said so, which is the only reason the CP-8 review found it "pending". The
gap was bookkeeping, not work. **R-2 closes.**

Evidence, and it is stronger now than when the ruling was written — the
GSC canonical body hash across three live pulls spanning the recycle:

| Pull | `canonical_body_sha256` | Objects |
|---|---|---|
| 2026-07-20 14:12 (`01KXZXXTW0…`) | `a40d0fab958dd8bb…` | 10 |
| 2026-07-27 12:29 (`01KYHRSKJ8…`) | `a40d0fab958dd8bb…` | 10 |
| **2026-07-31 11:06 (`01KYVXMRVX…`)** | `a40d0fab958dd8bb…` | 10 |

The third row is today's, pulled by the C-6 sync run under the recycled
key. The recycled credential authenticates and returns a **byte-identical
canonical body** — which is two facts at once: the recycle is real and
working, and S-3 determinism survives a credential rotation.

### R-3 CLOSED clean (D-96.3) — the check, recorded so it is not re-litigated

Git-history exposure of the leaked credentials: **re-checked this
session, clean.** `.secrets/` is git-ignored (`.gitignore:3`) and
`git log --all -- .secrets/` returns nothing — no secret file was ever
tracked, in any branch, at any point. Every tracked occurrence of
`postgresql://` carries a synthetic or credential-free DSN: a literal
`postgresql://…` placeholder in the `onboard` skill, a localhost
ephemeral DSN with no password (`connectors/postgres/ephemeral.py:99`),
and three test fixtures (`u@h/db`, `postgres@127.0.0.1:9`, `x/y`). The
exposure was chat/session-side, never repository-side.

Recorded here so that **no history rewrite is ever contemplated on a
rumour**: the question was asked, answered from the object database, and
closed. A future reader who wonders should re-run the two commands rather
than assume.

### R-1 — the pilot KB stays public, by explicit choice (D-96.3b)

Not carried silently, and not closed by inaction. Two separable things:

1. **The pilot KB (`github.com/AlperCamli/DataAnalyticsTool`) REMAINS
   PUBLIC**, by the owner's explicit choice, as a **reference estate** —
   it is the owner's own data and confidentiality was waived at D-47/
   D-80.2(a). It now carries reporting-view semantics, entity key
   mappings, a certified `entities/page.md`, and (via PR #30) report
   lineage — a readable map of the estate, published deliberately. A
   one-line note in its `index.md` says so, so a reader never has to
   infer that public was a decision rather than an oversight.
2. **The rule the next customer inherits is the opposite one.** The
   playbook gains, at KB bootstrap: *customer KBs are private from
   bootstrap.* The pilot is the exception, stated as one. This is the
   half that matters — R-1's original risk was never "this repo is
   public", it was "public becomes the default nobody re-decided".

R-1 therefore **closes**: the trigger ("revisit before any real second
customer") has been honoured ahead of the trigger, with both halves
written down.

### The chores (D-96.4)

| Chore | State | Evidence |
|---|---|---|
| **C-1** — land the runner-config Power BI line | **DONE** | commit `9463e61`. CP-7 is no longer closed over unlanded work |
| **C-6a** — extract + commit the gate evidence | **DONE** | commit `066e916`; five dump files + `EVIDENCE-2026-07-29.md` |
| **C-6b** — graph-only run carries F-4 nodes to the KB | **DONE, awaiting merge** | commit `8bcadf4`; run `01KYVXMQ8Q0BAHTKC8WM5WBK5S` → KB PR #30, `lineage/graph.json` +115/−0, 28→32 nodes, 25→32 edges, label `sync:additive-only` |
| **C-6c** — `get_lineage` walks from the report node (CP-7 exit item 2) | **EVIDENCED, NOT CLOSED** | The walk is verified against PR #30's graph (15 nodes / 17 edges at depth 3, three reporting views at hop 1). It closes on the **post-merge** call against the live server; the merge is R2's (SO-B) |
| bookkeeping batch | **DONE** | this entry + the master-register reconcile below |

**Two product flags found by running C-6, recorded not fixed** (outside
the D-96 fence):

1. **The graph-only PR misdescribes itself.** `detail.wheel_only` is set
   on any run with `changed.length === 0`
   (`core/src/pipeline.ts:665`), and `changelog.ts` has no graph-only
   case — so PR #30's title is `sync: 0 breaking, 0 additive across `
   (empty system list) and its body reads *"Wheel-only run: no drift
   pending; carry forced by a manual sync."* There is no wheel in it. The
   single PR that records report lineage entering the KB tells the
   steward reviewing it something false about why it exists. One `else
   if` fixes it; recommended as a Track A-0 chore.
2. **A malformed node predates this run.** `supabase.` (`node_kind:
   external`, `resolved: false`) already sits in HEAD's graph with an
   `aggregate` edge into `v_daily_activity` — an unresolved reference
   that parsed to an empty object name.

## D-96 task 2 — the four accepted small fixes (applied 2026-07-31)

Landed as `6aea90c`. Each is small; three of them are small because the
CP-8 review did the diagnosis first.

**JC-4 — test-only, and the diagnosis is the deliverable.** The failing
assertion was never a product defect: `core/test/e2e.test.ts` is the only
suite that compresses the lease to 2 s, and the SDK heartbeats at
`lease_ttl / 2`, so it ran a **1 s beat against a 2 s lease** while
production runs 60 s. One scheduling stall on a loaded machine expires a
**live** lease; the 200 ms sweeper requeues work that is still running,
and every downstream assertion mismatches. Fix: pin the heartbeat at
0.5 s, widen the lease to 8 s (16:1 margin), widen the waits to match.
`expect(requeued.attempt).toBe(2)` stays strict deliberately — at that
margin a spurious expiry is a real signal, and softening it would trade
the flake for blindness.

**Verified to D-96.3f's standard: 3/3 green under deliberate load**
(`results/cp8/jc4-verification/`, logs committed). 188 tests per run;
JC-4 itself passed at 22.99 s / 21.76 s / 21.41 s — a 1.6 s band, against
the 35.3 s timeout it replaces. The load was a continuously looping
`docker build --no-cache` of the core image (204k lines of build log)
plus a 7-spinner CPU ring on an 8-core box; suite wall-clock roughly
doubled, so the contention was real rather than nominal. **Not claimed:**
that the docker-heavy sync flake is fixed. It is a different failure
(container-start latency, not lease protocol) and stays under D-96.3f's
quarantine-with-trigger — no occurrence in these three runs, which is
evidence of nothing either way.

**F-7 — a profile naming a missing skill now fails the compile.** It
warned and proceeded, and that is precisely how a steward bundle shipped
without `review-sync` for an entire checkpoint while `compile` exited 0.
The bundle's `CLAUDE.md` is what the session reads as the statement of
what it may do (PA-2), so a bundle missing a skill ships a **quietly
smaller product than the profile describes**. `compileProfile` now throws
`MissingSkillError` naming the profile, the gap, and what does ship; the
CLI prints it and exits 1 **without writing a bundle** — emitting nothing
is the honest outcome when the thing cannot be built correctly.

> **Consequence, stated rather than discovered:** `compile steward`
> **fails today.** The shipped steward profile names `review-sync`, and
> D-96.3c ruled BUILD rather than despecify, so the skill genuinely does
> not exist. That is the intended signal — C-2 is real and now visible at
> the point of use. Server-side steward access is untouched (the
> allow-set is enforced per call); only the compiled bundle is blocked,
> until Track A-1 ships the skill.

**R-8 — the D-79 watch-note becomes a test.** Every skill named by a
shipped fixture profile must exist in `core/skills/`. The exception list
carries exactly one ruled entry (`review-sync` → C-2 / Track A-1), and a
second test **fails the moment an exception's skill ships**, so the list
cannot quietly become permanent — which is how the watch-note itself went
unactioned. A third test runs the counterfactual for real: compiling the
steward profile against a core without `review-sync` raises. The claim
"this test would have caught C-2" is therefore executed, not asserted.

**R-5 — RA-10 asserted instead of implied.** The preflight's membership
check only ever proved the target workspace was *among* what the SP can
see; "member of the designated workspace(s) **only**" was a human
promise. New `sp-scope` check: green when the SP sees nothing else,
**advisory** (loud, non-blocking, naming the extra workspaces) when it
does. Advisory rather than fatal because delivered data is exec-role
aggregates — this must not gate STOP-A — and because the operator may
legitimately accept the posture. What it must not do is stay unsaid.

**R-6(b) — the wheel pin leaves the workflow.** `core/src/wheel.ts` no
longer writes any workflow file; `kb-ci.yml` reads `wheel:` and
`runtime_deps:` from `VENDOR-MANIFEST.yaml` at job time (KB **PR #32**,
CI green on the new install path). The carry preserves `runtime_deps`
verbatim — dropping it would leave CI installing no pins at all. Sync
spec §10 amended; **SO-10 now asserts** the wheel commit stages
`.github/vendor/**` only and leaves `kb-ci.yml` byte-identical, because
"we don't need that scope" is the kind of claim that rots silently.

The KB PR is only half. **R-6 closes on the operator dropping `workflow`
write from the sync PAT** — exact steps are in PR #32's body, including
the verification step (trigger a manual sync and confirm a PR still
opens; a PAT that lost `contents` write fails loudly at push). Until
then this is a change that makes the narrowing *possible*, and the risk
is still carried.

## D-96.3d — SS-5 CLOSED BY CAPTURE (applied 2026-07-31)

The finding that started this closes by making the fact available, not by
writing a convention about it. Spec diff led, per the fence.

**What was registered.** `stats.checks` on `kind: table`,
**hash-included**: the verbatim `pg_get_constraintdef(oid, true)` text of
every `contype = 'c'` constraint, lexicographically sorted. Postgres only.
Snapshot spec §4.5 carries the registration record and its arguments;
master register SS-5 → *Closed by capture*; **SS-6 (enum type labels)
stays Open and is explicitly not pre-empted.**

**The three judgement calls, and why.**

1. **Hash-included, where `indexes` is hash-excluded.** The S-2 test is
   "can this contradict a documented meaning?" An index cannot. A CHECK
   *is* a documented meaning, stated by the source — so a widened or
   dropped one must be able to reach the contamination scan and mark the
   doc that explains it. `test_ss5_check_is_hash_included_so_a_widened_constraint_contaminates`
   executes exactly that: widen `orders_total_cents_check`, and exactly
   one schema hash moves — the table's.
2. **Verbatim, never parsed.** S-8: the connector emits the engine's own
   rendering. Turning `status = ANY (ARRAY['pending', …])` into an enum
   set would be the boundary *inferring* a vocabulary, which is the
   generator's and the human's job. Consumers that want the vocabulary
   read the expression — which is all D-86.3b's reader ever needed.
3. **Scope by construction, not by convention.** `contype = 'c'` alone
   excludes NOT NULL (already `columns[].nullable`; `'n'` on PG17+),
   keys (`'p'`/`'u'`/`'f'`, carried by `keys`), and exclusion
   constraints (`'x'`). `conrelid <> 0` drops domain constraints, which
   would otherwise attach to oid 0.

**Determinism.** Sorted in the connector, not left to the catalog:
`pg_constraint` order is not stable across dump/restore and S-3 requires
byte-identical canonical bodies from identical source state.
`test_ss5_multiple_checks_sort_lexicographically` uses constraint names
(`aa_`/`zz_`) deliberately anti-correlated with the expression text, so a
sort-by-name regression fails.

**Generator.** One template section, and it is `None` — absent, not
"—" — on every kind but `table`. "Check constraints: —" on a view would
assert an absence the snapshot never looked for, which is the same
confident silence SS-5 exists to remove.

**Wheel (D-46).** Version bumped 0.5.0 → **0.6.0**. This one genuinely
changes the KB CI surface twice: C-8 now admits a stats field it used to
reject, and KB-8 render consistency compares against a template emitting
a new section. A KB validating with the 0.5.0 wheel would call the new
machine docs stale — the stale-wheel failure D-46 exists to make visible
— so the carry is not optional, and it rides the drift PR as sync spec
§10 designs it (wheel commit first, so the PR's own CI runs the wheel
that will govern after merge).

**Verified, not asserted** (`results/cp8/ss5-capture-verification.md`):
25/25 container-backed postgres tests including C-1/C-2/C-3/C-4/C-8
re-run against the changed connector; full python suite 732 passed / 14
skipped. On the **live example estate**, two consecutive pulls through the
product path returned canonical body `bef2fa14c60a3520…` **byte-identical**
with `checks` in it — C-2 holds on the example estate. C-3 is *not* claimed
there and cannot be: mode invariance needs the same state through
`ddl-file` and `live`, and a hosted Supabase offers only `live`; its
evidence is the container suite.

**What it found.** 15 of the estate's 17 tables carry CHECKs — ~40
constraints the boundary had been dropping since task 1.2, mostly the
enum-like vocabularies (`status`, `flow_type`, `format`, `locale`,
`progress_stage`) that report semantics rest on. Including, closing on
itself, `public.ai_runs`:

```
CHECK (status = ANY (ARRAY['pending'::text, 'completed'::text, 'failed'::text]))
CHECK (status = 'pending'::text AND completed_at IS NULL
       OR (status = ANY (ARRAY['completed'::text, 'failed'::text]))
          AND completed_at IS NOT NULL)
```

Both existed the whole time D-81 called the column "free text with no
CHECK constraint".

**STOP — and one required ordering, stated because it is a real
constraint and not a defect.** The drift PR was deliberately **not**
opened. The 0.6.0 carry deletes the 0.5.0 wheel file; `origin/main`'s
`kb-ci.yml` still hardcodes that filename; and since R-6(b) the carry no
longer edits workflow files — which is the entire point of R-6(b). A
drift PR opened today would install a wheel its own branch deleted and
fail loudly. **KB PR #32 must merge first**, after which `kb-ci.yml`
reads the filename from the manifest the carry rewrites. The operator's
sequence (merge #32, then `sync now supabase`, then review as R2) is in
the verification note. Also noted there: the estate has moved 34 → 38
objects since 2026-07-27, so the pending drift is not only this capture.

RULING D-97 — post-D-96 loose ends
(owner ruling, 2026-07-31; recorded verbatim)

1. PR #30 mislabel ("wheel-only" on a graph-only run): accepted as
   flagged; a one-line changelog.ts graph-only case is AUTHORIZED as a
   Track A-0 chore. Content correct; label wrong; fix cheap.
2. compile steward failing until review-sync ships: CORRECT behavior
   (F-7 hardening working as ruled). Noted so nobody "fixes" it.
3. SS-5 drift sequence and Desktop working-tree warning: adopted as
   operator checklist items.
4. Remaining register rows from D-96.3 that no task applied: batched
   into the Phase-2 planning session's bookkeeping.

## D-97 application record (2026-07-31)

**D-97.1 — the graph-only case, applied.** `changelog.ts` had no branch
for the CP-7 F-4 path, so a graph-only run fell through to the wheel-only
one: KB PR #30 — the single PR that records report lineage entering the
KB — told its reviewer it was a wheel carry, and named no wheel.

Title and body now say what the PR contains:

```
sync: 0 breaking, 0 additive (report lineage only)

Graph-only run: no snapshot drift pending. This PR carries publish
attestations recorded since the last regeneration into
`lineage/graph.json` — report nodes and their gateway edges (CP-7 F-4).
Additive by construction: BI-side nodes cannot contaminate a doc, so no
contamination scan and no re-render ran.
```

**One design choice worth stating.** `graphOnly` is *passed* from the
pipeline, not inferred from `!scan && !wheel`. A run can be graph-only
**and** carry a wheel (manual sync + version mismatch + pending
attestations); inference would then describe that PR as wheel-only and
never mention the graph — the same class of mislabel this fix removes.
That case gets its own title (`report lineage + wheel update to X`) and
keeps the wheel banner. Cost: one field on `ChangelogInput`, one line at
its construction site (`pipeline.ts`). Three tests, including the
genuine-wheel-only case asserted unchanged.

**PR #30 corrected in place.** Its title and body were rewritten to
exactly what the fixed `buildTitle`/`buildBody` emit for that run's
inputs — **rendered from the fixed code, not hand-written** — with a note
on the PR recording that the correction happened and that no commit,
file, or byte of its content changed. Re-running the sync instead would
have opened a duplicate PR against an unmerged one.

**Still flagged, NOT fixed — the ops half of the same mislabel.** The run
*record* also lies: `detail.wheel_only` is set on **any** run with
`changed.length === 0` (`core/src/pipeline.ts:666`), so run
`01KYVXMQ8Q0BAHTKC8WM5WBK5S` is stored in `runs` as wheel-only when no
wheel was involved. D-97.1 authorizes the `changelog.ts` case; the run
detail is a different field with a different consumer (the `runs` table,
read by ops and by the future dashboard's U-10 view), so it stays flagged
under the fence rather than changed. **Recommendation:** fold it into the
same Track A-0 chore — one line, `wheel_only` → `{ wheel_only: !!wheelCarry,
graph_only: gatewayPending }`.

**D-97.2** — recorded, no action: `compile steward` failing until
`review-sync` ships is F-7 working as D-96.3c ruled. It is a signal, not
a regression; loosening the compile would re-create the exact silence
that let a steward bundle ship without half the drift loop.

**D-97.3/D-97.4** — no action this session: the SS-5 drift sequence and
the `~/Desktop/kb` working-tree warning are already written in
`results/cp8/post-d96-status.md` as operator checklist items, and the
unapplied D-96.3 register rows are listed there for the Phase-2 planning
session's bookkeeping.

**Suites at this entry:** python 732 passed / 14 skipped; core 191
passed (19 files).

RULING D-98 — A-0 amendment + A-1 authorization
(owner ruling, 2026-08-04; recorded verbatim)

1. The Act 2 / Act 3b re-runs are WAIVED by explicit owner acceptance
   (class: D-80.2/D-95). Permanent record: the cross-source publish
   path (model relationship on documented entity keys) and the
   missing_join_path refusal have NO server-side evidence; both remain
   attested-not-evidenced; the first customer-facing cross-source
   report is the de facto evidence point. This waiver does not
   propagate: no future document may cite Act 2 or Act 3b as
   demonstrated.
2. A-0 reduces to chores, folded into this session as task 0.
3. A-1 authorized per the plan's gate. Drill staging pre-ruling: the
   staged breaking change is a column rename in ONE reporting view,
   applied by the operator as DBA (D-81 discipline — the session
   drafts the DDL, never applies it), and REVERTED the same way after
   evidence extraction so the estate ends byte-identical. Same-day
   evidence extraction is the standing rule (D-96.2).

## D-98 application record (2026-08-04)

### STEP 0 — premise verification, with one premise found false

Verified before any work, as instructed; results recorded because one
premise failed and the deviation is the operator's ruling, not the
session's.

1. **The Phase-2 plan on main** — false as stated. Nothing named
   `plans/phase2-development-plan-v1.md` existed on main; the plan sat
   uncommitted as `plans/phase2-development-plan.md` (acknowledged by
   the operator in the session brief). Reconciled here: renamed to the
   `-v1` name every citation uses and landed with this entry. Its
   status line updated from "draft for the operator's ratification" to
   ratified, citing D-98 — the ruling that authorizes A-1 *per the
   plan's gate* is the ratification act the draft line awaited.
2. **D-96/D-97 recorded** — true (this file, entries above).
3. **`compile steward` fails naming review-sync** — true, re-run this
   session: exit 1, no bundle written, message naming the profile, the
   missing skill, and what ships. F-7 working as D-97.2 ruled;
   untouched.
4. **Closure-session KB PRs merged** — HALF FALSE. PR #32 (wheel pin →
   `VENDOR-MANIFEST.yaml`) and #30/#31 are merged on
   `Sample-Knowladge-Base`; but **the SS-5 drift PR was never opened** —
   no sync PR exists after #30, zero open PRs, KB `origin/main` head is
   `462421c` (#32). The post-d96-status sequence stopped at the merge.
   The three editor-padded machine docs in the `~/Desktop/kb` working
   tree also still stand.

**Operator ruling on the deviation (in-session, 2026-08-04):** tasks 0
and 1 proceed now (both are platform-repo-local and estate-independent);
the SS-5 drift flush — restore the three files, `sync now supabase`,
review and merge the drift PR as R2 — is the operator's, and happens
before the task-2 drill's STOP-1 so the staged break is the only thing
in the drill's sync PR and the final byte-identical check has a real
baseline.

### Task 0 — the A-0 chores (applied 2026-08-04)

**Changelog graph-only case (A-0 gate item, D-97.1): verified already
applied**, not re-done — `e5d2f51` landed the `changelog.ts` branches
with three tests (`changelog.test.ts`, "graph-only runs describe
themselves"). What remained was the ops half D-97.1 left flagged:
`detail.wheel_only` set on **any** `changed.length === 0` run
(`core/src/pipeline.ts`). Applied as recommended —
`{ wheel_only: !!wheelCarry, graph_only: gatewayPending }` — with two
tests executed against the real pipeline: SO-10's wheel-only half now
also asserts `wheel_only: true / graph_only: false` on the run record,
and a new graph-only case (inserted `lineage_attestations` row → PR
titled "report lineage only") asserts `graph_only: true / wheel_only:
false`, the exact shape run `01KYVXMQ8Q0BAHTKC8WM5WBK5S` stored
wrongly. Both fail without the fix: `graph_only` was previously absent
from the record, and absent ≠ false under the assertion.

**RA-F 80 %-of-limit telemetry (D-96.3e).** The Power BI publisher now
computes ≥80 % proximity — integer-exact, `measured*5 >= allowed*4`, no
float boundary — across exactly the four dimensions it hard-checks
(tables, columns per table, rows per table none-retention,
relationships) and reports survivors in result `detail.limit_proximity`;
the core records a `push_limit_proximity` health event (severity
`warning`, system, job id, artifact id, entries) and the publish
proceeds untouched — proximity is telemetry, never a refusal. Tests:
python — 60/75 columns (exactly 80 %) reported while the delivery
succeeds, default fixture reports no key, rows dimension unit-tested at
4,000,000 and 3,999,999 of 5,000,000; core — scripted adapter proximity
lands as the asserted health row beside an intact delivery record.

**D-96.3 register rows applied** (the post-d96-status list, verbatim):

- **RA-F** re-dated in `report-authoring-spec.md` §13: due 2027-01-31,
  or first `push_limit_exceeded`, or the second Power BI customer —
  whichever first; the tripwire above named in the row.
- **SUPPRESS-1** (master): home ruled — profile `limits.min_cell_count`
  enforced at the publish path's re-validation, disclosed in the
  artifact; trigger tightened to the first report with an audience
  beyond its author (B-1's demos may trip it).
- **BASELINE-1** (master): gate restated — entry condition of the first
  customer conversation that quotes value; the ≈8–13 h estimate recorded
  so the trigger books a two-day block; D-96.5 constraint cross-linked.
- **PA-1 / PA-2** (master): ruled to Track A-2, with the plan's gate
  language (authenticated download against the requester's own binding;
  staleness demonstrated closed by repeating the 2026-07-29 shape).
- **OB-4** (master): D-96.3g BUILD recorded (Track A-6); trigger split —
  targets still wait on the third onboarding, instrumentation on A-6.
- **R-5**: RA-10's design-ruling row in the authoring spec now records
  that the `sp-scope` preflight check *asserts* membership-only (built
  at D-96 task 2; the row had still called it a threat-model statement).
- **Verified already applied, deliberately not re-edited:** SO-F (the
  master row has carried the Track B-1 disposition since D-96.4's
  batch); R-6 (sync spec §10 amendment present at "the manifest is the
  only pin"; closure still rides the operator dropping `workflow` write
  from the sync PAT — unchanged, still open, still the operator's); R-8
  (mechanical since `1b69529`; its one-entry exception list closes at
  task 1 of this session, which is the A-1 gate's business, not a
  bookkeeping edit's).
- **review-sync** stays a finding-with-a-ruling (D-96.3c), not a
  register row: it closes as C-2 when Track A-1 ships it, which is this
  session's task 1.

**Suites at this entry:** python **735 passed / 14 skipped** (+3, the
RA-F tests); core **193 passed** (19 files; +2 — the graph-only run
record and the RA-F health emission; SO-10's new record assertions ride
its existing test).

### Task 1 — `review-sync` ships; C-2 closes (applied 2026-08-04)

**The skill** (`core/skills/review-sync/`): SKILL.md per skill spec §7 —
`ingest → impact → recommendation → [repair-plan]`, with four absolutes
stated as boundaries the product asserts: never merge (CP-V2), never
edit the sync PR (CP-V2), never set `status: verified` (KB-7 — the
skill prepares the diff, the human certifies with their name), rename
candidates stay ambiguous with both interpretations until a human
decides. S4 stages the re-verification diff (clear `contamination`,
refresh `written_against_schema_hash`) while leaving `status` untouched
with a PR-body note telling the human the flip is theirs. Bundled thin
tooling: `triage.py`, a stdlib-only deterministic tree inventory (docs
by status, parsed contamination fields, per-object blast counts, sorted
everywhere) — the compile bundles the whole skill directory, so it
reaches the steward machine.

**Conformance, per the D-78 layering — both layers, layered:**

- *(a) CI validators:* `check_review_summary` in
  `tools/skill_conformance.py` pins CP-V1/CP-V2 over the summary
  structure (verdict consistent with body, breaking-first, both rename
  interpretations per bullet, undeclared refs marked non-authoritative,
  no merge-performing language). 8 staged tests, bads rejected, goods
  passed; plus 2 tests running `triage.py` for real over the drill
  world staged by the real `generator.statuses` stage (counts, the
  two-hop path surviving the front-matter round trip, blast ordering,
  byte-identical double run).
- *(b) AS-7 behavioral, the gate evidence:* **PASS, first run, 7/7**
  (`results/phase2/a1-as7/`, model claude-opus-4-8, cost $2.06). Real
  headless steward session, fixture deployment + a staged drill sync PR
  in a scratch git world where the agent held **unprotected push
  capability** — and every remote ref is byte-identical after; clone
  worktree clean (no `status: verified` anywhere); audit stream shows
  `get_entity → get_metric → get_table ×3 → get_lineage` and zero
  execute/publish despite the profile carrying `execute_sql:drill`; the
  produced summary clears the layer-(a) validator with 0 findings and
  names the rename with both interpretations and the two-hop
  contamination doc. Falsifiability, stated since the run went green
  first try: the validator is red-tested against staged bads, the git
  assertions are live sha comparisons that any push would flip, and the
  audit assertions count real rows — each could have failed if the
  behavior were absent (D-78.2). The agent also surfaced, unprompted,
  the triage-vs-changelog fan-out subtlety and a pre-existing
  placeholder hash in the fixture — recorded in the committed
  `review.md`.
- *Harness fix while here:* `_prepare_workdir` copied only SKILL.md;
  it now copies the whole skill directory (minus `__pycache__`),
  matching what compile bundles — without this, bundled tooling never
  reaches a scenario workdir and "ships inside the skill" is a sentence.

**The two mechanical gate clauses, verified by running them:**
`compile steward` exits 0 and the bundle carries
`enrich/SKILL.md + review-sync/SKILL.md + review-sync/triage.py` — F-7
satisfied by shipping the skill, not by loosening the compile. R-8's
`KNOWN_UNSHIPPED` list is **empty** — the entry's removal was forced by
the exhaustion test exactly as designed; the counterfactual test (an
unlisted missing skill fails both the inventory and the compile) still
runs against a scratch skills root.

**Suites at this entry:** python **745 passed / 14 skipped** (+10);
core **193 passed**.

**A-1 gate status after this entry:** review-sync shipped per §7 with
AS-7 green on behavioral evidence; `compile steward` succeeds honestly;
R-8 green without exemptions. Open: the live drill (task 2), which
waits on the operator's SS-5 drift flush and STOP-1.

RULING D-99 — render-scope defect (authorizes the fix)
(owner ruling, 2026-08-04; recorded verbatim)

1. DEFECT ACCEPTED AS DIAGNOSED: stage-8 render scope must be
   (changed systems) ∪ (systems owning any stage-9 status-written doc).
   Fix authorized at renderInputs, plus the test as proposed
   (cross-system contamination → foreign system's index re-rendered,
   in-run KB-8 covering the widened scope). No other pipeline change.
2. REPAIR IS PRODUCT-NATIVE: after the fix lands and suites are green,
   re-trigger sync now supabase; SY-3 supersedes PR #33 with a
   consistent PR. No hand-commit ever touches a sync branch — affirmed.
3. DECISIONS record: first-ever cross-system contamination; the in-run
   self-check shared the render-scope blind spot and KB CI caught it —
   logged as defense-in-depth evidence.
4. The "15 breaking" wave is the expected SS-5 first-capture semantics
   (checks appearing on ~15 tables), not a second defect. Docs
   declaring depends_on on those tables — including entity docs, and
   possibly the certified page.md — may be legitimately contaminated;
   re-verification where the claims still hold is the correct steward
   response, not an error.
5. BONUS, RECOMMENDED: review the superseding PR using the just-shipped
   review-sync skill — a rehearsal on REAL drift before the staged
   drill, and free field evidence for A-1.

## D-99 application record (2026-08-04)

**The defect, as found on KB PR #33** (`sync: 15 breaking, 4 additive
across supabase` — the SS-5 drift flush). KB CI failed KB-8 on
`systems/ga4/index.md`: `not the render of (latest accepted snapshot,
HEAD enrichment)`. Diagnosis, reproduced locally in a scratch worktree
of the branch: `systems/ga4/dimensions.md` declares
`depends_on: supabase.public.exports` (the custom `export_status`
dimension is grounded in that table; its CHECK migration is cited in the
doc's own `sources`). SS-5 put `stats.checks` on `exports` → breaking
(`stat_changed: checks`) → the scan **correctly** contaminated the ga4
doc across systems and stage 9 wrote its front-matter — but stage 8
rendered only the changed system (supabase), so the ga4 machine index
still said `draft` where the branch's own doc said `contaminated`. The
in-run KB-8 self-check double-renders the same too-narrow inputs, so it
shared the blind spot; **the whole-tree KB CI is what caught it** —
defense in depth doing its job (D-99.3), on the first cross-system
contamination the product has ever produced.

**The fix** (`core/src/pipeline.ts`, renderInputs — exactly the D-99.1
scope, nothing else): render inputs are now (changed systems) ∪ (systems
owning any status-written doc), the foreign systems resolved from the
instruction doc paths through the KB §3 `mangle` rule against the pinned
snapshots. The in-run self-check consequently double-renders the widened
scope.

**The test, red before green** (`sync-run.test.ts`): a second, unchanged
system (the drill schema republished as `demo2`) carries a human doc
with `depends_on: drill.shop.customers`; the drill's breaking handover
contaminates it across systems. Asserted on the PR branch: the doc's
front-matter, the `demo2` schema index row saying `contaminated` (a
system this run never changed), run outcome `succeeded`, and the CI-form
KB-8 — a fresh render over the branch is a byte no-op. **Executed both
ways:** with the fix stashed the test fails; with it, passes (D-78.2
observed, not presumed).

**Suites at this entry:** python **745 passed / 14 skipped**; core
**194 passed** (+1, the D-99 test).

**The repair, executed product-native (D-99.2), same day.** Core image
rebuilt from `468fe87` and recreated with the running stack's own env
discipline (secrets sourced, `SYNC_PLATFORM_COMMIT` = HEAD,
`CL_HOST_ADDR` updated to the machine's current 192.168.1.3 — the IP had
moved again; the compiled reporter bundle now points at a stale address
and needs the operator's re-point before any demo). `sync now supabase`
→ run `01KZ71HGZREBWN6377C8HNBVNF` succeeded → **KB PR #34**, which
SY-3-closed #33 with the successor link. **PR #34's KB CI is green**,
including `systems/ga4/index.md` — re-rendered this run by the fix, now
agreeing with its contaminated `dimensions.md`. No hand-commit touched
any sync branch.

### D-98 task 2 — the live drill record (2026-08-04/05)

Full narrative, timeline, and pointers: `results/phase2/a1-drill/`.
The short form: rename staged on `reporting.v_user_signups_by_day`
(operator as DBA, both DDL files pre-drafted) → drift **PR #35** with
the exact designed shape (1 breaking, the rename candidate with both
interpretations, one-doc contamination) → steward review on the
**first-ever compiled steward bundle**, audit-evidenced (5 rows, all
reads, zero execute/publish/flag_gap) → repair **PR #36** → revert →
mirror drift **PR #38** → **estate byte-identical**, canonical body
`sha256:4ecf4951b540c00b…` equal on both sides of the drill (S-3 held
across apply+revert, including the `v_mart_fact_daily` deparse ripple
both ways).

**Recorded deviations, per the exit-criteria-honesty rule:** (1) #35
merged before the steward review (operator's own act; review became
review-of-record); (2) the verification flip was not made before the
revert, and certifying `signup_date` post-revert would have been false —
**the flip moved to the closing reconciliation**: after #38 merged, the
session prepared the final repair (text back to `signup_day`, sibling
regenerated, hash refreshed) and the operator certified there.

**GATE CLOSED (2026-08-05).** Reconciliation **PR #39** merged with the
operator's own certification commit: `status: verified`,
`last_verified: "2026-08-05 (Alper Camli)"`, hash at the pre-drill value
the estate returned to; the reporting index agrees
(`results/phase2/a1-drill/doc-states/4-certified.md`). A third
same-class field lesson recorded on the way: the hand-made flip tripped
KB-8 on the schema *index* (which renders doc status) and needed one
more generator run — hand edits outside a skill session must end with
`render` + `validate`; CI backstopped all three occurrences. **Every
A-1 gate clause now holds:** review-sync shipped per §7 with AS-7 green
on behavioral evidence; the live drill ran staged break → sync PR →
steward review-sync → repair PR → doc re-verified under the operator's
name, recorded with same-day evidence; `compile steward` succeeds
honestly (F-7 untouched); R-8 green with an empty exception list.
**A-1 closes.** Next per the plan's serial order (§3): **B-0** (read
APIs before pixels), whose entry condition is the dashboard/UI spec.

**STOP-2 field notes (2026-08-04/05, recorded before the drill record).**
(1) **Sequence deviation, operator's own:** PR #35 (the staged break) was
merged by the operator *before* the steward review — the
merge-to-record-reality default exercised early. The gate's substance
(steward runs review-sync → repair PR → human re-verifies) proceeds on
the merged PR; the S3 merge recommendation is retrospective for this
drill. Recorded, not papered over. (2) **First-ever compiled steward
bundle** produced this session (F-7 had blocked every prior attempt) and
used for the STOP-2 session. (3) **Second field lesson, same class as
enrich's oldest one:** repair PR #36 shipped the human-doc edit without
regenerating the machine sibling — the renamed `column_purposes` key
never reached the machine doc's Purpose slot and KB CI failed KB-8. The
regeneration was pushed to the branch (validate 0/0, CI green);
`review-sync` S4 now states the regeneration duty explicitly with the
command pair, marked as a field lesson. Noted honestly: AS-7 is a
review-only scenario, so S4 conduct has no behavioral coverage — the KB
CI backstop is what caught this, again. (4) **PR #37** (operator's
enrich test) is simultaneously the first SS-5 re-verification-campaign
item: `usage_counters` repaired + enriched with customer-stated
free-tier limits, contamination cleared, hash refreshed, status left
`contaminated` for the human flip — the prepared-for-certification
shape, CI green.

**D-99.5 bonus, done:** PR #34 reviewed with the shipped `review-sync`
skill — the first review of *real* drift, same day the skill landed.
Evidence at `results/phase2/a1-ss5-review/` (review + triage output +
method notes): 35 contaminated docs across the 15-object first-capture
wave, all routes declared dependencies, **zero rename candidates**,
`entities/page.md` (the certified doc) untouched, branch discipline
verified (wheel commit stages `.github/vendor/**` only). Verdict:
BREAKING — merge to record reality, then a batched re-verification
campaign per D-99.4. The review passes the CP-V1/CP-V2 validator with 0
findings; nothing was merged and no verified status written. Merging #34
and the campaign are the operator's; the staged drill's STOP-2 remains
the gate act.

# DECISIONS — Phase 2 Track B entry (2026-08-05)

Three owner rulings, recorded verbatim as issued.

**RULING D-100 — A-1 closure affirmed + B-0 entry**
1. A-1 CLOSED as landed (72f406c): C-2 closed, AS-7 behavioral, drill
   rehearsed with the human half performed for the first time,
   deviations and KB-8 field lessons recorded unsmoothed — which is the
   point of a first rehearsal. D-99's cross-system finding stands as
   defense-in-depth evidence.
2. Next checkpoint per the plan's serial order: B-0 — whose entry
   condition is the dashboard/UI spec, authored and merged first
   (spec-first pattern). The spec below is submitted for that purpose;
   on merge, B-0 build is authorized.

**RULING D-101 — enrichment-request queue (authorizes the amendments below;
fence otherwise unchanged; each diff leads its PR)**

1. FEATURE ADOPTED: anyone may submit a knowledge request — a hole or a
   proposal with suggested content; requests land in the steward's
   queue; the steward's verdict (approve / reject-with-reason) changes
   ledger state only; approved items are drafted BY THE ENRICH SKILL in
   batches of ≤10 into ONE PR carrying per-request resolution trailers;
   the steward's merge of that reviewed diff remains the sole
   certification act. Requester text is drafting input, cited as
   "customer-provided, <name>, <date>", never embedded verbatim.
   Batches are cut on demand or at ~10 approved — no immortal rolling
   PR; appending is permitted only to a still-open, still-small batch.
2. FAULT-LEDGER SPEC (additive): kind `enrichment_request` — payload:
   optional target FQN + optional proposal text (LED-R2 scrub + length
   bounds apply; LED-R3 server-set identity; LED-R5 render
   neutralization; LED-R7 counts-only). States: open → approved |
   rejected(reason) ; approved → batched(batch_id) → resolved via the
   existing L-5 CL-Resolves lifecycle on the batch PR's merge —
   trailers resolve every request the batch satisfies; recurrence and
   fingerprint-dedup semantics unchanged. Rejection reasons surface to
   the filer through the same F-10 channel as resolutions.
3. MCP SPEC (additive): flag_gap gains an optional proposal argument
   (same scrub/bounds), so session-side users can submit content
   proposals without the dashboard; server-set identity unchanged.
4. SKILL SPEC (additive): the enrich skill gains queue-driven batch
   mode — input: approved enrichment_requests; grounding rule: the
   approved request is itself a citation of the customer-provided
   class; per-item honesty unchanged (an approved request the skill
   cannot ground beyond the proposal is drafted citing exactly that
   provenance; one it cannot draft at all returns to the queue with a
   note, never guessed); PR body lists request→doc mapping; ≤10 per
   batch; conformance scenario added per the D-78 layering (behavioral
   evidence: approve → batch → PR → trailers → resolution fires).
5. PHASE-2 PLAN (amendment): B-1's gate gains the Knowledge Requests
   queue with DT-11/DT-12, and one end-to-end demonstration: request
   submitted (with proposal) → steward verdict in the dashboard →
   batch delivered → enrich PR merged as R2 → requester sees
   resolution. The dashboard-spec's UI-11 governs.
6. BOUNDARY RESTATED for the record: this feature adds a triage gate
   IN FRONT of the PR flow; it removes nothing from it. Approve ≠
   certify; the diff remains the review; the merge remains the act.

**RULING D-102 — pre-B-0 decisions**

1. BROWSER AUTH: OIDC authorization-code flow at the core (same IdP as
   MCP), server-side session cookie (HttpOnly, SameSite, CSRF-protected),
   identity {subject, roles} resolved through the SAME verifier the MCP
   path uses — no parallel identity code, no dashboard service account
   (UI-2). Logout and session expiry per IdP token lifetimes.
2. STEWARD AUDIT SCOPE v1 = full read. The matrix's "own + team" is
   amended to "all" with the note: no team concept exists in the role
   model; introducing one is a future ruling triggered by the first
   multi-team customer, never a filter-side invention. Reporter = own
   rows only, unchanged. Auditor = B-4, unchanged.
3. UI-A (stack) deferred to B-1 as specced.

**RULING D-103 — B-1 pre-decisions**

1. UI-A: frontend = light SPA (React), built to static assets served by
   the core; no separate frontend server, no client-side permission
   logic, no client persistence (UI-1/2/9 restated as build
   constraints). Component/library specifics proposed by the B-1
   session in ≤5 lines.
2. UI-D confirmed: resolution/rejection surfacing v1 = dashboard badge
   on the filer's next session; in-session surfacing remains a
   skill-side candidate, unbuilt.

**RULING D-104 — A-2 second-human designation**

The A-2 gate's second human = the operator's colleague. Requirements
when it arrives: their own machine, their own identity in the IdP (a
real reporter account, not a shared login — the audit rows must show
THEM), operator hands-off during the journey, and their friction notes
recorded as first-user field notes in the CP-8 style. What they find
is gate evidence, not anecdote.
# DECISIONS — B-0 build (2026-08-05)

Four decisions the B-0 build had to take to implement dashboard spec §5
as written. Each is a recommendation for ratification; none contradicts a
spec or the amendment fence; each is implemented exactly as described, so
the code and this record cannot quietly disagree.

**D-105.1 — UI-B pagination defaults (closes the spec-local item).**
Keyset cursors over each endpoint's stable sort key (audit `(ts, audit_id)`;
deliveries `(delivered_at, artifact_id, target)`; queue `(occurrences,
distinct_subjects, last_seen, issue_id)`). Server default 50 rows, hard cap
200, both config-overridable (`CORE_DASHBOARD_PAGE_DEFAULT`/`_MAX`); an
over-cap request is clamped and reports the size it used, a nonsensical one
is a 400. Audit **retention** is deliberately untouched at B-0: MCP §8 makes
retention and export the Audit module's concern, which is B-4.

**D-105.2 — the ledger read's subject dimension is "who filed".**
DT-1 requires a subject scope on all three endpoints; for the ledger the
only honest one is the filer. A reporter reads the issues they filed —
which is also exactly what UI-D's resolution badge needs — and a crafted
`filed_by` for anyone else is a 403. A steward reads the whole queue.
Recommendation: adopt this as the ledger endpoint's DT-1 shape.

**D-105.3 — per-event `subject` in the §8 issue view is steward-only.**
LED-R7's counts-only rule governs the *queue*, which carries no identity
for anybody, and it stays that way. The issue view's event stream is a
different surface: a steward already reads every audit row's subject under
D-102.2, so withholding it there would be theatre rather than privacy.
Everyone else gets the same stream with the field absent.

**D-105.4 — the read APIs accept a bearer token as well as the session
cookie.** Both are resolved by the same verifier, so identity and filtering
are identical either way; this is what let `extract-audit.sh` become an API
client holding no database credential — only the operator's own identity.
CSRF is required on every cookie-authenticated write, and the cookie always
takes precedence, so presenting a bearer header cannot shed that check.

**RULING D-106 — B-0 acceptance + flagged dispositions**
(owner ruling, 2026-08-05; recorded verbatim)

1. B-0 CLOSED as landed (af31811). The evidence-reproduction standard
   (reload committed evidence into a scratch estate, reproduce byte-
   for-byte) is ADOPTED as the norm for future extractor changes.
2. deferJob COLLISION — ruled: COALESCE, never dead-letter (nothing
   failed). On defer of a leased job when a queued duplicate exists for
   the same (system, type): the deferred instance terminates in a
   coalesced state; the queued job survives and ADOPTS the later
   run_after of the two (the deferral's quota-reset wait must not be
   lost, or the survivor immediately re-hits the same quota wall).
   Additive clarifying amendment to the job-protocol spec (diff leads)
   + queue fix + a JC-series conformance test reproducing the exact
   collision. Rides the next session as task 0.
3. FLAKE RE-ATTRIBUTION: the property.test.ts intermittent from the
   CP-8 record is root-caused to this collision — deterministic repro
   on pristine HEAD is the capture the quarantine demanded. The
   docker-heavy watch item narrows to the container-start-latency
   class only; DECISIONS notes the split.
4. PROPOSAL LENGTH: the alias to description's 500 chars is DECOUPLED
   by intent — proposal bound = 2000 chars. Rationale: suggested
   content legitimately carries enum decodings and structure sketches;
   the defense against data-value dumping is the LED-R2 scrub, not
   brevity. Description stays 500. Ledger-spec one-line amendment.
5. REJECTED-REQUEST RECURRENCE — ruled symmetric with L-4: a new
   occurrence after rejection REOPENS the request to open with the
   prior verdict history preserved and occurrence counts cumulative;
   the steward sees "rejected before, refiled by N more" and may
   re-reject. No threshold sophistication in v1. Ledger-spec
   amendment, same diff.
6. OPERATOR ITEM, precedes A-2: KB PR #34 and the 34 contaminated
   docs. The SS-5 wave's contamination is real steward work, not test
   noise — review with review-sync, merge as R2, then triage the
   contaminated set (re-verify where the claims still hold — most
   will, the CHECK facts largely CONFIRM existing prose). The
   environmental Python test failure clears as a side effect. The
   live-extraction re-run with a steward token: optional, operator's
   convenience.

# DECISIONS — A-2 build (2026-08-05)

Checkpoint A-2 ("setup delivery is a product surface") built to the
point where the remaining work is the operator's and the colleague's.
Task 0 applied D-106; tasks 1 and 2 built the download and the
staleness signal; task 3 wrote the two run artifacts and stopped.
The decisions below are recommendations for ratification; each is
implemented exactly as described, so the code and this record cannot
quietly disagree.

## D-106 as applied

**D-106.2 — the coalesce.** `deferJob` now checks for a queued duplicate
before it re-queues (`core/src/queue.ts`), and when it finds one the
deferring instance terminates in the new terminal state `coalesced`
(migration `0010_defer_coalesce.sql`) while the survivor takes
`GREATEST(its own not_before, now + retry_after_s)`. The job-protocol
amendment leads the diff (§4.3 note, §5 amendment paragraph, JC-11 row);
`JC-11` in `conformance.test.ts` reproduces the exact collision from
PR-B0's write-up — enqueue → claim → enqueue same key → defer — and
asserts the outcome three ways: the deferring job ends `coalesced` with
no `error` recorded, the survivor's wait is the later of the two, and
`{coalesced: 1, queued: 1}` is the whole of the key's state. Two
adjacent cases are pinned beside it: a survivor whose own `not_before`
is later keeps it (GREATEST, not "the deferral wins"), and a deferral
with no duplicate behaves exactly as JC-5 says it does.

*Two judgment calls inside the ruling, both visible in the amendment
text.* (a) **Trigger history merges into the survivor**, marked
`merged_from`, the same way a requeue's absorb already merges it — a
coalesce that dropped the accepted trigger would lose the record of work
the queue accepted. (b) **The §5 deferral cap is checked first**: past
the cap a deferral is already converted to a retryable failure, which is
the existing path and the one that emits the `deferral_cap_reached`
health event, so the coalesce applies to honoured deferrals only. The
survivor keeps its own `deferrals` count; the terminating instance does
not increment anything.

**D-106.3 — the flake split, recorded.** `property.test.ts > dedupe
invariant holds under arbitrary interleavings` is green and is now the
regression witness for the collision rather than a quarantined
intermittent: fast-check generates the offending sequence, and before
this fix that sequence raised `duplicate key value violates
"jobs_dedupe_queued"`. The quarantine standard's remaining scope is the
**docker-heavy container-start-latency** class alone (JC-4's watch item)
— the two were one line in the CP-8 record and are two different things.

**D-106.4 — proposal bound 2000.** `PROPOSAL_MAX` no longer aliases
`DESCRIPTION_MAX`; the ledger-spec amendment states why. The scrub is
untouched, which the tests hold: a 40-item enum sketch survives intact
(it did not at 500) while its bare stage numbers are still dropped, and
an oversized proposal is still bounded.

**D-106.5 — rejection recurrence.** The L-4 upsert's reopening set gains
`rejected`; the verdict columns are deliberately not cleared, and the
dashboard's issue shape gains `reopen_count`, so the queue renders
exactly the sentence the ruling asks for — *rejected before, refiled by
N more*. A steward may re-reject, because the reopened issue is `open`
again and `recordVerdict`'s transition set is unchanged. **Recorded
limitation:** the columns hold the **latest** verdict only, so a second
rejection overwrites the first reason while `reopen_count` keeps the
tally. A full per-verdict log would be new DDL and is not in the ruling;
if the register wants one it is a new item, not a patch.

**D-106.6 — the operator item, as found.** KB PR #34 **is merged**
(2026-08-04); the memory note saying otherwise was stale. The
**triage is not done**: `origin/main` carries **34** docs still marked
`status: contaminated`, so
`tests/test_benchmark_integrity.py::test_no_contamination_in_current_kb`
still fails. That failure is a statement about the estate, not about
this code — it reads the operator's working clone by design — and it
clears when the re-verification campaign runs. Python suite at this
entry: **744 passed / 1 failed (that one) / 14 skipped**.

## D-107 — decisions this build had to take

**D-107.1 — the bundle is compiled on request, never cached.** A
download runs `compileProfile` against the workspace the caller's read
would see and streams the result; there is no stored artifact and no
invalidation rule. Rationale: a cache would need exactly the staleness
machinery D-107.2 builds for the copy on the user's disk, and would add
a second, invisible copy that can be wrong. The compile is milliseconds
of file reads over the core image's own skills, and the KB workspace is
already cached by the reader both surfaces share. **PA-2 implication,
stated plainly:** with no server-side cache, the only stale bundle in
the system is the one already unpacked on someone's machine — which is
the thing the stamp reports and the one-step download replaces.

**D-107.2 — the staleness signal is a compile stamp in the client's own
URL, compared at connection.** `compileProfile` digests everything the
bundle puts on disk (server URL, `CLAUDE.md`, every skill file) into a
16-hex `stamp` and writes it into the compiled `.mcp.json` URL as
`&setup=<stamp>`. The MCP handler recomputes the current stamp for the
resolved profile (cached per KB-state × profile) and, on a mismatch,
returns a `SETUP OUT OF DATE` notice as the server's `instructions` in
the `initialize` result — at connection, before the session forms any
belief about what it may do. Three properties this shape has and a
"recompile on profile change" shape does not: it needs no push channel
to a machine the core cannot reach; it is exact rather than heuristic
(the comparison is over the bytes, so a skill edit counts as much as a
tool grant); and it degrades honestly — a bundle with **no** stamp,
which is every bundle compiled before today including the one that ended
the 2026-07-29 attempt, reports `SETUP UNVERIFIABLE` rather than passing
silently. `GET /v1/setup/status` answers the same question for a
runbook. No MCP-spec surface changed: `instructions` is a transport
field the tool reference does not specify, and no tool result gained a
member.

**D-107.3 — an ambiguous binding is refused, not resolved.** If a
caller's roles bind them to more than one profile, the download answers
`409 ambiguous_binding` naming both and pointing at the operator. No IdP
user wears two bound roles today, so this is asserted on the binding
function rather than over the wire. Picking one silently would ship a
user a smaller product than their roles describe, which is PA-2's
failure shape with a different cause; the role map is a KB PR, which is
where a two-binding identity should be settled.

**D-107.4 — a browser gets the login flow, a script gets 401.** An
unauthenticated `GET /v1/setup/bundle` whose `Accept` carries
`text/html` is redirected to `/v1/auth/login?redirect=…`; everything
else keeps the JSON 401. This is what lets the address handed to a first
user *be the download* — one link, one sign-in, one file — which is the
minimum for "setup delivery is a product surface" to mean anything for
someone who has never seen the system. It is a redirect, not a page: no
pixels were built (B-1 owns those).

**D-107.5 — the core image now ships `core/skills/`** (`core/Dockerfile`).
Found by asking where the compile runs: until today every compile ran
from a developer checkout on the host, where the skills directory sits
beside `dist/` anyway. In the deployed image it did not exist, so the
first real download would have answered `503 setup_uncompilable` —
F-7's refusal, telling the truth about the image and a lie about the
release. Verified in the built image (`listShippedSkills()` → benchmark,
enrich, report, review-sync), not merely in tests that run from source.

## Live rehearsal, 2026-08-05 (no gate claims — the operator's identity)

The build was exercised against the running pilot stack, rebound to the
operator's current address, before any of it is put in front of a second
human. What the deployed stack did: `401` for a script and `302` into
the login flow for a browser; the full browser path (one URL → IdP form
→ callback → cookie → download) served `contextlayer-setup-reporter.tar.gz`,
4 files, 17 269 bytes, stamped `01cb2be8a19b372d`, on the cookie alone;
`/v1/auth/session` reported the signed-in subject, and the steward
identity got the *steward* bundle from the same URL (both live bindings
resolve to exactly one profile). The staleness probe answered all three
ways against the real KB (`kb_ref 5d99f41`): current stamp → no notice,
wrong stamp → `SETUP OUT OF DATE`, absent stamp → `SETUP UNVERIFIABLE`.
A credential scan of the delivered archive against every value-shaped
string in `.secrets/` returned one hit, `looker_studio` — a target name
in the profile's tool list, not a credential. **This is a rehearsal of
the mechanism, not gate evidence:** the identity was the operator's.

**Finding, security, raised by that rehearsal (not a spec matter, no
fence question — recorded so it is not discovered during the run).** The
pilot's dev IdP accounts live in `deploy/oidc/users.json`, and that file
with its three default passwords is **published in the public release
repo** (`AlperCamli/DataAnalyticsTool`). Binding the stack to anything
but `127.0.0.1` — which the A-2 run requires — therefore exposes a
steward login to everyone who can reach port 8180, and on a campus or
office network that is not a small set. Mitigation is one edit and a
`docker compose restart devidp`; it is now act **3.0** of the runbook,
mandatory before any non-loopback binding, with the un-binding step for
afterwards. The deeper fix is the A-4 vault work and a real IdP; this is
the interim rule.

## What is NOT closed by this entry

The A-2 gate has a human half that no session can run: **the second
human's journey**. `results/phase2/a2/` carries the two artifacts it
needs — `COLLEAGUE-BRIEFING.md` (one page, plain language, the two
rules) and `A2-RUNBOOK.md` (dual-shell, per-act success criteria, the
operator's hands-off discipline and note format) — and the run stops
there by ruling D-104: their own machine, their own identity, the
operator silent. Evidence extraction, field notes, and the gate check
are the task that follows the run, not part of this build.

**Suites at this entry:** core **267 passed / 24 files** (+17 on B-0's
250: 3 JC-11, 2 ledger amendments, 11 setup/staleness, 1 compile stamp);
python **744 passed / 14 skipped / 1 failed** — the estate-state failure
above, unchanged by this work.

RULING D-107 — A-2 build acceptance + flags
(owner ruling, 2026-08-05; recorded verbatim, 2026-08-06 — see the
recording note below)

1. Task 1/2 proposals AFFIRMED as built: compile-on-request (no cache
   — a cache is a second copy that can be wrong), stamp-compare at
   initialize, SETUP UNVERIFIABLE degradation for pre-stamp bundles.
   The instructions-field transport note accepted: no MCP-spec surface
   changed, none needed.
2. D-106 judgment calls (trigger-history merge into survivor; deferral
   cap checked first) AFFIRMED as stated in the amendment text.
3. VERDICT HISTORY: register item filed (home: ledger spec) —
   per-verdict log vs latest-only; current shape (latest verdict +
   reopen_count) ACCEPTED for v1; trigger: the first dispute over a
   prior rejection reason, or B-1's queue UI wanting history display,
   whichever first.
4. JOBS RETENTION: register item filed (home: job protocol) — no
   retention rule exists for terminal rows (coalesced included);
   trigger: first deployment where the jobs table's growth is
   operationally visible; decide sweep semantics then, consistent with
   the ledger's 90-day event precedent.
5. A-2 remains OPEN pending the colleague run per the runbook (O-1
   creates the real identity first — a shared login voids gate claim
   4) and task 4's evidence. The contamination triage (D-106.6) stands
   as prior operator work: 34 docs, review-sync in hand.

RULING D-108 — A-2 closure
(owner ruling, 2026-08-06; recorded verbatim)

1. GATE CLOSED on the extracted evidence: all four clauses met —
   authenticated download authorized server-side, no credential in the
   bundle, staleness demonstrated (harness regression + SETUP
   UNVERIFIABLE degradation), and the second-human journey with
   subject=eda on all 11 rows, zero operator rows in the window.
   The 8m41s sign-in-to-first-question figure is recorded as the
   first measured onboarding number (OB-4-adjacent evidence).
2. EXECUTION SHAPE, operator statement for the record: execution was
   available to the session and unattempted, not blocked; capability
   is separately proven (M2/M3). What happened in the room:
   [ONE SENTENCE: e.g. "she was satisfied with the validated SQL" /
   "she didn't realize she could ask for results" / "unobserved"].
   Recorded as finding A2-F1: a first user's natural stopping point
   was validated SQL, not results — input to B-1's surfaces and the
   report skill's phrasing, not a defect.
3. FRICTION NOTES: [PASTE RAW NOTES / or: "none were taken"]. If none:
   recorded as finding A2-F2 — the observation half of the first-user
   run was lost; the A2 runbook gains a line making notes a named
   operator artifact for any future run.
4. STAMP-IN-AUDIT GAP accepted as filed: audit rows cannot prove which
   setup stamp a session presented. Register item PA-3 (home:
   dashboard spec §5 / MCP audit fields) + the cheap fix AUTHORIZED to
   ride the next session's task 0: the audit record gains the
   presented stamp (or "unstamped"), extractor updated. Closes the
   PA-2 evidence story properly.
5. A-2 marked CLOSED in the plan; field notes and evidence committed
   under results/phase2/a2-field-notes/ per the runbook.

**Recording note (A-3/B-2 session, 2026-08-06).** Both rulings above
are transcribed as issued. Two of D-108's clauses arrived with their
placeholders unfilled — clause 2's one-sentence operator statement and
clause 3's friction notes — and this session did not fill them: an
invented sentence about what happened in a room no session was in is
the one thing a decisions record must never contain. They stay
bracketed until the operator writes them, and the two findings they
govern (A2-F1, A2-F2) are conditional on that text. What this session
*did* execute is D-108.4 (the stamp-in-audit fix, task 0 below) and
D-108.5's plan half (A-2 marked CLOSED). D-108.5's field-notes half
cannot be executed here for the same reason: `results/phase2/a2-field-notes/`
is the operator's write, and it is empty. **D-107.3 and D-107.4 are
recorded above but their register rows are NOT filed** — the register
carries no VERDICT-HISTORY or JOBS-RETENTION item today; filing them is
outside this session's amendment fence and is flagged, not done.

# DECISIONS — A-3 + B-2 (Connections are operable; the first pixels), 2026-08-06

The paired checkpoint. Task 0 recorded D-107/D-108 and built D-108.4's
stamp-in-audit fix; tasks 1 and 2 built the Connections API and the SPA
that faces it; task 3 rewrote playbook step 3 to the shipped surface;
task 4 wrote the operator's gate runbook and stopped. Each decision
below is implemented exactly as described, so the code and this record
cannot quietly disagree.

## D-109 — decisions this build had to take

**D-109.1 — the read-back lives in the registry, not the handler.**
`upsertSyncSystem` (and `deleteSyncSystem`) now write, re-read through
the ordinary read path, compare, and throw `RegistryWriteNotObserved`
when the store disagrees. The API handler therefore has no value to
answer with except the one the store handed back — there is no line in
`connections.ts` that echoes the request body. The alternative (verify
in the handler) was rejected for one reason: a verification only the
production path performs is a verification the next writer skips, and
D-84's cost was paid twice by two different writers. Every writer in the
codebase now inherits it, tests included. **Proved by making the failure
happen**: a `BEFORE INSERT OR UPDATE` trigger returning NULL reproduces
the exact D-84 shape — no error, no row — and the API answers 500
`write_not_observed` rather than 200.

**D-109.2 — ops writes, steward reads, and `adminRoles` is a distinct
config from `opsRoles`.** Registering a source is provisioning, which is
the playbook's R3 (`oidc_group: ops`), not the steward's context work.
`CORE_DASHBOARD_ADMIN_ROLES` defaults to `ops` and is deliberately not
`opsRoles` — that list defaults to `ops,steward` because it opens the
whole job/ops HTTP surface, and reusing it would have collapsed exactly
the split A-3's gate asks for. No new role was invented: `ops` is
already in the pilot's `roles.yaml` and in the ops-surface config, which
is UI-4's rule (the dashboard never knows a role the server doesn't).

**D-109.3 — the probe is the SDK's builtin, over surfaces that already
existed.** `test_connection` (job §4.2, `implemented` at last) dispatches
to a new engine in `connectors/sdk/runner.py` that runs the config gate
plus each declared capability's preflight. `QueryExecutor.preflight`
already existed (G3's startup check); `MetadataProvider.preflight` is its
symmetric twin, with a **no-op default**, implemented for postgres by
reusing `_live_dsn` + `_connect` + `check_introspection_role` (the two
things every live snapshot job does first) and for ga4/gsc by making the
one API call their `introspect` makes first. No new credential path
exists: the runner resolves references exactly as it does for a snapshot
job. `health_probe: builtin` — already in the manifest schema and in the
capability spec's reference manifest — is how a connector opts in, and
it is now declared on all six.

*The honesty rule inside it.* A capability whose handler implements no
preflight is reported `unprobed`, never counted as a pass. Looker Studio
and Power BI therefore answer `unprobed: [publish]` today, because CI-5's
tenant probe is unbuilt. A green tick beside a connection nobody has ever
successfully used is the precise failure this checkpoint exists to
prevent, and it would have been one line of convenience to ship it.

**D-109.4 — health has four states and "not a sync source" is one of the
readings.** `sync-policy.yaml` is the declaration of which systems are
snapshotted. A registered connection absent from it — a publish target —
will never hold an accepted snapshot, so freshness cannot be its verdict;
its last job is. **Found by the live check, not by reasoning**: the first
run against the pilot reported `looker_studio` and `powerbi` permanently
`amber / never_snapshotted`, which would have made playbook step-3's
"health green" exit unreachable for two of five connections and taught
the operator to ignore the colour. The four states stay four (green /
amber / red / unknown); what changed is which question each connection is
judged on. `unknown` remains a real answer: an unreadable
`sync-policy.yaml` is reported as such rather than defaulted to green.

**D-109.5 — references are refused by shape as well as by name.** A
write carrying `config.dsn`, `client_secret`, `password` and the rest is
refused with `raw_secret_rejected` naming the field and its indirection
twin; so is any string value shaped like a URI with an embedded
password, a PEM key, or a service-account JSON, wherever it appears. The
refusal **never echoes the value** — an error message is a thing people
paste into tickets. `vault://` is accepted alongside `env://` now, so
A-4 changes the resolver and not this validation. Reads are deliberately
not gated the same way: the existing pilot rows must remain readable and
testable unchanged, which the live check confirms they are.

**D-109.6 — the module map is a server answer; the client has no role
model.** `GET /v1/dashboard/modules` resolves `.contextlayer/dashboard.yaml`
against the caller's OIDC roles server-side and returns the list; the SPA
renders it. DT-2 is asserted two ways: the **shipped bundle** contains no
role name and no role-check shape, and the app's **own sources** contain
no raw-HTML escape hatch, no browser storage, and no password input. A KB
with no `dashboard.yaml` (the pilot's, today) gets the shipped default
and the response *says* `config_source: default` — an operator who edits
that file and sees no change can tell it was never read without opening a
log. A KB that declares `role_views` and says nothing about a caller's
roles shows them nothing: the narrow reading, so a half-applied config
never looks fully applied.

**D-109.7 — component and library specifics (D-103 allows ≤5 lines).**
React 18 + TypeScript, bundled by **esbuild** (`web/build.mjs`, ~30 lines)
to `web/dist/{app.js,app.css,index.html}`, built in the same Docker stage
as the server that serves it. **No router, no component library, no state
library, no CSS framework** — `fetch` plus `useState`/`useEffect`, one
hand-written stylesheet, one `history.pushState` route switch. The whole
client is five files; that is the ceiling this ruling should be held to
until a screen genuinely needs more.

**D-109.8 — `/healthz` reports `dashboard_enabled`, and the runbook's
first act was wrong.** Found by the operator, immediately, on the first
reading of `GATE-RUNBOOK.md`: `/app/` answered 404 while `/healthz` said
`ok`. Nothing was broken — the core had been recreated by a
`docker compose up` that did not carry `CORE_MCP_ENABLED=1`, so the
dashboard was never registered. **This is D-84.2's shape a third time**
(`environment:` in `docker-compose.yml` outranks the overlay's
`env_file:`, so an unsourced env silently disarms a surface), and my own
Act 0 reproduced it: it gave the plain compose lines rather than the
`set -a; . .secrets/sync.env` form `make stack-live` uses. Both halves
are fixed — the runbook's commands, and the instance packet, which now
states `dashboard_enabled` beside `mcp_enabled` and `sync_enabled` for
exactly the reason SO-F gave for the latter. A surface that can be
silently off must be checkable without reading the process environment.

## What the live check found (2026-08-06, pilot stack)

All five existing pilot rows read through the new API **unchanged** and
all five probe **pass**: `supabase` green (introspection role verified
non-superuser/non-BYPASSRLS, execution role's write-wall verified),
`ga4` and `gsc` pass on one real API call each while their *snapshots*
read **red / stale** (16 days and 5.5 days against 3-day thresholds — a
true statement about the estate, surfaced by this build rather than
caused by it), and the two publisher adapters pass with `publish`
unprobed. `/app/` serves, `/` redirects to it, and the module map answers
`config_source: default` because the pilot KB carries no `dashboard.yaml`.

## What is NOT closed by this entry

**The A-3/B-2 gate demo is the operator's** and no session can run it:
signing in as a person, reading five health states, pressing test, adding
and removing a scratch connection, and writing down every place the
product failed to explain itself. `results/phase2/a3-b2/GATE-RUNBOOK.md`
is the page; `extract-connections.sh` beside it pulls the evidence
through the governed APIs, holding no database credential.

**Two things this build deliberately did not do**, both flagged rather
than quietly absorbed: connection CRUD writes are **not** in
`audit_records` (that table is specified as one row per MCP call; the
durable record of a dashboard act today is the job's trigger actor), and
the capability spec has **no `test_connection` section** — the builtin
probe's two preflight surfaces are shipped and undocumented there.

**Suites at this entry:** core **286 passed / 4 skipped / 27 files** (the 4 skipped are `connections-live.test.ts`, which runs only against a stack named by `CL_LIVE_API` — it was run, live, and is recorded above); python **748 passed / 14 skipped / 1 failed** — the 34-doc contamination triage, estate state, unchanged by this work.

## D-110 — A-3 + B-2 closure + dispositions (owner ruling, 2026-08-06)

**Numbering, first, because the ruling arrived as "D-109" and D-109 was
already taken.** The A-3/B-2 build session recorded its own decisions as
`## D-109 — decisions this build had to take` and landed them in
`ec1987b`; the Phase-2 plan's A-3 entry cites "DECISIONS D-109" for that
build. The owner's closure ruling for the same checkpoint, written
against a working copy believed to end at D-108, reused the number. Two
D-109s with different clause contents would make every future citation
ambiguous, and the build-side one is already cited in a plan document, so
**the ruling is recorded here as D-110** and the build decisions keep
D-109. Clause mapping is one-for-one: the ruling's clause *n* is D-110.*n*
(so the authorized compose fix is **D-110.2**, the capability-spec section
is **D-110.3c**, the operator debts are **D-110.4**). This renumbering is
bookkeeping — no clause's content was altered, and nothing else in the
ruling was interpreted.

**D-110.1 — A-3 + B-2 CLOSED as landed** (`ec1987b`, `3d75251`). E2 closed,
U-1 served. Affirmed by name: the read-back in `upsertSyncSystem` (every
writer inherits it), `write_not_observed` over a 200, and the
publish-target health model fix — a connection absent from
`sync-policy.yaml` is judged on its last job, which is correct, and the
amber-forever shape it replaced would have failed step-3's exit for every
future customer, not just for the pilot's two publisher rows.

**D-110.2 — compose-env precedence is a structural defect, and the fix is
applied.** Third occurrence (D-84.2 sync-off for two days; D-109.8
dashboard-off behind a healthy `/healthz`; one earlier). Ruled: not
operator error. The rule now has a statable form —

> a value a **deployment supplies** lives in an env file; only a value
> **this compose file computes** lives in `environment:`.

*As applied.* Every feature toggle left `environment:` for
`deploy/core.defaults.env` (all off), which overlays outrank by plain
list order: `core.defaults.env` → `deploy/core.live.env` (committed;
live mode arms MCP + dashboard) → `.secrets/sync.env` (the pilot's own)
→ `deploy/baseline/<condition>.env`. `make stack-live` no longer sources
anything into the shell, and `make stack-mcp` became an overlay
(`deploy/compose.mcp.yml`) rather than a shell assignment. Verified by
`docker compose config`: the live overlay resolves `CORE_MCP_ENABLED=1`
and `SYNC_ENABLED=1` with an empty shell, and the baseline overlay still
inverts sync to `0` on top of it — now by list order rather than as a
side effect of `environment:` ranking.

**One thing this ruling forced that its text did not anticipate.** The
obvious escape hatch — a bare pass-through entry, `environment:
[- CORE_MCP_ENABLED]`, which reads as "shell wins if set, env file
otherwise" — **is the same defect wearing a different hat**. Compose
resolves the unset case to null and the container ends up with the
variable *unset*, wiping the env-file value rather than deferring to it.
Verified at runtime, not assumed, and kept as a test
(`test_a_bare_passthrough_entry_is_not_an_escape_hatch`) so the next
person who reaches for it finds the answer instead of the two silent
days. Consequence: **there is no shell override for a toggle any more**,
which would have quietly broken `CORE_MCP_ENABLED=1 make stack-live` —
three checkpoints of muscle memory. So the habit was made loud instead of
silent: `deploy/check-toggle-env.sh` runs ahead of every `make stack-*`
target and refuses to start, naming the toggle and where to set it. That
guard is the honest half of removing the hatch; without it this ruling
would have traded one quiet failure for another.

*Effective-flags reporting*, the ruling's second half: `/healthz` now
reports the **whole** toggle set rather than three hand-picked fields,
from `FEATURE_TOGGLES` in `config.ts` — so a toggle added to the core
without a line in the health packet is a failing test, and no future
surface can be both silently off and unreportable. The set is a
three-way contract (`config.ts` reports it, `core.defaults.env` supplies
its off-state, `check-toggle-env.sh` refuses a shell export of it) and
`tests/test_compose_env_passthrough.py` asserts the three agree, so
adding a toggle costs three lines or a red test. `migrate_on_start`
joined the packet as the first beneficiary.

**D-110.3 — register filings.**

- **(a) Governance writes leave no audit row.** Filed, home
  `specs/dashboard-spec.md` §5.1, pointer on register row U-12. Stated as
  the shape rather than the symptom: `audit_records` is specified as one
  row per *MCP call* and is faithfully that, so connection CRUD — and
  every governance write B-2/B-3 adds after it — lands nowhere. The
  durable trace today is the job's `triggers` array, which exists only
  where a job exists; a registration that enqueues nothing leaves
  nothing. Not fixed here because the fix is a schema ruling (widen
  `audit_records` and re-read its every consumer, or add a second
  governance-write table at the read API), and inventing that inside a
  build session is how a spec gets contradicted silently. **Trigger,
  normative: MUST close before B-4's audit view ships.** An audit view
  that renders MCP calls and omits the writes that changed who can reach
  what is not incomplete, it is dishonest — in exactly the register the
  auditor role exists to read. B-4's gate inherits the clause.
- **(b) D-107.3 verdict history and D-107.4 jobs retention** — filed as
  recorded, dashboard spec §5.2, so B-4 meets them as known open items
  rather than rediscovering them.
- **(c) Capability-spec `test_connection` section** — additive amendment
  applied as authorized: `specs/capability-interfaces-spec.md` §3.1
  documents the probe's three preflight surfaces (`metadata`, `query`,
  `publish`), its result shape, its failure mapping, and the `unprobed`
  contract as **normative** — `unprobed` is not a pass and no consumer
  may render it as one. Placed under §3 (where `health_probe` is
  declared) rather than given a capability section of its own, because
  §11's conformance table and §12's register are cited by number in this
  file and renumbering them to make room would strand those citations.
  Conformance rows **CC-14/CC-15/CC-16** were added for coverage that
  already existed and was undocumented — the three probe tests in
  `tests/test_sdk_runner.py` are tagged to them. No behaviour changed;
  this documents what A-3 shipped.

**D-110.4 — operator debts, verified against the live stack at the head
of this session.** None blocks A-4's build; all three block honest books.

- **(a) D-108 clauses 2/3.** `results/phase2/a2-field-notes/` does not
  exist — not empty, absent. The clauses' placeholders are unfilled. One
  sentence on the room plus the raw notes, or "none taken" → A2-F2.
- **(b) The contamination triage.** 34 docs, review-sync in hand, D-106.6
  standing; still the python suite's one red
  (`test_no_contamination_in_current_kb`).
- **(c) The two red rows.** Confirmed live through the governed API: `ga4`
  red at 1 416 318 s stale (16.4 days) and `gsc` red at 477 089 s
  (5.5 days), both against 3-day thresholds. `supabase` green/fresh, the
  two publisher rows green/`not_a_sync_source`. All five last probes
  succeeded, so this is staleness, not breakage — the dashboard surfaced
  it and acting on it is the loop the product exists for.

*Live state at this entry:* core healthy, `/app/` 200, `/` 302,
`mcp_enabled` / `sync_enabled` / `dashboard_enabled` all true, five
connections registered, 18 `test_connection` jobs on record including the
`scratch-demo` add-test-remove leg of the gate demo (`dead_lettered
auth_error`, which is the re-auth path firing). Every pilot credential is
still an `env://` reference — the surface A-4 migrates.

## D-111 — decisions this A-4 build had to take

A-4 has one gate sentence and it hides a design: *one vault resolver
behind the existing `resolver:` seam*. The seam has existed since CP-3a
and was written for exactly this, so the runner half was small. What was
not small: the core never had a seam at all, the migration has to be
incremental rather than a cut-over, and the pilot's end state — no
plaintext credential files — turns out to have a prerequisite nobody had
written down. Each decision below is implemented as described.

**D-111.1 — the reference shape carries no version pin, deliberately.**
`vault://<mount>/<path>#<field>`, identical in the Python resolver and
the TypeScript one, with KV v2's `/data/` segment inserted by the
resolver rather than written into the reference (so a KV version change
rewrites one line, not every registry row). The rejected alternative was
`?version=N` support: it is one parameter, it is what the API offers, and
it would have made A-4's own gate unprovable. **A pinned reference is a
rotation that silently does not take** — write the new value, watch
nothing change, go looking in the wrong place. That is D-84.2's family,
and this checkpoint exists partly to stop paying into it. Always-latest
is the contract, and the rotation test asserts it.

**D-111.2 — two identities, two policies, not one platform role.** The
core reads `secret/contextlayer/core*`; the runner reads
`secret/contextlayer/connections/*`; neither can read the other's. A
single role would have been four lines shorter and would have given the
runner — the process that executes customer SQL — a read of the KB git
token, which is push access to the customer's knowledge base. Verified in
both directions against a real Vault, not asserted.

**D-111.3 — `env://` is retained, marked PILOT-ONLY, and made visible.**
The seam routes by scheme (`SchemeRouter`), because A-4 flips references
one connection at a time and a runner mid-flip holds both kinds. Three
things keep "retained" from decaying into "supported": the module
docstring and the playbook both say pilot-only in those words; every
`env://` resolution logs a warning naming the reference (never the
value), so the remaining plaintext-backed credentials are a `grep` rather
than an assumption; and `resolver.allow_env: false` turns a surviving
`env://` reference into a hard error. That flag is what makes "the estate
is migrated" a mechanism instead of a claim.

**D-111.4 — the core resolves its config at boot, all-or-nothing, and
generically.** Any config value that *is* a `vault://` reference is one —
no hand-maintained list of "the secret variables", because such a list
goes stale the first time someone adds a config value and the failure
mode is a secret that silently stays plaintext because its name was not
on it. The first unresolvable reference throws, naming the variable and
the reference, and the process exits. A core on half its secrets fails
later, elsewhere, with a worse error; this is S-6's all-or-nothing
reasoning applied to boot.

**D-111.5 — `/healthz` reports vault reachability and seal state, and no
address.** `configured`, `reachable`, `sealed`, `initialized`. `sealed`
earns its place because a persistent vault seals on every restart and
that is the single commonest way this breaks; it is a fact about
infrastructure, not a secret. The address is deliberately absent —
`/healthz` is unauthenticated, and an internal URL there buys the
operator nothing they did not already type.

**D-111.6 — the JC-8 canary was re-pointed, not duplicated.** The same
test that has guarded credential injection since CP-3a now seeds its
canary into vault, resolves it through `VaultResolver` under an AppRole
login, and keeps every original assertion. A second canary beside the old
one would have proved the vault code works while leaving the *runner's
actual path* covered by the old one; moving it is the claim.

**D-111.7 — the pilot needs a persistent vault, which the ruling's text
did not anticipate.** Dev-mode Vault is in-memory. Harmless in the dev
stack, where the secrets are toys — and destructive at A-4's own final
step, because reducing `.secrets/` to the bootstrap remainder deletes the
only other copy. A reboot would then have cost a re-provisioned Supabase
role, Google service-account key and Power BI secret.
`deploy/compose.vault-file.yml` ships file storage on a named volume, and
**the runbook gates `rm .secrets/runner.env` on it being in use with the
unseal key stored off this disk.** The cost is stated rather than hidden:
that vault seals on every restart and there is no auto-unseal without a
cloud KMS. Recorded as finding A4-F2.

**D-111.8 — the migration is a script, because the module cannot edit.**
The B-2 Connections module ships Add, Test and Remove, and renders no
`config` on the card. Changing one reference through the UI therefore
means retyping a config JSON that the screen will not show you. On five
connections that is five chances to drop a config key silently. The
runbook uses `results/phase2/a4/flip-references.sh` — the same governed
API, read-modify-write, dry-run by default, verifying A-3's read-back
after each write. **This is a missing screen, not a broken API**, and it
is filed as **A4-F1** against B-1/B-2 rather than absorbed: until a
connection can be *edited* and its config *seen*, A-3's "wired without a
DBA shell" is true for creating a source and not for changing one.

**D-111.9 — the compose fix's escape hatch had to be closed too.**
Recorded under D-110.2 as applied, and repeated here because it is a
build decision: a bare pass-through entry (`environment: [- CORE_MCP_ENABLED]`)
is not a safe shell override — compose resolves the unset case to null
and the container gets the variable *unset*, wiping the env-file value.
Verified at runtime. So there is no shell override at all, and
`deploy/check-toggle-env.sh` makes the old habit loud instead of silent.

## What A-4 does NOT close

**The migration itself is the operator's** and no session can run it: it
moves real credentials, and one of its steps deletes the last plaintext
copy of them. `results/phase2/a4/VAULT-MIGRATION-RUNBOOK.md` is the page;
`flip-references.sh` beside it does the reference rewriting through the
governed API and holds no database credential.

**Task 4 is blocked behind that run** — the rotation proof, the
`.secrets/` inventory with a reason per surviving line, the post-run
playbook §4 check, the gate check against the plan's A-4 text, and
closure. Playbook §4 has been rewritten to the shipped reality now
(vault-first, `env://` and `.secrets/` marked pilot-only in those words,
the bootstrap remainder named as two files); what the operator's run adds
is whether it is *true* — §4.1 was written from the build, and only a
person following it can say where it lies.

**What is verified, and how:** the runner resolver and the core loader
against a **real Vault container** — AppRole login, KV v2 read, token
reuse and re-login on expiry and on revocation, a rotated value picked up
with no restart, the policy split refusing in both directions, boot
refusing to proceed half-resolved, and no secret in any error message.
What is *not* verified is any of that against the pilot's own
credentials, which is precisely what STOP-1 is for.

## D-112 — A-4 build acceptance + STOP-1 (owner ruling, applied 2026-08-06)

Recorded as issued. Clause 1 affirms the D-110/D-111 renumbering; clause
2 authorised the commit to `main`; clause 3 affirmed the toggle fix
including the removed shell-override hatch and the no-version-pin call;
clause 4 filed A4-F1 to B-1, accepted A4-F2's file-backed vault + runbook
gate ("this finding likely saved the pilot's credentials"), and recorded
A4-F3 as a caught-by-running lesson; clause 5 authorised STOP-1.

**STOP-1 ran the same day, operator-driven, with the terminal work
delegated to the session at the operator's request after repeated
copy-paste failures.** That delegation is itself recorded rather than
smoothed over: the operator performed acts 1–3 by hand and generated
three findings doing so, then handed over. The DDL half stayed theirs
throughout (the `ALTER ROLE` in Supabase), as did the decision to delete
the last plaintext file.

**Gate, clause by clause — all four met.**

1. *One vault resolver behind the existing `resolver:` seam, JC-8 canary
   green through it.* `VaultResolver` + `SchemeRouter` behind the CP-3a
   seam; the canary re-pointed, not duplicated. Verified live against the
   pilot's own credentials, not only fixtures.
2. *`.secrets/` path marked pilot-only in the playbook.* §4.1, in those
   words, with `env://` marked pilot-only in the module docstring too and
   made mechanical by `resolver.allow_env: false`.
3. *Playbook §4 matches reality.* Followed literally on the pilot. It did
   not match in seven places — that is what the findings are.
4. *Rotation of one credential through the vault path verified live.* The
   exec-role password, `results/phase2/a4/ROTATION-EVIDENCE.md`. The
   load-bearing step is the failure before the write: with the old DSN
   still in vault the probe returns `auth_error`, which is what proves
   the runner reads from vault rather than a file.

**End state, verified with zero plaintext credential on the host:** all
five connections `vault://` and probing `succeeded`; the core resolving
`SYNC_GIT_TOKEN` at boot; the G3 preflight resolving from vault; a
governed execute returning rows; `env://` resolutions since restart, 0.

**Seven findings, and the shape they share.** A4-F1 (no edit affordance
in Connections → B-1), A4-F2 (dev-mode vault is in-memory; the file-backed
overlay and the gated deletion), A4-F3 (a Vault policy glob does not
cover its own prefix), A4-F4 (shell-sourcing an env file ≠ Compose's
parse; the Google key arrived 44 bytes short and invalid), A4-F5 (browser
sign-in fails on a same-machine stack — playbook §4's exit condition
failing as written, filed to whichever checkpoint owns the install
story), A4-F6 (the G3 execution preflight never went through the
resolver), A4-F7 (`/favicon.ico` answered 401).

Five of the seven are the same shape: **a step whose failure was
invisible.** The listener race looked like a broken vault; an empty
`read` looked like a completed one; a shell-sourced credential looked
identical to a working one; a silently-withheld `execute` sat behind five
green probes. That is the D-84 family, and A-4's own instrumentation is
what surfaced each of them — the loud boot failure, the `unprobed`
contract, the `PILOT-ONLY` log line, the effective-flags packet.

**A4-F6 deserves its own sentence in the record**, because it is the one
that would have shipped. The G3 execution preflight read
`execute_dsn_env: CL_EXEC_DSN` — a plaintext credential by construction —
and consulted no resolver, so it was the single credential path A-4
missed. It kept working for exactly as long as the plaintext file sat
beside it, and its failure mode is governed execution *silently
disappearing* while every visible surface stays green. It was found by
deleting the plaintext, which is the whole reason act 8 exists as a step
rather than a cleanup. **A migration is complete when the old source is
removed, not when the new one works.**

**Not closed, and owed by the operator:** the unseal-key rekey and root-
token revoke (both passed through a chat transcript during the run; a
rekey was started and deliberately **cancelled** rather than completed,
because completing it in-session would have put the new key in the same
transcript), and the four "owed" rows in
`results/phase2/a4/SECRETS-INVENTORY.md` — helper files still holding
copies of values vault now owns.

**Suites at this entry:** core **306 passed / 4 skipped / 28 files**;
python **777 passed / 14 skipped / 1 failed** — the contamination triage,
now **35** docs, estate state, untouched by this work.

# DECISIONS — B-1 (KB Health, Gap Triage & Knowledge Requests), 2026-08-06

The dashboard's second and third modules, the two read views beside them,
and the enrich skill's queue-driven entry. Task 0 recorded D-113, resolved
D-108's two bracketed clauses on the operator's attestation, and made
playbook §4's exit condition true for the install shape A4-F5 found.

## D-113 — A-4 closure + standing rules (owner ruling, 2026-08-06)

Recorded as issued.

1. **A-4 CLOSED as verified.** All four gate clauses, zero plaintext on
   host, rotation proof live, `env://` fallbacks zero. A4-F6's fix
   affirmed: G3 routes through the same credential path jobs use — one
   path, not two.
2. **STANDING RULE ADOPTED**, beside fan-out and read-back: *a migration
   is complete when the old source is removed, not when the new one
   works.* Removal is the test that finds the missed path. Filed in the
   standing-rules list below.
3. **TRANSCRIPT HYGIENE AFFIRMED.** The in-session rekey cancellation was
   correct — secret-bearing ceremonies run out of band, never through a
   transcript. Recorded as practice.
4. **A4-F5 playbook amendment AUTHORIZED** to ride this session's task 0.
   Executed: see D-113.4-as-applied below.
5. **FINDINGS FILED AS FILED**, incl. A4-F1 → inherited by B-1's build.
   Executed: see D-114.6.
6. **SECRETS-INVENTORY debt rows ACCEPTED** as honest bookkeeping; purge
   per the operator queue, inventory updated to the true bootstrap
   remainder after. **Operator-owned; nothing in this session touches it.**

### The standing rules, as they now stand

Three, and each was bought with a failure:

| Rule | Bought by |
|---|---|
| **Fan-out**: a value that appears in two places will disagree in one of them | the D-84 class |
| **Read-back**: a write is reported as it was read back from the store, never as it was submitted | A-3's claimed-registered-actually-absent shape |
| **Removal** (new, D-113.2): a migration is complete when the old source is removed, not when the new one works | A4-F6 |

### D-113.4 as applied — playbook §4's exit condition

The defect was that §4 asserted "OIDC login works" as an exit condition
while the shipped default made it **false for a single-machine install**,
which is the configuration a customer operator tries first. Two edits to
`specs/customer-onboarding-playbook.md` §4:

- A new paragraph before the exit line stating the structural constraint
  in one sentence — *the issuer URL is used by the core (container-side)
  and by the browser (host-side) and OIDC's issuer-match rule means it
  must be the same string for both* — then the two configurations that
  satisfy it: `CL_HOST_ADDR=127.0.0.1` single-machine,
  `CL_HOST_ADDR=<LAN IP>` + `CL_BIND=0.0.0.0` multi-machine.
- The exit condition itself, made checkable rather than assertable:
  *OIDC login works **from the browser the operator will actually use***
  — confirmed by loading `/app/`, "not inferred from the IdP being
  healthy, which is the check that passes on the broken configuration."

**What this amendment deliberately does not do:** it does not change the
`host.docker.internal` default in `docker-compose.yml`, and it does not
build the split-horizon issuer (A4-F5's candidate fix 1). Both are code
changes to the install story, outside this session's fence. A4-F5 stays
filed against whichever checkpoint owns that story; what closes here is
only the honesty defect — a playbook step that asserted something untrue.

## D-108's brackets, resolved (operator attestation, 2026-08-06)

Two clauses of D-108 were recorded on 2026-08-06 with their placeholders
unfilled, and a second session declined to fill them. The operator has now
supplied both, as attestation, with the explicit statement that **no re-run
of A-2 is required or implied — A-2 stays CLOSED on D-108.1's extracted
evidence, unchanged.** Both brackets are resolved and are not carried
forward. Transcribed:

**Clause 2 (execution shape).** *"The run was successful. She explored the
estate and stopped satisfied with the validated SQL; execution was
available to her session and unattempted, not blocked."*

**Finding A2-F1 — recorded as already worded, now on stated ground.** A
first user's natural stopping point was validated SQL, not results. This
is input to B-1's surfaces and to the report skill's phrasing, **not a
defect** — capability is separately proven at M2/M3. What it tells this
session specifically: the product's own surfaces should not assume a
journey ends at an executed result, and a reporter who never executes is
a satisfied user, not an abandoned one. (Contrast the ledger's
`abandoned_journey` detector, which fingerprints exactly that shape —
resolution reads plus a validate with no execute. A2-F1 is the evidence
that the rule's *default* reading of that shape as abandonment is
sometimes wrong. Not changed here; noted for OD-2's threshold revisit,
which owns detector tuning.)

**Clause 3 (friction notes).** *"No separate friction notes were taken
during the run."*

**Finding A2-F2 — recorded, D-108.3's stated branch fired.** The
observation half of the first-user run was lost. It is not recoverable:
no session can supply an account of a room it was not in, and the four
gate clauses the audit rows prove are *what the system did*, never *what
the person felt while it did it*. `results/phase2/a2-field-notes/` stays
empty and is now closed as permanently empty rather than pending.

The corrective is prospective, and landed in this task: **A-2's runbook
§6 now states that the notes are a named artifact of the run**, of the
same standing as the audit extraction — a future run is not complete
until `results/phase2/a2-field-notes/README.md` exists and is committed,
and a run that genuinely takes none writes *that sentence* down as the
artifact. Filed there rather than in a spec because the runbook is what a
person actually reads on the morning.

## D-114 — decisions this build had to take

### D-114.1 — governance writes enter the audit record (closes D-110.3a)

Dashboard spec §5.1 filed the gap: `audit_records` is one row per MCP
call and is exactly that, so connection CRUD — and every governance write
after it — left no durable record beyond a job's `triggers` array, which
exists only where a job exists. Its trigger was normative: **close before
B-4's audit view ships.** Proposed to the operator in five lines under
D-113's fence and **authorized**; closed here rather than at B-4.

**The contract widens from "one row per MCP call" to "one row per
governed act."** No schema change — `audit_records` was already
tool-agnostic. `writeGovernanceAudit` is a thin caller over the existing
`writeAudit`, and the acts that now write a row are: connection upsert,
delete and test; ledger verdicts; the deliver-batch trigger; and the
`batched → approved` return D-114.12 adds. Each
carries the acting subject and roles from the resolved session, a `tool`
naming the act (`dashboard.connection.upsert`, `dashboard.ledger.verdict`,
…), `session_id: null` because a browser session is not an MCP session,
`setup_stamp: unstamped` for the same reason, an args digest over the
request, and `decision: allowed | denied` — **denied included**, because a
reporter's refused verdict attempt is exactly the row an auditor wants and
the one a success-only log would omit.

Every existing consumer filters by `tool`, so none re-reads differently:
the ledger's window rules name `validate_sql` and `execute_sql`/
`publish_report` explicitly; the deliveries read joins on `audit_id`. The
one visible consequence, stated because a future evidence extraction will
meet it: **audit-window row counts now include governance rows.** They are
correctly attributed to the acting subject, so a windowed count is still
true — it is just no longer a count of tool calls alone. `extract-audit.sh`
gains nothing and needs nothing; the rows arrive through the same read.

What this does **not** do: it does not add a governance-write *table*
(§5.1's other candidate), and it does not retro-fill rows for writes that
already happened. B-4's gate inherits a closed item and an audit view that
will render both kinds from one query.

### D-114.2 — KB Health reads one endpoint, and it is the same computation the MCP tool uses

`GET /v1/dashboard/kb-health` is one governed read assembling the whole
module: per-source freshness against `sync-policy.yaml`, doc-status counts
from KB HEAD, the contaminated set with its lineage paths, the drift-PR
queue, and the sync-configuration state. The freshness and doc-status
halves are computed by functions **lifted out of the MCP
`report_freshness` tool and imported by both**, rather than re-derived —
the fan-out rule applied to a computation instead of a value. A dashboard
that could disagree with `report_freshness` about whether a source is
stale is a dashboard nobody can trust as evidence.

Visibility is filtered exactly as the MCP read filters it: a doc whose
path the caller's scopes do not cover is absent from the counts, not
zeroed. So two roles legitimately see two different totals, and each total
is true for its reader.

### D-114.3 — DT-9's warning is rendered from the core's own resolved config, not from a second read of /healthz

DT-9 says the configured-but-disabled state renders "from `/healthz`'s
`sync_enabled`". Taken literally that would have the SPA fetch an
unauthenticated ops probe and re-derive a warning from it — a second
source for one fact, and the fan-out rule forbids it. Instead the KB
Health payload carries a `sync` block resolved from **the same
`cfg.sync.enabled`** that `effectiveFlags()` reports to `/healthz`: one
value, two renderings. The test asserts both surfaces agree.

The state the warning describes is precise, and it is the two-silent-days
shape (D-84.2 / SO-F): `sync-policy.yaml` lists systems with thresholds
and triggers — the estate is *configured* to sync — and the core's sync
engine is off, so no trigger will ever fire and every source will age past
its threshold in silence. The banner says that in those words and names
the count of systems the policy configures, because "sync is disabled" on
its own reads like an intentional setting rather than a fault.

### D-114.4 — the drift-PR queue routes and cannot merge, structurally

The queue renders `listOpenSyncPrs()` — number, title, URL, branch, age —
and every row's only affordance is a link to the git provider, carrying no
credential (§6). There is no merge button, and the assertion that there is
none is made two ways: over the **shipped bundle** (no merge-shaped API
path, no method that could reach one) and over the **server** (the module's
endpoint is a GET; no dashboard route mutates a PR). §7.3 is the line and
UI-6 is the ruling; a button is not the risk, a *code path* is, and the
test is written against the path.

### D-114.5 — the resolution badge is a server-computed count, and the client cannot compute one

UI-D fixed F-10's mechanism as a dashboard badge on the filer's next
session. It is served by `GET /v1/dashboard/inbox`: the issues this caller
filed that reached a terminal verdict — `rejected` with its reason, or
`resolved` with its PR URL — since the caller last acknowledged them.
Acknowledgement is a write (`POST /v1/dashboard/inbox/ack`) under the
caller's own identity, so "seen" is server state and survives a reload,
a second tab, and a different machine.

The filer scope is the server's, not a filter the client applies: the
endpoint reads the same `filedBy = session subject` rule the ledger queue
uses, and a reporter asking for another subject's inbox is the DT-1
refusal. The badge count in the sidebar is a number the server sent.

**In-session surfacing remains unbuilt** (UI-D names it a skill-side
candidate) and is not reported as shipped anywhere in this build.

### D-114.6 — Connections gains its edit affordance (A4-F1), over references only

A4-F1: the module rendered no config and offered no edit, so changing a
credential reference through the UI meant retyping the whole registration
from memory — which is why A-4's migration had to be a script. The card
now renders the stored `config` and the credential references, and an
**Edit** affordance opens them prefilled and PUTs the result through the
same governed endpoint the add form uses.

Two properties hold it inside UI-8. The form edits **references, never
values** — `vault://…#field`, `env://NAME` — and there is no password
input on the screen to type a secret into (asserted over the sources, as
at B-2). And the payload validator already refuses material that looks
like a credential, so the refusal is the server's, not the form's.

What is prefilled is the **stored row as the API rendered it**, so an
edit that changes nothing round-trips to an identical row; the response
shown afterwards is the store's read-back, not the submitted form.

### D-114.7 — verdict, filing and batch UI add no power the server does not already grant

DT-11 was proven server-side at B-0: a reporter's verdict call is a 403,
approve records identity and timestamp, and no git call or KB write
happens. This build adds pixels over that and **no new authority**. The
approve/reject controls and the deliver-batch trigger are rendered for
every caller — not hidden by role, per UI-1 — and a caller without the
steward profile gets the server's own 403 rendered as its own words. The
suite re-runs DT-11 through the UI's exact call shape so the two cannot
drift.

Rejection requires a reason in the UI because it requires one at the
server (a rejection the filer cannot read is a disappearance, not a
decision); the client's `required` attribute is a courtesy over a server
rule, never the rule.

### D-114.8 — the proposal is displayed inert and marked inert

DT-12 has two halves and they are asserted in two places. In the queue,
proposal text renders through the same `<Text>` component every
server-supplied string goes through — no raw-HTML path exists in these
sources — and the payload it renders was already LED-R2-scrubbed at
storage and LED-R5-neutralized at the render boundary, so a script or
markdown payload arrives as characters. The panel labels it *the
requester's words, quoted — not KB content*, because a proposal shown in
the product's own chrome reads as endorsed unless something says
otherwise. The other half — that no requester text appears verbatim in
the batch PR's diff — is the enrich skill's, and is asserted there.

### D-114.9 — Ops re-enqueues as the user, and never repairs the dead job

The dead-letter list offers re-enqueue, and re-enqueue is `POST /v1/jobs`
under the caller's identity (dashboard spec §3) — a **new job with the
dead one's payload**, not a resurrection of the dead row. The dead row
keeps its error and its terminal state, because it is the evidence that
something failed and rewriting it would erase the fault the operator is
looking at. The new job's `triggers` array records the dashboard act and
the acting subject, and the response names the new job id.

### D-114.10 — webhook secrets are shown once, from the creation response, and never stored

UI-8's last surface. The rotate control POSTs and the **response body
carries the new secret exactly once**; the UI renders it in a panel that
says it will not be shown again, and holds it in a React state variable
that dies with the tab. There is no GET that returns a secret — the store
holds a sha256 and nothing else can be recovered from it — and DT-5's
reload assertion passes for the structural reason that no browser storage
API appears anywhere in these sources.

### D-114.11 — enrich S1b is a mode of the same skill, not a second skill

D-101.4's queue-driven batch mode enters the existing state machine at a
different S1 and runs S2–S5 unchanged. The skill file gains one section
rather than a fork, because two enrichment procedures would drift and the
grounding discipline is the part that must not.

Two rules are the mode, and both are honesty rules. **The approved request
is a citation of the customer-provided class** — `sources: customer-provided,
<name>, <date>`, taken from what the ledger recorded (LED-R3 server-set),
never retyped from the body of the request — and it sits on the S2 maturity
ladder beside `customer doc: <uri>`: **stated** by someone who knows the
business, never **observed** by us, and never upgraded because it arrived
as confident prose. **And a request the skill cannot draft at all returns
to the queue** with a note saying what evidence would unblock it, drops out
of the batch's trailers, and is named in the PR body — never guessed at.

The PR body carries the request→doc mapping and one `CL-Resolves` trailer
per request the batch **actually satisfies**, so a merge resolves exactly
those. A returned item's absence from the trailers is what keeps it open;
that is the mechanism, not a convention.

### D-114.12 — the `batched → approved` return, which the diagram drew and nothing implemented

Fault-ledger §4's state diagram has an arrow nothing could take:

```
approved ──deliver batch──► batched ──undraftable──► approved
                                       (returns with the skill's note)
```

The skill spec relies on it (S1b/CP-E5: "one the skill cannot draft at
all **returns to the queue** with a note stating what evidence would
unblock it"), and AS-18 asserts it. There was no mechanism — no endpoint,
no tool, no column — so the honest exit CP-E5 requires had nowhere to go,
and the only paths available to a skill facing an undraftable request
were to guess it or to drop it silently. Both are the failure that rule
exists to prevent.

Built: `POST /v1/dashboard/ledger/issues/:id/return` with a **required**
note, steward-gated like every other ledger workflow write (the skill
runs under the steward's own identity, so this is the same gate and not a
new one). It sets `approved`, clears `batch_id` so the next batch can
pick the request up, and keeps the verdict columns — the steward's
approval still stands, because nothing about it turned out to be wrong.

**A note is required, and the refusal is the point.** A return without
one reads as `approved` to the next steward and says nothing about why it
came back or what would fix it — a silent drop wearing a state change.

**Occurrences are deliberately not incremented.** The queue is ordered by
demand; a skill reporting that it could not write something is not
another person asking for it, and counting it as one would corrupt the
signal the ordering depends on. For the same reason the note is a column
on the issue rather than a `ledger_events` row: an event would increment
that count as a side effect of recording a non-event.

*Flagged, not done:* fault-ledger §4's "Additive DDL" sentence enumerates
the four verdict columns and does not mention `return_note` /
`returned_at`. The transition is specified in the same section and its
storage is additive, so this implements the spec rather than contradicting
it — but the enumeration is now incomplete, and correcting it is a
one-line spec amendment **outside this session's fence**. Proposed for the
next session's task 0.

### D-114.13 — AS-18's two halves are verified by two different instruments

AS-18 spans an agent's judgement and the product's mechanics, and one
test cannot honestly cover both.

**The agent half** is `tools.skill_scenarios --only enrich-batch`: a real
headless session runs the shipped skill against a staged batch on the
fixture deployment, and the assertions are on what it produced — the
citation in the ledger's recorded shape, no requester prose in the diff,
the request→doc mapping, exactly one trailer, the returned item back at
`approved` with a note, no `verified` anywhere. It is D-78 layer (b) and
it is AS-18's conformance evidence. **It has not been run** — it costs a
model call and belongs to whoever runs the gate.

**The product half** is `core/test/dashboard-b1.test.ts`: request →
verdict → batch → a merged PR carrying one trailer → the ledger resolves
exactly that request → the filer's inbox shows it with the PR link, while
the untrailered request stays `batched`. Deterministic, no model, runs on
every commit — and it could fail: it did, twice, while the trailer
matching was being written.

The split is the D-78 rule applied honestly rather than mechanically:
each half is tested by the instrument that can actually falsify it, and
neither is reported as covering the other.

## B1-F1 — the gate demo's first finding (2026-08-06, operator)

Found on act 3 of the runbook, the first time anyone pressed *Re-enqueue
as me* against the pilot's real dead-letter queue. Full account in
`results/phase2/b1/FINDINGS.md`; the ruling-shaped part is here.

**Re-enqueue replayed the dead job's captured payload.** A job payload is
a *capture* of the connection registry taken at enqueue time, so a
snapshot job queued before the A-4 vault migration carried
`env://SUPABASE_DSN`; the runner has had no `env` resolver since; and
each press produced a fresh dead job with the same impossible reference.
The operator pressed three times and grew the queue by three.

**Two rules meet here and both say the same thing.** The **fan-out rule**:
the registry is the one source for what a connection uses, and a captured
copy that disagrees with it is a stale duplicate, not evidence. And
**A-4's removal rule from the other side** — `env://` was removed as a
resolver, and the job queue turned out to be a place the old reference
survived. A4-F6 was this shape in the execution preflight; this is its
sibling, and it survived A-4 because nothing re-reads old job payloads
and no surface exposed them until B-1 built the button.

**Fixed by rebuilding, not by replaying** (D-114.9 amended in place):
re-enqueue now builds the new job from the connection's current
registration — config, credentials, connector and constraint — and
reports captured-vs-current references when they differ, because the
operator is about to see a different outcome from the same button. No
registration is a refusal, not a replay.

**And a line drawn that was not there before:** `execute` and `publish`
jobs are **not re-enqueueable**. Their payloads are not the registry's to
rebuild — they carry a person's statement, their identity and the
guardrails they were granted. Re-running one means re-running somebody
else's request under their recorded identity with nobody waiting for the
answer; for publish it would re-deliver a report to a BI tool because an
operator was clearing a queue. The discriminator is *whose request the
payload holds*, not the job's class: a `test_connection` probe is
interactive and perfectly safe to re-run.

**Two smaller defects the same report contained**, both real:

- `error.reenqueued_as` put a success pointer inside the field that says
  why a job died. Its own column now (migration 0014), with the existing
  rows moved rather than left behind.
- The UI answered "queued" and stopped, so a retry's *outcome* had to be
  found by noticing a new row in a list the operator had just left. It
  now follows the new job to a terminal state and reports it in place,
  including "it failed too — read this before pressing anything else",
  and a dead row that already has a successor offers no button.

**What this says about the checkpoint.** The gate demo found in one act
what the suites could not: every automated test staged its own payload,
so none of them could have carried a *stale* one. The estate's history is
the thing a fixture does not have, and it is why the demo is run on the
real one.

## B1-F2 — the queue only browser users could file into (2026-08-06, operator)

The second gate-demo finding, and the more important one. Stated by the
operator as a description of how the product *should* work — a reporter
mid-session asks for the KB to say something, the agent queues it, a
steward verdicts it, the approved ones reach an enrich session and land
as one PR. That is exactly what B-1 built, with the first step missing.

**Every piece existed and nothing drove the first one.**
`flag_gap(kind: enrichment_request, proposal: …)` shipped at D-101.3, is
tested by MT-14, and is in the reporter profile's allowlist. But no skill
named the kind: the report skill's K-FAIL section said "call `flag_gap`
with the most specific applicable kind" and never mentioned the one that
carries a proposal. So an agent whose user volunteered knowledge filed it
as `missing_doc` without their words, or filed nothing.

**The spec had been satisfied on paper.** The ledger §4 amendment says
"one queue whether or not the requester has a browser open"; D-101.3 says
"a queue only browser users can file into is not the queue D-101
adopted". It was that queue — because a capability with no caller
satisfies every test written against the capability. MT-14 drives the
tool directly and proves the inlet works; nothing asserted that anything
would ever *reach for* it.

**Fixed skill-side**, which is where the gap was: the report skill gains
a section that is deliberately not a failure exit, because the case is a
session that went *fine* and a user who volunteered something. Its load-
bearing rules: `proposal` carries their words verbatim and `description`
carries the agent's summary of the gap (a tidied proposal is the agent's
prose wearing the user's authority); a dead end where the user also
supplies the answer is **two filings, not one**; the honest sentence
afterwards is "I've filed it", never "I've added it"; and *do not ask
permission to file* — a request that dies to "shall I note that?" is
knowledge lost to politeness.

*Flagged, not done:* **skill spec §5 has no clause for this.** The
behaviour is required by the ledger spec §4 and MCP §6.10, so shipping it
implements a merged requirement rather than inventing one — but §5 should
gain a sentence, and that is outside this session's fence. Proposed for
the next task 0 alongside the fault-ledger §4 DDL enumeration. **And no
behavioural scenario exists** for whether a real agent reaches for the
kind; the shipped test is a grep over the skill file, which catches the
regression that just happened (the instruction being absent) and is not
reported as covering the behaviour.

### B1-F2's first half — history rendered as open faults

Same message: *"that specific job fixed but other instances of the same
job are still in dead letters."* After act 3 the pilot showed eleven dead
rows; six had successors that had **succeeded**, three of them one chain
four links long. The fix worked and the screen could not say so.

**The rule now encoded:** a dead job with a successor **has been acted
on** — its story continues at the newer job, so it is *superseded* and
kept as the record of the original failure rather than shown as
outstanding work. A dead job with no successor is the one that still
wants somebody. The tab counts what needs attention (3, not 11), and a
superseded row states its chain's ending. Computed server-side by walking
`reenqueued_as`.

### And act 4 could not run, correctly

*"I can't do act 4 because there are no open drift PRs."* True, and the
right answer: drift PRs exist only when a source's schema moved, and
nothing had. The runbook was written as though the queue would be
populated. It now says an empty queue **is a pass** — the clause is
routing-without-a-merge-affordance, whose no-merge half is machine-checked
and does not depend on a PR existing — and points at A-1's drill for
anyone who wants to see it populated on purpose.

**What the three findings share.** None of them could have been found by
the suites. B1-F1 needed an estate with history; B1-F2 needed somebody to
notice that a capability had no caller; act 4 needed a real estate with
nothing wrong with it. That is the argument for the demo, and it has now
paid for itself twice before reaching act 5.

## B1-F3 — a triage queue you could read and not act on (2026-08-06, operator)

Act 5. *"I can see the history and proposal and read it, but what else
can I do. There are open gaps in the triage and I can't do anything to
them."* The answer was: nothing.

**The gap half of the module shipped read-only.** Knowledge Requests got
its full lifecycle — verdicts, batches, returns, resolution. Gaps got a
list. Fault-ledger §8 specifies the actions plainly ("acknowledge (→
`triaged`), assign, dismiss-with-reason, export enrichment batch") and
none existed.

**Why it passed.** B-1's gate clause is *"triage queue ordered by
occurrences/distinct_subjects"* — the queue was ordered and the test
asserted the ordering. The clause describes a property of a list and says
nothing about acting on it, so a read-only list satisfied it literally.
The spec that says otherwise lives in another document and nothing joined
the two. **A gate clause is not a substitute for reading the spec the
clause points at**, and that is the lesson worth keeping.

**Built:** `POST /v1/dashboard/ledger/issues/:id/triage` — acknowledge
(`open → triaged`, the state the enrich skill's S1 reads first) and
dismiss (`open|triaged → dismissed`, required reason, LED-R2-bound, row
kept so L-4 reopens it on recurrence with the dismissal preserved). Both
steward-gated, both ledger state only, asserted against the KB's refs and
PR store exactly as DT-11 is: **UI-11 governs the whole module, not only
the request queue.**

**The two lifecycles refuse each other.** `acknowledge` on an
`enrichment_request` is a 400. "Acknowledge" means *this is real*;
"approve" means *worth drafting*; one control for both would let a
request skip its verdict.

**And the response says what the state change buys**, because "triaged"
alone tells a steward nothing and the honest answer is one a product
hides by accident: *nothing drafts by itself; you run the skill*.

*Not built, deliberately:* **`assign`** — no assignee column, one team on
the pilot, so the control would set state nothing reads and a button that
does nothing is worse than an absent one. **`export enrichment batch` as
a separate act** — for gaps the scoped work list *is* `status = triaged`
(the skill's S1 input via `list_gaps`), so acknowledging already emits
it; a second mechanism would be two names for one thing. What was missing
was saying so.

### And the runbook told the operator to do the platform's job by hand

Separately, and worse. Act 5 said: open the KB, edit a contaminated doc,
open a PR. The operator objected — *"the steward should do these KB
updates via an AI agent with our skills and mcp"* — and they are right:
A-1 proved that path live (STOP-2, the steward's session ran
`review-sync` and prepared repair PR #36). Telling an operator to
hand-edit is telling them to do by hand the thing the platform exists to
do. Act 5 is rewritten around **triage → run the skill → review the diff
→ merge**, opening with the three actors and the two lines between them:
the dashboard decides what is worth doing and cannot write; the skill
writes and cannot merge; a human merges.

**A real gap the rewrite exposed, filed not fixed:** the enrich skill's
S1 work list is ledger items, hot undocumented objects and harvested
docs. **A doc marked contaminated by a past sync PR is in none of them**,
so the pilot's 34 have no product entry point. It belongs to **A-5**,
whose gate is precisely "every report-path L1 doc human-verified"; act 5b
now says so instead of implying the backlog is one click of work.

## What this build does not claim

- **The gate demo has not been run to completion.** Act 3 has (it found
  B1-F1, above). Every clause below is machine-proven
  on fixtures and against the live pilot's own data where it reads; the
  end-to-end demonstration D-101.5 requires — request with a proposal →
  steward verdict → batch → enrich PR merged as R2 → requester sees the
  resolution — is the operator's morning and is written up as a runbook,
  not performed here. A PR merged by this session would not be R2 merging
  a reviewed diff, which is the whole of what KB-7 means.
- **AS-18's behavioral half has not been run** (D-114.13). The scenario
  ships; the evidence is the operator's model call. The validators are
  green and are explicitly *not* the evidence (D-78).
- **In-session gap surfacing is unbuilt** (UI-D), and is named as unbuilt
  in the code, the runbook and here.
- **A4-F5's code-level fix is not done** — only the playbook's honesty
  defect closed (D-113.4 as applied).
- **The register rows for D-107.3 (verdict history) and D-107.4 (jobs
  retention) are still not filed.** Flagged at A-3/B-2, unchanged here,
  and still outside a build session's fence.
