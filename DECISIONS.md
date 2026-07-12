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

## D-9 — Repo-path discrepancies (no code impact)

Specs live at `spec/`, but CLAUDE.md, the spec index (§"Change process"),
and the dev plan all say `specs/`. `phase1-supabase-ga4-gsc-plan.md`,
referenced by the snapshot spec header and the task brief, is absent from
the repo; the snapshot spec states it formalizes that plan's §4, so it was
treated as the authority. Both worth fixing at the next consolidation pass.
