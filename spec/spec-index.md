# Context Layer — Specification Set Index (v1.0)

Entry point for the documentation set. Twelve documents: one requirements root, eight contract specifications, one operational playbook, this index, and the master open-decisions register. Consolidated at v1.0: all cross-spec amendments folded into their home documents (each amending spec retains its amendment section, marked *applied*, as the change record).

## Document map

| Document | Governs | Ruling prefix | Primary consumers | Unblocks (phase-1 tasks) |
|---|---|---|---|---|
| `high-level-requirements-and-user-journeys.md` | Roles, journeys, failure philosophy, agent surface, pipeline protocols (P1–P5), standardization rules | — (root) | Every other document | Frames all |
| `snapshot-schema-spec.md` | The connector→platform data boundary: format, hashing, canonicalization, diff semantics | S-1..8 | Connectors, generator, sync engine, `validate_sql` | **1.1**, 1.2–1.4 |
| `job-protocol-spec.md` | How work reaches connectors and results come back: runners, leases, retries, dead-letter | J-1..8 | Connector SDK, core job API, gateway | 1.2–1.4 (transport) |
| `capability-interfaces-spec.md` | The six capability contracts + connector manifest + guardrail/identity envelopes | CI-1..8 | Connector authors, gateway, adapters | 1.2–1.4, **1.7** (harvest), 1.9 (LP) |
| `kb-repository-spec.md` | Repo layout, ownership zones, front-matter, status lifecycle, contamination scan, KB CI | K-1..8 | Generator, sync engine, MCP server, skills, humans | **1.5**, **1.6**, 1.7, 1.8 |
| `mcp-tool-reference-spec.md` | The eleven-tool surface, enforcement model, validation tokens, trust blocks, audit record | M-1..8 | MCP server, skills, security review | Phase 5 (M1) |
| `skill-specifications.md` | The four shipped skills as state machines; kernel; enforced/attested checkpoints | SK-1..7 | Skill implementations, benchmark harness, acceptance CI | 1.7, 1.8; phase 6 |
| `lineage-and-report-artifact-formats-spec.md` | `graph.json` + intermediate report artifact: models, identity, walks, publish lifecycle | F-1..8 | Lineage merger, contamination scan, adapters, `get_lineage` | **1.9**; phase 8 |
| `fault-ledger-schema-spec.md` | Events/issues model, class-1 detector rules, triage contract, `list_gaps`, loop closure | L-1..8 | Core detectors, KB Health, enrich skill | Phase 5+ (ledger ships with MCP) |
| `customer-onboarding-playbook.md` | Signed agreement → report-ready KB: 10 steps with per-case variations; KB storage & distribution model | — (process) | R5, R2/R3 counterparts | Per-customer instantiation |
| `master-open-decisions-register.md` | Authoritative status of all 48 open/partial/closed decisions | — | Everyone | — |

## Dependency and reading order

```
HLR ─┬─► snapshot ─┬─► capability ─┬─► MCP ─► skills
     │             │               │
     ├─► job ──────┘               ├─► formats
     ├─► KB repo ──────────────────┤
     │                             └─► fault ledger
     └─► onboarding playbook (consumes all)
```

New engineer reading order: HLR → snapshot → job → capability → KB → MCP → skills → formats → ledger → playbook. A connector author needs only: snapshot, job, capability (+ this index).

## Change process

1. **Specs live in git** as `specs/` in the platform repo; this consolidation is the initial commit (v1.0). Changes are PRs — the same discipline the product imposes on customer KBs applies to its own contracts.
2. **Amendment rule (HLR §11):** a change contradicting an upstream document requires amending the upstream first. Additive cross-spec effects are recorded in the amending spec's amendments section and folded home at the next consolidation pass, exactly as done for v1.0.
3. **Open decisions:** new items enter their home spec's register, then the master register; the master is the status authority.
4. **Versioning:** wire formats (`snapshot_version`, protocol version, `graph_version`, `artifact_version`) evolve additively within a version per their own rules; the *document set* version (v1.0) tags consolidation states.

## Known gap (deliberate)

The **sync-orchestrator spec** (webhook ingestion detail — JP-4 — scheduling, and the drift-run pipeline tying snapshot diff → contamination scan → PR authoring into one process) is contracted at every edge but not yet specified as a process. Scheduled for authoring before phase 4 (sync engine) begins; tracked via JP-4.

## What each phase-1 exit criterion now rests on

| Task | Exit criterion | Verified by |
|---|---|---|
| 1.1 | Fixtures validate; diff runs on fixtures | Snapshot §8.1 schema, §8.2 fixtures, C-1 |
| 1.2 | DDL→snapshot identical to live introspection | Snapshot C-2/C-3, capability MP-1, job JC-4 |
| 1.3 / 1.4 | Live GA4/GSC pulls produce valid objects | Snapshot C-1..C-8, manifest CC-1 |
| 1.5 | Idempotent rendering | KB §3/§4/§7 templates, KB-8 |
| 1.6 | Bootstrap merged, CI green | KB §10, playbook step 2 |
| 1.7 | Docs ingested as PRs | Capability KP-*, skill §6, AS-6 |
| 1.8 | Entity drafts reviewed | KB §4.3, playbook step 6 |
| 1.9 | View lineage resolves; `get_lineage` walks | Formats §3, FG-1..FG-5, capability LP-* |
