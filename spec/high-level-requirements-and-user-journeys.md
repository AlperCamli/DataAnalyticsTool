# Context Layer — High-Level Requirements & User Journeys

Status: v1, consolidated from planning discussion (Rounds 1–3, July 2026). Companion to `context-layer-v1-spec.md` (product spec), `platform-architecture.md` (platform & stack), and `phase1-supabase-ga4-gsc-plan.md` (first deployment). This document sits *above* the contract and interface specifications: it fixes the roles, journeys, agent surface, and pipeline-handling protocols that every downstream spec must serve. When a lower-level spec conflicts with this document, the conflict is resolved here first.

Decision provenance: everything below was settled through a bounded three-round discussion (roles & journeys → agent surface → pipeline protocols). Items that remained contested carry a provisional default and appear in the Open Decisions register (§10).

---

## 1. Purpose and scope

This document answers, in order: who uses the system and how their work changes (§3–§4), what the system-level journeys are and how they vary per customer (§5), how failures are detected and handled when agents cannot detect them themselves (§6), what agent surface we ship — profiles, skills, MCP tools (§7), and which standardized protocols govern every customer data-pipeline topology we encounter (§8–§9).

It deliberately does not contain interface signatures, schemas, or wire formats. Those descend from this document into the contract specifications (§11).

## 2. Foundational framing

Three locked decisions from the product spec shape everything in this document and are restated here because every section leans on them.

**The product contains no LLM.** Therefore "which agents do we need" resolves to "which agent *profiles* and *skills* do we ship." An agent in this system is: the customer's own Claude Code session + a profile (tool allowlist, skills bundle, CLAUDE.md fragment, limits) + the MCP server enforcing that profile server-side on every call. The agent catalog is a set of YAML files and skill packages — cheap to add, version, and customize per customer.

**Git holds knowledge, Postgres holds operations.** Docs, entities, metrics, conventions, and profiles live in the KB git repo; runs, logs, audit, benchmarks, and the fault ledger (§6) live in Postgres. Every knowledge change is a PR; every operational event is a row.

**Enforcement is server-side.** Client-side configuration is convenience only. The MCP server evaluates every tool call against (user's OIDC roles ∩ profile allowlist). This is also what makes the fault ledger's deterministic detectors possible: the complete agent action stream flows through surfaces the deterministic product controls.

## 3. Roles

Five roles. R1–R4 are product personas; R5 is our own internal deployment role, included because its journey must be standardized, not improvised, for per-customer instantiation to scale.

### R1 — Business user (non-analyst)

The revenue-justifying persona.

**As-is workflow:** has a question → files a ticket or Slack message to the data team → waits days → receives a dashboard that half-matches the intent → iterates over more days → often gives up and exports to Excel. Zero self-service beyond canned dashboards; the data team is the bottleneck.

**To-be workflow:** opens Claude Code under the Reporter profile → describes the report in plain language → the agent resolves entities and metrics from the KB, validates SQL, executes governed, and returns a result or a one-click template link. Time-to-report drops from days to minutes. The data team enters the loop only as PR reviewer (reporting views), not as author.

**What this journey demands from the product:** `search_context` / `get_entity` / `get_metric` resolution quality; the `report` skill's guided, checkpointed flow; the publish path per BI adapter capability class (§8, P5); honest dead-end handling via `flag_gap` (§6).

### R2 — Data / analytics engineer (context steward)

The adoption-deciding persona: if this role distrusts the KB, nobody uses it.

**As-is workflow:** report factory plus tribal-knowledge keeper. Documentation exists in five stale places; schema changes break dashboards silently; lineage lives in their head; the request queue never empties.

**To-be workflow:** the job shifts from *writing reports* to *curating context*. They run `enrich` to draft documentation as PRs, review nightly sync PRs with `review-sync`, repair contaminated docs, certify metrics, review agent-authored reporting-view PRs, and triage the fault-ledger queue in KB Health. The KB Health dashboard is their home screen.

**Demands:** enrich/review-sync skill quality; contamination-flow ergonomics; ownership-zone mechanics that never overwrite human work; a fault-ledger triage queue that converts agent dead-ends into an ordered work list.

### R3 — Platform admin / ops

**As-is:** not applicable (new product), but the reference point is every other self-hosted tool they run; the journey is judged as "how painful is this compared to running GitLab."

**To-be:** Compose/Helm install → connect sources via the Connections module → wire OIDC → create and assign profiles → watch health. Two stateful dependencies only (git, Postgres).

**Demands:** installation and upgrade documentation; credential-reference UX (vault references, never raw secrets); per-connection health surfaces; freshness warnings (§8, P1 sync policy).

### R4 — Security / compliance reviewer

Gatekeeper at pilot milestone M2.

**As-is:** reviews vendor questionnaires; blocks anything that phones home or touches production systems ungoverned.

**To-be:** reviews a self-contained security pack (data flows, identity model, audit specification, RLS boundary statement), then periodically audits live behavior through the Audit module.

**Demands:** audit-log completeness (user, intent, SQL, target, rows, duration on every execution); deterministic guardrails they can verify rather than trust; a minimal, enumerable MCP tool surface (§7).

### R5 — Vendor deployment engineer (internal)

**Journey:** discovery checklist → topology classification against the case matrices (§8) → connector configuration → KB bootstrap (J1) → benchmark seeding → profile setup with the customer. The standardization rule: onboarding is the *execution of a decision tree*, never a design exercise. A customer topology that does not fit an existing case is handled per the extension rule in §9.

## 4. Handoff map

The product's real effect is moving work across the R1/R2 boundary: business users gain authoring; data engineers gain review. The handoff points are where most design decisions hide, so they are named explicitly:

| Handoff | From → to | Mechanism | Design consequence |
|---|---|---|---|
| Recurring report needs SQL backing | R1's agent → R2 | Reporting-view migration PR authored by the agent | PR is the interface; R2 reviews SQL, not requirements prose |
| Agent hits a KB gap | R1's agent → R2 | `flag_gap` → fault ledger → KB Health triage queue | Dead-ends become assignable work items, not silent failures |
| Schema drift contaminates docs | Sync engine → R2 | Drift PR + contamination flags + `review-sync` skill | R2 is pointed at exactly the docs needing repair |
| New user/team onboards | R3 → R1 | Profile assignment (OIDC group → profile) | Access is a config change, not a provisioning project |
| Security wants evidence | System → R4 | Audit module + audit log export | Measurement is the audit trail itself; no manual tracking |

## 5. System journeys

Role journeys describe individuals; system journeys cut across roles and are where per-customer variance concentrates. Three are primary.

### J1 — KB creation

Variance runs along two independent axes, each with a standard protocol.

**Axis 1 — how schema is obtainable** (resolved by protocol P1, §8): DDL/migration files → ephemeral introspection; live database → read-only direct introspection; API source → metadata endpoints; locked-down system → replica reads or offline exports. The snapshot contract guarantees identical output across modes, so the mode choice is operational, not architectural.

**Axis 2 — how much documentation exists** — the **documentation maturity ladder** (protocol P4, §8):

- **Level 3 — real documentation exists.** Harvest via `KnowledgeProvider`, land as human-owned docs with `sources` front-matter citing the origin document. Human review confirms; status can reach `verified` quickly.
- **Level 2 — no docs, but evidence exists** (DB comments, DDL structure, query history). Generate machine-owned docs; the `enrich` skill drafts semantics *grounded in that evidence*, landing as PRs with status `draft` and evidence-grade `sources` ("join path observed in historical queries" vs. "inferred").
- **Level 1 — bare schema only.** Machine docs plus enrich drafts inferred from names and (opt-in, masked) samples. Everything is marked `draft` with `sources: inferred`, and certification to `verified` **requires** human verification before agents treat the content as trustworthy. Skills warn users when answers rest on unverified docs.

Maturity is assessed **per source, not per customer** — a customer can be Level 3 on their OLTP and Level 1 on their GA4 setup. "The customer has nothing" is a defined case with a defined ruling, not an improvisation.

### J2 — KB update

Three triggers, converging on one review surface (the PR flow):

1. **Source schema change** → sync engine → drift PR, fired by CI webhook (near-zero lag on intentional change) and/or scheduled re-snapshot (catches out-of-band change), per the customer's configured sync policy (§8, P1).
2. **Manual human edit** → ordinary git PR. Explicit rule the documentation must teach: manual edits to *machine-owned* files are overwritten on the next regeneration — semantics belong in the human-owned file. Sync never writes to human-owned files; it only flags them.
3. **Agent-proposed change** — enrich output, or enrichment work arising from `flag_gap` entries — → PR opened under the triggering user's identity.

One review surface regardless of trigger keeps R2's burden predictable and the audit trail uniform.

### J3 — Report creation

Explicitly multi-role: the same journey skeleton — resolve → validate → execute → publish — is executed by any role whose profile permits it, with the profile parameterizing permissions, limits, execution targets, and publish targets per department or unit. The design consequence: **we do not design per-department journeys; we design one journey parameterized by profile.** The terminal state of the journey (full publish vs. template link vs. SQL handoff) is determined by the BI target's capability class (§8, P5), and the `report` skill reads those capability flags to set user expectations *before* the journey starts, not at the moment of failure.

## 6. Failure handling — the fault ledger

Design principle: **never rely on agent self-awareness as the primary failure detector.** An LLM frequently cannot know it has failed. The structural advantage we exploit: every agent action flows through the MCP server and execution gateway (server-side enforcement), so the deterministic product observes the complete action stream despite containing no LLM.

Three detector classes, in descending order of trust:

**Class 1 — deterministic detectors (server-side, primary).** Pattern rules over the audit/action stream, no LLM involvement — failure inferred from behavior the way a web product infers failure from funnels:
- `validate_sql` failing repeatedly against the same object → probable doc/schema mismatch.
- `search_context` returning zero or low-confidence results → coverage gap.
- Guardrail hits: timeouts, row caps, quota exhaustion.
- A session with report intent that never reaches a terminal action (execute/publish) → abandoned journey.

**Class 2 — agent self-reports (secondary, best-effort).** The `flag_gap(object, kind, description)` MCP tool. Skills instruct the agent to call it at *recognized* dead ends — an undocumented table, an uncertified metric, a missing join path between systems. The server writes the entry to the fault ledger tagged with user, session, and profile; the agent tells the user what is missing and that the data team was notified. Useful signal, but explicitly one of three classes, never the mechanism — because the agent will not always know it is stuck.

**Class 3 — human reports (ground truth).** The `report` skill ends by asking the user to confirm the result looks right; a negative lands in the ledger. R2 can file entries from the dashboard. The golden benchmark in CI is the systematic form of this class.

**Ledger mechanics.** The ledger lives in Postgres (operational state, per the git/Postgres rule). Entries link to KB objects where attributable, surface in the KB Health module as a triage queue for R2, and resolve into either an enrichment PR or a doc fix — closing the loop into journey J2, trigger 3.

**Stated limitation — the silent semantic error.** SQL that validates, executes, and is *wrong* (bad join, wrong metric interpretation) is undetectable in-line by any of the three classes. Mitigations are structural, not detective: certified metrics shrink the space where agents improvise; trust signals steer agents away from `draft`/`stale` docs; skills refuse to build on `contaminated` docs without explicit user override; and the benchmark-in-CI catches systematic versions. This limitation is stated plainly in customer-facing documentation and in the R4 security pack.

## 7. Agent surface

The deliverable is: profile templates + a skills package + the MCP tool surface. All three are product artifacts; only profiles vary per customer.

### 7.1 Shipped profile templates

Customers instantiate and customize these (dashboard CRUD → git commits under the editing user's identity):

| Profile | Serves | Skills | Tools (beyond the read/resolve set) | Character |
|---|---|---|---|---|
| **Reporter** | R1 | `report` | `validate_sql`, `execute_sql:<allowed systems>`, `publish_report:<allowed targets>`, `flag_gap` | Guided journey, tight limits (row cap, timeout), publish restricted to role-mapped workspaces |
| **Explorer** | Analyst-grade users | none (unguided) | Same as Reporter; publish optional per customer | Ad-hoc investigation, higher limits, no state-machine guidance |
| **Steward** | R2 | `enrich`, `review-sync`, `benchmark` | Full read + `validate_sql` + `execute_sql` + `list_gaps`; **no MCP write surface** | KB writes happen via git PRs in the Claude Code session itself |
| **benchmark** (non-user) | CI / harness | `benchmark` | Read set + `validate_sql` + `execute_sql` + `list_gaps`; **no publish** | Audit-tagged; excluded from adoption metrics; not role-assignable to humans by default (skill spec SK-4) |

The Steward ruling keeps the security story clean: the MCP surface remains read/execute/publish only; all knowledge mutation goes through git PRs.

### 7.2 MCP tool surface

The product-spec §6 tool table **plus two additions**: `flag_gap` (agent self-reports, §6) and `list_gaps` (Steward-gated triage reads, added through the OD-5 register process — fault-ledger spec §12). Standing rule unchanged: resist adding tools — every tool is security-review surface, and every proposal goes through the register.

### 7.3 Skills as state machines

What makes agent behavior *protocol* rather than vibes: each shipped skill is specified as a **state machine with mandatory checkpoints**. Reference specification for `report`:

```
intent → resolution → drafting → validation → execution → presentation → [publish]
```

- **resolution**: must present the resolved entities/metrics to the user for confirmation before drafting.
- **validation**: hard gate — `validate_sql` must pass before execution is attempted.
- **presentation**: must ask the user-confirmation question (fault-ledger class 3).
- **Every state defines its failure exit**, and every failure exit routes to `flag_gap` plus a user-facing explanation of what is missing and who was notified.

Mandatory trust behaviors carried by all skills: warn when relying on `draft` or `stale` docs; refuse to build on `contaminated` docs unless the user explicitly overrides; state the publish-capability ceiling of the target (P5) at journey start.

### 7.4 Skill variance rule

**Skills are fixed product artifacts, identical across customers.** All customer variance is pushed into profiles, `conventions.md`, and CLAUDE.md fragments. This keeps skills testable, benchmarkable, and upgradeable as versioned product components; anything customer-specific lives in the customer's KB.

## 8. Data-pipeline handling protocols

Purpose: a new customer's topology maps onto predefined cases with predefined rulings, so onboarding (R5's journey) is a decision tree. Five case matrices.

### P1 — Source access protocol

*How do we get schema out of a system?*

| Case | Topology | Ruling |
|---|---|---|
| A | DDL / migration files exist | Ephemeral introspection: apply DDL to a throwaway container, introspect as if live. No live access needed to start |
| B | Live DB access grantable | Read-only role, direct introspection over system catalogs |
| C | API source (GA4, GSC, SaaS) | Metadata endpoints via the source's API |
| D | Locked-down system (SAP-class) | Replica reads or periodic offline exports |

Standing ruling: **always start with the least-privileged mode that works and upgrade later.** The snapshot contract guarantees identical output across modes, so starting cheap costs nothing. Every connector declares which modes it supports; every source lands in exactly one case at onboarding.

**Sync trigger policy (per-customer configuration — all three modes supported):** the system ships all of the following, selected and combined per customer at onboarding:

1. **CI webhook** on the customer's migrations/pipeline repo — near-zero-lag tracking of intentional change; works in both DDL-file and live modes. Recommended default wherever the customer has CI.
2. **Scheduled re-snapshot** (default nightly, configurable) — catches out-of-band change; requires live or API access (cases B/C/D).
3. **Manual re-submission with freshness monitoring** — for case-A customers without CI integration: the KB updates when they re-send DDL, and the dashboard shows a prominent freshness warning once snapshot age exceeds a configurable threshold, with optional scheduled "re-confirm your DDL" reminders.

The chosen combination is recorded in `.contextlayer/` sync policy and surfaced in the Connections module. Staleness risk under mode 3 is documented to the customer explicitly at onboarding.

### P2 — Execution topology protocol

*Where do agent queries run?*

| Case | Topology | Ruling |
|---|---|---|
| A | DW exists | All reporting queries route to the DW; OLTP/SAP questions route via entity docs to replicated copies. SAP is never queried directly |
| B | No DW, OLTP read replica exists | Execute on the replica; reporting-views pattern for recurring reports |
| C | No DW, no replica | Governed direct-OLTP: read-only role, statement timeout, row cap; reporting views mandatory for anything recurring |
| D | API-only sources | Quota-aware API execution with session-level result caching |

Standing ruling: the execution policy is **encoded in the KB and enforced by the gateway**, chosen from this matrix at onboarding, never improvised per query. A production system incident caused by agent load is the pilot-ending event this protocol exists to prevent.

### P3 — Lineage evidence protocol

Three evidence tiers, used in priority order:

1. **Pipeline-tool metadata** via `LineageProvider` connectors (dbt manifests, Airbyte/Fivetran configs) — where tooling exists.
2. **Core SQL parsing** of view and model definitions — always on, every deployment; pipeline-less customers still get a full graph with column-level edges.
3. **Human-declared annotations** for opaque steps (stored procedures, external scripts).

Ruling: every lineage edge records its evidence tier; trust propagation treats human-declared edges as weakest.

### P4 — Documentation maturity protocol

The J1 ladder (§5) as a formal matrix, assessed **per source** at onboarding:

| Level | Customer state | Ruling |
|---|---|---|
| 3 | Real documentation exists | Harvest via `KnowledgeProvider` → human-owned docs, `sources` cite origin → fast path to `verified` |
| 2 | No docs; comments / DDL / query history exist | Machine docs + evidence-grounded `enrich` drafts, status `draft`, evidence-graded `sources` |
| 1 | Bare schema only | Machine docs + inference-only drafts, `sources: inferred`; human verification **required** before `verified` status; skills warn on unverified content |

### P5 — Publish capability protocol

BI targets are classified by their `Publisher` capability flags, which determine the terminal state of journey J3:

| Class | Target capability | Terminal state of J3 |
|---|---|---|
| Full authoring API | e.g. Power BI (PBIP/TMDL + Fabric APIs) | Agent publishes end-to-end |
| Template/link APIs only | e.g. Looker Studio (Linking API + reporting views) | Agent ships reporting-view PR + pre-wired template link; one human click instantiates |
| No usable API | — | Agent delivers validated SQL + step-by-step instructions |

Ruling: the adapter's flags are recorded at onboarding, and the `report` skill reads them to set user expectations **before** the journey starts, not at the moment of failure.

## 9. Cross-cutting standardization rules

1. **Case-matrix extension rule:** a customer topology that fits no existing case is an Open Decisions item and a case-matrix extension — never a one-off hack. The matrices in §8 are living parts of the spec.
2. **PR convergence rule:** every knowledge change — machine, human, or agent-proposed — lands as a PR into the KB repo. One review surface, one audit trail.
3. **Least-privilege-first rule:** every integration starts in the least-privileged access mode that works (P1) and upgrades only when value justifies it.
4. **Server-side enforcement rule:** no client configuration can widen access; profiles are evaluated on every MCP call.
5. **Honest-failure rule:** agents never guess past a recognized gap; they flag, explain, and route (§6). Dead-ends are the KB's growth signal.

## 10. Open Decisions register

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| OD-1 | Silent semantic errors (validating, executing, wrong SQL) have no in-line detector | Accept as stated limitation; mitigate via certified metrics, trust signals, benchmark-in-CI | If pilot evaluation shows correctness failures the benchmark misses |
| OD-2 | Deterministic detector rule set (class 1) | **Partially resolved** — rules + defaults are ops configuration (fault-ledger spec §5); remaining open scope is threshold values | After first month of pilot audit data |
| OD-3 | Freshness-warning threshold for P1 sync mode 3 | Snapshot age > 30 days ⇒ dashboard warning (configurable) | Per customer at onboarding |
| OD-4 | Explorer profile publish rights | Off by default, per-customer opt-in | First customer request |
| OD-5 | New MCP tools beyond §6 + `flag_gap` | Register exercised once — `list_gaps` approved (fault-ledger spec §12); otherwise none | Any proposal enters this register first |

## 11. Documentation roadmap — what descends from this document

This document is the root. The next layer is the **contract & interface specifications**, in dependency order:

1. **Snapshot schema spec** — versioned JSON Schema, additive-evolution rules, hashing/normalization semantics. (Blocks phase-1 tasks 1.1–1.4.)
2. **Job protocol spec** — the language-agnostic connector contract.
3. **Capability interface specs** — `MetadataProvider`, `QueryExecutor`, `Publisher` + flags, `LineageProvider`, `KnowledgeProvider`, `UsageProvider`.
4. **KB repository specification** — layout, front-matter, ownership zones, doc templates (formalizing product-spec §5 and the phase-1 plan §5).
5. **MCP tool reference** — §6 table + `flag_gap`, with role-gating and trust-signal payloads.
6. **Skill specifications** — the state machines of §7.3, one per shipped skill.
7. **Lineage graph format** and **intermediate report artifact format**.
8. **Fault ledger schema** — Postgres tables, detector rules, KB Health triage queue contract.

Each spec must cite the sections of this document it implements; changes that contradict this document require amending it first (via PR, like everything else).
