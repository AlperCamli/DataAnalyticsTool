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
