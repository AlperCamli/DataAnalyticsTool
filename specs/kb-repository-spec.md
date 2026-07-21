# Contract Specification — KB Repository (v1)

Status: v1 draft for implementation. Formalizes `context-layer-v1-spec.md` §5 and `phase1-supabase-ga4-gsc-plan.md` §5; implements journeys J1/J2 and the trust behaviors of `high-level-requirements-and-user-journeys.md` §5–§7. Consumers of this spec: the generator (writes machine-owned content), the sync engine (diffs, flags, opens PRs), the MCP server (reads docs + front-matter as trust signals), the shipped skills (`enrich`, `review-sync`, `report` all read/write per these rules), and humans.

The KB repo is the product's knowledge store and its only knowledge-change mechanism is a git PR. This spec defines what the repo contains, who may write what, and the machine-readable contracts (front-matter, dependency declarations, status lifecycle) that make sync, contamination scanning, and trust serving deterministic.

---

## 1. Scope

**In scope:** repository layout; ownership zones and path rules; front-matter schemas per doc class; the status lifecycle and its transition rules; the dependency-declaration contract the contamination scan runs on; doc templates; naming and cross-reference conventions; sync branch/PR conventions; `.contextlayer/` layout; KB CI checks.

**Out of scope:** the YAML schemas *inside* `.contextlayer/` (profiles, sync policy, dashboard — each owned by its component spec; only their location is fixed here), generator template internals, and MCP tool response shapes (MCP tool reference spec).

## 2. Design rulings

| # | Ruling | Rationale |
|---|---|---|
| K-1 | Ownership is **per-file**, never per-section; no editable regions inside generated files | Section markers rot under regeneration; file-level ownership is enforceable by path + front-matter alone |
| K-2 | The contamination scan's primary input is the **declared `depends_on` list** in human-doc front-matter; body-text FQN matching is a secondary best-effort net | Deterministic scan; "what breaks if this column drops" becomes a query. The `enrich` skill maintains the declarations |
| K-3 | `stale` = underlying object changed **additively** since verification (possibly incomplete, not wrong); `contaminated` = a **breaking** change contradicts it, broken reference named. Time-based aging is a dashboard warning, never a status | Statuses carry precise agent-facing semantics (warn vs. refuse); mixing in age would blur them |
| K-4 | SQL systems: one doc pair per object. API systems: grouped docs per kind, with an `objects:` front-matter roster | Grouped docs match how API estates are understood; the roster keeps contamination flagging uniform across both shapes |
| K-5 | Front-matter is a normative machine contract: strict YAML, schema-validated in KB CI; it **is** the trust payload the MCP server serves | Trust signals must be parseable, not prose |
| K-6 | Human edits to machine-owned files **warn, don't block** in CI, stating the edit will be overwritten and pointing to the human-owned sibling | Preserves open editing (product decision #6) while preventing silent work loss |
| K-7 | Root `index.md` and `conventions.md` are bootstrapped once by the generator, then human-owned forever; per-system and per-schema `index.md` files are machine-owned, each with an optional human-owned `_notes.md` sibling that the generator links | Navigation stays current automatically; narrative stays human |
| K-8 | Every snapshot object gets a machine doc unconditionally; human docs exist only where written (stub ↔ hot distinction lives in the index, not in file existence) | Machine docs are free; forcing empty human stubs would create thousands of meaningless files |

## 3. Repository layout (normative)

```
kb/
├── index.md                        # H (bootstrapped once): entry point, navigation
├── conventions.md                  # H (bootstrapped once): dialects, query rules, trust behaviors
├── systems/
│   └── <system>/                   # one dir per configured system (snapshot `system` name)
│       ├── index.md                # M: object listing, hot/stub, doc-status roll-up
│       ├── _notes.md               # H (optional): narrative about the system
│       └── <schema>/               # SQL systems (K-4)
│           ├── index.md            # M: per-schema listing
│           ├── _notes.md           # H (optional): narrative about the schema (K-7)
│           ├── <object>.schema.md  # M: facts (from snapshot)
│           └── <object>.md         # H (optional): semantics
│       # API systems instead carry grouped docs at the system level:
│       ├── <kind-group>.schema.md  # M: e.g. dimensions.schema.md, metrics.schema.md, events.schema.md
│       └── <kind-group>.md         # H (optional): semantics for the group
├── entities/
│   └── <entity>.md                 # H: cross-system business concepts
├── metrics/
│   └── <metric>.md                 # H: certified definitions
├── lineage/
│   ├── graph.json                  # M: the lineage graph (lineage-format spec)
│   └── <pipeline>.md               # H (optional): why each transformation exists
├── faults/                         # nothing — fault ledger is Postgres, not git (HLR §6); dir must not exist
└── .contextlayer/
    ├── sources.yaml                # source configs (credential references only)
    ├── snapshots/<system>.json     # latest accepted snapshot per system — the render input (D-49)
    ├── sync-policy.yaml            # trigger modes per system (HLR §8 P1), thresholds
    ├── roles.yaml                  # OIDC role → doc-visibility map
    ├── profiles/*.yaml             # agent profiles (platform-architecture §5)
    └── dashboard.yaml              # dashboard module config
```

Legend: **M** = machine-owned (sync regenerates freely, humans warned off per K-6); **H** = human-owned (sync never writes, only flags).

Path rules: directory and file names for objects use the source-native name lowercased with characters outside `[a-z0-9_-]` percent-free-mapped to `-`; the authoritative source-native name always lives in front-matter (`object:`), so filename mangling never loses identity. Entity and metric filenames are kebab-case English business terms.

**Render inputs (purpose-merge amendment, D-49):** a machine render is a deterministic function of exactly two inputs — the **latest accepted snapshot** per system and the **enrichment front-matter at repo HEAD** (§4.2/§4.7 `purpose`, `column_purposes`, `object_purposes`, plus the human-sibling existence/status reads the indexes already made). `.contextlayer/snapshots/<system>.json` is the latest accepted snapshot's committed identity: it is what pins "latest accepted" at a given HEAD, what the generator renders from, and what KB CI re-renders against (KB-8, §10) — without it the §10 consistency invariant would not be well-defined per commit. Sync updates it in the same PR as the renders it implies; its JSON schema is the snapshot spec's, not this document's.

## 4. Front-matter schemas

All front-matter is strict YAML between `---` fences at byte 0 of the file. KB CI validates every file against the schema for its class (K-5). Unknown keys are rejected (front-matter is a closed contract, unlike snapshot `stats` — docs are numerous and typo-prone).

### 4.1 Machine-owned object doc (`*.schema.md`, generated)

```yaml
---
doc_class: machine-object
object: supabase.public.orders          # FQN: system.schema.name (SQL)
kind: table
schema_hash: "sha256:…"                  # from the snapshot that generated this file
generated_at: 2026-07-11
source_mode: ddl-file
snapshot_version: "1"
status: machine
---
```

**`generated_at` (clarifying amendment, task 1.5, applied):** the value is the capture date (the date part of `captured_at`) of the snapshot whose render last *changed this file's content* — never the generator's wall clock. A regeneration whose output differs only in this field leaves the file byte-untouched, which makes KB-8 a fixed point and makes a full render byte-identical to the KB-C changed-objects-only path — the two regeneration routes can never disagree. Corollary (single timestamp locus): machine-doc bodies never embed a timestamp; the §7 "freshness" reference points at this field. A `source_mode` switch (ddl-file → live) is a content change and restamps the field — honest provenance ("this doc now reflects live introspection"), not churn. Rationale: DECISIONS.md D-33.

**D-49 clarification (purpose merge):** `generated_at` remains rule B — the capture date of the snapshot whose *facts* the render reflects. Enrichment is not a fact: a rewrite whose differences are confined to purpose slots (the §7 Purpose cells/rows) keeps the file's existing `generated_at`; only fact-content changes restamp. Purpose-driven re-renders therefore never change the field, even when the latest accepted snapshot's capture date has advanced past the file's stamp (recaptured-but-unchanged estates).

Grouped API docs use `doc_class: machine-group` and replace `object`/`kind` with:

```yaml
objects:                                  # the roster (K-4)
  - { object: "ga4.custom.sessions_with_intent", kind: api_metric, schema_hash: "sha256:…" }
  - { object: "ga4.standard.sessionSource",      kind: api_dimension, schema_hash: "sha256:…" }
```

### 4.2 Human-owned object doc

```yaml
---
doc_class: human-object                   # or human-group for API kind-groups
object: supabase.public.orders
written_against_schema_hash: "sha256:…"   # hash current when last verified
status: draft                             # verified | draft | stale | contaminated
last_verified: null                       # date + name once verified: "2026-07-11 (a.demir)"
sources:                                  # evidence grading (maturity ladder, HLR §8 P4)
  - "customer doc: orders-service.md"
  - "inferred from column names"
depends_on:                               # K-2: the contamination scan contract
  - supabase.public.users
  - supabase.public.order_items
contamination: null                       # set by sync only — see §6
purpose: "One row per checkout; the commerce fact table."   # optional (D-49)
column_purposes:                          # optional (D-49): column name → one-liner
  status: "Order lifecycle state; enum decodings in the body below."
---
```

**Purpose enrichment (D-49, additive):** `human-object` docs may carry an optional `purpose` (string, one line) and `column_purposes` (map of column name → one-line string); `human-group` docs may carry `purpose` and `object_purposes` (map of FQN → one-line string). These fields are human-owned enrichment that the generator **merges into machine renders** (§7) — the one sanctioned flow of human-authored text into machine-owned files, safe under K-1 because the source is closed, schema-validated front-matter, never markdown bodies. Values are one-liners (no newlines); front-matter stays a closed contract — unknown keys are still rejected. JSON structure documentation for `json`/`jsonb` columns is human-doc *body* content (one subsection per column, evidence-cited or an explicit gap note), not merged into machine renders in v1.

### 4.3 Entity doc

As §4.2 with `doc_class: entity`, no single `object:`, and a required `maps:` block — the routing hub:

```yaml
aliases: [customer, account holder]        # optional; search-indexed (MCP ruling M-6)
maps:
  - { object: supabase.public.users, role: system-of-record, keys: [id] }
  - { object: "ga4.standard.userId", role: analytics-identity, keys: [userId] }
join_guidance: per-target                  # free-form body section carries details
depends_on: [supabase.public.users]        # derived superset of maps[].object; CI checks consistency
```

### 4.4 Metric doc

As §4.2 with `doc_class: metric`, plus `owner:` (person/team) and `implementations:` — one entry per system where the metric is computable, each carrying the exact formula or SQL fragment, plus optional `aliases:` (search-indexed, as §4.3). `status: verified` on a metric **is** certification; the `report` skill treats only verified metrics as certified.

### 4.5 Lineage annotation doc

`doc_class: lineage-note`, `edges:` list of edge IDs from `lineage/graph.json` the note explains, ordinary `status`/`depends_on` semantics. May additionally carry a fenced `declared_edges:` YAML block — the human-tier edge source ingested by the graph merger (formats spec §3.3); KB CI validates the block against the edge model.

### 4.6 Machine-owned index doc (`index.md`, generated) — registration record (task 1.5 amendment, applied)

Per-system and per-schema `index.md` files are machine-owned (K-7), but §4 defined no front-matter class for them while KB-1 validates every file and K-5 makes front-matter the trust payload. This registers the class:

```yaml
---
doc_class: machine-index
system: supabase
scope: schema                            # system | schema
schema: public                           # present iff scope: schema
generated_at: 2026-07-11
source_mode: ddl-file
snapshot_version: "1"
status: machine
---
```

**Root-bootstrap exemption (amended by D-49 for `_notes.md`):** the K-7 bootstrap artifacts — `kb/index.md`, `kb/conventions.md`, and optional `_notes.md` siblings — are human-owned navigation/narrative docs with no object identity; the two root files carry **no front-matter** and are exempt from KB-1, latched by path (they are written by the generator only when absent; `_notes.md` is never generator-written). `_notes.md` siblings *may* carry front-matter since D-49: absent front-matter remains exempt (additive evolution — existing notes stay valid); present front-matter must validate as `human-notes` (§4.7). Whether repo-level human docs need trust statuses for the MCP trust blocks is deliberately not designed here — register item KB-F. Rationale: DECISIONS.md D-34, D-49.

### 4.7 Notes doc (`_notes.md` siblings) — registration record (D-49, applied)

```yaml
---
doc_class: human-notes
purpose: "Core commerce schema; everything an order touches."   # optional, one line
---
```

Front-matter is optional on `_notes.md` (§4.6); when present, this is its class — `doc_class` required, `purpose` the only other key, unknown keys rejected. The `purpose` of a *schema-level* `_notes.md` is merged into that schema's row of the per-system machine index (§7). A system-level `_notes.md` may carry `purpose` too; v1 renders it nowhere (the per-system index has no self-row) — it is served, not merged.

## 5. Status lifecycle (K-3)

```
                 (enrich PR / human authoring)
                          │
                          ▼
        ┌──────────────► draft ───(human review + last_verified set)───► verified
        │                 ▲                                                │  │
        │   (human edits  │                                (additive drift │  │ (breaking drift
        │    to repair)   │                                 on depends_on) │  │  contradicts doc)
        │                 │                                                ▼  ▼
        └─────────── contaminated ◄───(breaking drift, ref named)──── stale  contaminated
```

Transition authority is exclusive:

| Transition | Set by | Trigger |
|---|---|---|
| → `draft` | enrich skill or human, at authoring | New human doc |
| `draft` → `verified` | Human only, PR review; must set `last_verified` and refresh `written_against_schema_hash` | Certification |
| `verified` → `stale` | Sync engine only | Additive hash change on any `depends_on` object since `written_against_schema_hash` |
| any → `contaminated` | Sync engine only; fills `contamination: {object, change, detail}` naming the broken reference | Breaking change on a `depends_on` object, or downstream propagation through the lineage graph |
| `stale`/`contaminated` → `verified` | Human only, after repair; sync clears `contamination` is **not** allowed — the human removes it in the repair PR | Repair |

Agent-facing semantics (enforced by skill trust behaviors, HLR §7.3): `verified` — use freely; `draft`/`stale` — use with an explicit warning to the user; `contaminated` — refuse to build on it unless the user explicitly overrides, and say why.

## 6. Dependency declaration and the contamination scan (K-2)

**Declaration duty:** every human-owned doc lists in `depends_on` the FQN of every object whose structure its content relies on — tables it explains joins to, columns whose enum decodings it documents, views a metric formula reads. The `enrich` skill emits `depends_on` with every draft; the `review-sync` skill flags PRs whose body references an FQN missing from `depends_on`.

**Scan algorithm (normative for the sync engine):**

1. A drift run produces the per-object diff classifications (snapshot spec §7).
2. For every object classified *breaking* (removed, or changed-structural with breaking sub-diff): collect all human docs whose `depends_on` (or entity `maps`) includes its FQN → mark `contaminated`, write `contamination: {object, change, detail}`.
3. Walk `lineage/graph.json` **downstream** from the changed object; every reached node's dependent docs are contaminated too, with `contamination.path` carrying the lineage route (a breaking change in one source table surfaces everywhere its data flows).
4. For every object classified *changed* with only additive sub-diffs: dependent docs currently `verified` → `stale`.
5. Secondary net: grep all human docs for the changed FQN as a token; hits **not** covered by steps 2–4 are listed in the drift PR changelog as *undeclared possible references* — surfaced for the reviewer, never auto-flagged (best-effort, not authority).

All markings land as front-matter edits inside the same drift PR — sync's only writes to human-owned files are these front-matter status/contamination fields, never body text. This is the single, narrow exception to "sync never writes human files," and CI enforces that sync-authored commits touch nothing below the closing `---` fence of human docs.

## 7. Doc templates (normative section order)

Generated machine docs and skill-authored human docs follow fixed section orders so agents can navigate by heading. Deviations in human docs are permitted (open editing) but the enrich skill always emits the canonical order.

**`<object>.schema.md` (machine):** Identity (FQN, kind, hashes) · Columns (table: name, type, nullable, default, description, purpose) · Keys & indexes · Row estimate & freshness · Referenced-by (reverse FKs within system) · View definition (views/matviews, fenced SQL).

**Purpose merge (D-49):** machine renders carry the §4.2/§4.7 enrichment in fixed slots, populated from the human-owned sibling's front-matter and `—` when absent. Slot rule: *purpose renders last* — the trailing column of a table, the trailing row of a fact block — and every slot always renders (`—` marks absence; slots never collapse away), which keeps renders line-stable across enrichment changes. The slots: the columns table of `<object>.schema.md` gains a Purpose column from the sibling's `column_purposes`; each roster object's fact block in an API `<kind-group>.schema.md` gains a Purpose row from the sibling's `object_purposes`; per-schema index rows gain the object's `purpose` one-liner; per-system index rows gain the schema's purpose (from the schema-level `_notes.md`, SQL) or the kind-group's purpose (from the human group doc, API). Facts still come only from the snapshot (S-8); purposes come only from these declared front-matter fields — a generator emitting prose from any other source, or reading markdown bodies, is the K-1 violation this design exists to avoid.

**`<object>.md` (human):** front-matter carries `purpose` and `column_purposes` (§4.2); the body carries Grain · Column meanings the one-liners cannot hold · Join guidance · Reporting notes (which reporting views expose it) · Warnings.

**Template/front-matter alignment (D-38 purposes; amended at CP-5).** The template above no longer opens with a body "Purpose" section, and "Column meanings" is scoped to what a one-liner cannot carry. The reason is the D-49 merge: `purpose` and `column_purposes` are front-matter fields that the generator renders into the machine sibling (§7 purpose merge), so a body section repeating them creates **two sources for one claim** — and the two drift, at which point the KB says a table means one thing in `orders.schema.md` and another in `orders.md`, with nothing to arbitrate. One-liners live in front-matter, where the merge can reach them and where KB-10 checks their keys resolve.

The body is therefore for what a one-line, newline-free front-matter value structurally cannot express: enum decodings (`status: 1 = pending, 2 = shipped, …`), JSON/JSONB structure documentation (one subsection per column, per §4.2), multi-condition join caveats, and the reasoning behind a warning. Rule of thumb for the enrich skill: **if it fits on one line, it belongs in front-matter; if the body would only restate a one-liner, drop the section.** An empty body under complete front-matter is a valid human doc — objects whose meaning genuinely is one line per column should produce exactly that, not padding written to fill a template.

**`entities/<entity>.md`:** What it is · System map (rendered from `maps:` — system of record, analytics identity, per-purpose routing) · Keys & join paths (incl. BI blend keys per HLR §8 P5) · Cross-source resolution rule (blend vs. fetch-and-combine, per phase-1 §2) · Caveats.

**`metrics/<metric>.md`:** Definition (business language) · Formula · Implementations (per system, exact SQL/API expression) · Grain & dimensions it may be sliced by · Owner & certification trail · Known discrepancies.

**`conventions.md` skeleton (bootstrapped):** System classes & dialects · Query guardrails per system (execution policy, HLR §8 P2) · Trust-status behaviors (the §5 semantics, stated for agents) · Naming conventions · Quota notes for API sources · Machine-readable guardrail block (fenced YAML consumed by `validate_sql` per-system checks, MCP §6.6).

## 8. Naming and cross-reference conventions

- **FQN grammar:** `system.schema.name` (SQL) / `system.group.name` (API), matching snapshot identity minus `kind`; where kind is ambiguous in prose, suffix it: `ga4.custom.sessions_with_intent (api_metric)`. FQNs in doc bodies are always backticked — this is what the §6 step-5 token grep matches.
- **Intra-KB links** are relative markdown links; CI link-checks them. Links into machine docs use stable heading anchors (the generator emits deterministic anchor IDs).
- **Entities and metrics are referenced by path** (`entities/user.md`), never by prose title — titles may change, paths are identity.

## 9. Sync branch and PR conventions

- Branch: `sync/<run-id>` (one batched PR per run, all systems); title: `sync: <n> breaking, <m> additive across <systems>`; body: severity-ranked changelog (breaking first, each naming contaminated docs; rename candidates with both interpretations; undeclared possible references last).
- **Supersede rule:** on opening a new sync PR, sync auto-closes its own previous unmerged sync PRs with a comment linking the successor (the new run's snapshot subsumes the old diff).
- Commit identity: sync commits as the bot identity `contextlayer-sync`; enrich/agent-proposed PRs commit under the **triggering user's** git identity (HLR §5 J2.3) — provenance is git blame, so identity discipline is a hard rule.
- Merge policy is the customer's (branch protection on their server); the product's stance: additive-only PRs are safe to auto-merge if the customer enables it; breaking PRs never auto-merge.
- **Resolution trailers:** a PR body may carry `CL-Resolves: <issue-id>` trailers; on merge the core resolves the referenced fault-ledger issues (ledger spec §9). The enrich skill writes these automatically for ledger-originated work.

## 10. KB CI checks (shipped as a workflow the bootstrap installs)

| # | Check | Failure mode |
|---|---|---|
| KB-1 | Front-matter parses and validates against its `doc_class` schema (§4); K-7 root-bootstrap artifacts exempt (§4.6) | Block |
| KB-2 | Every `depends_on`/`maps` FQN resolves against the latest snapshot (or is explicitly marked `external:`) | Block |
| KB-3 | Machine-owned file modified by a non-sync author — except diffs CI reproduces exactly by regeneration, which pass without warning (D-49: enrichment PRs carry their implied re-renders) | **Warn** (K-6): "will be overwritten; semantics belong in `<object>.md`" |
| KB-4 | Sync-authored commit touches human-doc body text (below front-matter) | Block (violates §6 exception boundary) |
| KB-5 | Relative links and anchors resolve | Block |
| KB-6 | Entity `depends_on` ⊇ `maps[].object` | Block |
| KB-7 | `verified` status without `last_verified` or with stale `written_against_schema_hash` | Block |
| KB-8 | Render consistency (amended by D-49): machine files at HEAD byte-equal the render of (latest accepted snapshot, HEAD enrichment) — regeneration is a no-op. Runs on sync PRs and on every PR touching enrichment front-matter; PRs editing enrichment must include the implied machine re-renders | Block |
| KB-9 | Golden benchmark regression suite (product spec §11) on KB-content PRs | Per customer policy: block or report |
| KB-10 | `column_purposes` / `object_purposes` keys that do not resolve against the current snapshot, naming doc and key (D-49; repair pressure stays with the contamination flow) | **Warn** |

## 11. Retrieval-budget guidance (non-normative)

The hierarchical path (index → entity → 3–8 object docs) targets ~5–10K tokens per query regardless of estate size. To keep that true: human object docs should aim under ~800 words; entity docs under ~600; anything longer belongs split into linked notes. The generator caps machine-doc column tables at full fidelity (they are facts) but emits per-schema indexes so agents never list-scan a system directory.

## 12. Open decisions (spec-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| KB-A | Doc-visibility enforcement granularity (`roles.yaml`): per-directory vs per-file | Per-directory (system/schema level) in v1; per-file adds config burden ahead of demonstrated need | First customer with intra-schema confidentiality boundaries |
| KB-B | `external:` dependency escape hatch in KB-2 (docs referencing objects outside configured systems) | Allowed with `external: true` per entry; excluded from scans | If external refs proliferate, consider stub systems |
| KB-C | Machine-doc regeneration scope per drift run: changed objects only vs full re-render | Changed objects only (cheap PRs); KB-8 guards correctness | If template changes require estate-wide re-renders, add a `regen-all` manual job |
| KB-D | Localization of human docs (customer-language KBs) | Out of scope v1; docs in the customer's working language, templates language-neutral | First non-English deployment |
| KB-E | Grouped API docs splitting threshold (huge custom-dimension estates) | **No split in v1** — one group file regardless of roster size (owner ruling 2026-07-13, superseding the earlier split-at-200 default). Evidence: the trigger fired on the first example estate (pilot GA4: 376 standard dimensions) and it renders, validates, and holds KB-8 as a single group doc; a split scheme (file naming, roster partitioning, anchor stability) remains undesigned and none is improvised | Retrieval/navigation degradation in pilot, or the MCP session finds group docs too large to serve |
| KB-F | Trust semantics of repo-level human docs (`index.md`, `conventions.md`, `_notes.md`): do they need `status` front-matter for the MCP trust blocks? | No front-matter, KB-1-exempt (§4.6, amended by D-49: optional `human-notes` front-matter on `_notes.md`); the MCP server serves them without a trust block | CP-4/M1 MCP server session, when the trust-block consumer exists |
| KB-G | Purpose-merge scope growth: entity/metric one-liners into indexes (D-49.7) | **Parked** — v1 merges only the §4.2/§4.7 purpose fields; no new prose sources | Demonstrated retrieval need for entity/metric purposes in machine indexes |
