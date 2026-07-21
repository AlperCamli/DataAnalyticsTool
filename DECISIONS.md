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
`task/2-benchmark-harness` (commits `d2a81b1`..`cec5347`). Full platform
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

- **G3 startup check passes**: role `contextlayer_exec`, engine 17.6.
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
role/credential assertions — `contextlayer_exec` read-only at the
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

**3. Uncommitted D-71/D-72 work committed** (`2ff056d`, `e0c4f43`) as a
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
