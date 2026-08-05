# Customer Onboarding Playbook — Signed Agreement → Report-Ready KB (v1)

Status: v1. This is role R5's journey (`high-level-requirements-and-user-journeys.md` §3) expanded into an executable playbook: every step names its actors, the components/skills/tools it uses, the protocol or spec that governs it, its **variations** (drawn from the HLR §8 case matrices — onboarding is the execution of a decision tree, never a design exercise), and its exit criterion. It ends at report-readiness: the state where an agent under a Reporter profile can run journey J3 end-to-end against the customer's estate.

Companion: §11 (KB storage & distribution model) resolves where the KB lives and how departments and roles get scoped access — the central-plus-local question.

---

## 1. Inputs: the signed-agreement packet

Onboarding begins by issuing the **ask list** (generalizing phase-1 plan §8 / product spec §12) and receiving:

1. Per data source: what exists (DDL/migrations repo? live access grantable? API? locked system?), and any existing documentation (files, wiki spaces, Drive folders).
2. Platform facts: git server (GitHub Enterprise / GitLab / Azure DevOps), IdP (OIDC), secret store, container platform (Compose-class VM vs K8s), network posture (internet-connected vs air-gapped).
3. BI target(s) and licensing tier.
4. Pilot seeds: 3–5 target non-analyst users, the roles/departments in scope, and **10–50 real report requests with any existing SQL** (golden-benchmark seed).
5. Named counterparts: R2 (data team lead — the adoption decider), R3 (ops owner), R4 (security contact).

## 2. Pipeline overview

```
0 Discovery & topology classification
1 Platform install                          ┐ R3-heavy
2 KB repo bootstrap                         ┘
3 Connect sources → first snapshots         ┐
4 Generation: machine KB + lineage          │ machine phase (deterministic)
5 Enrichment: human semantics (P4 ladder)   ┐
6 Entities & metrics                        │ knowledge phase (R2 + skills)
7 Profiles, roles, dashboard                ┘
8 Golden benchmark baseline
9 Readiness gate & handover                 → report-ready (M1 posture)
```

Steps 3-per-source run in parallel; 5 and 6 overlap; 7 can start any time after 2. The critical path is almost always **credential/approval lead time in step 3** — start those asks at step 0.

## 3. Step 0 — Discovery & topology classification

**Actors:** R5 with R2/R3. **Governing specs:** HLR §8 case matrices P1–P5.

Every source and target is classified — this record drives all later config:

| Classification | Question | Cases |
|---|---|---|
| P1 access mode, per source | How do we get schema out? | A DDL files · B live read-only · C API · D replica/export |
| P1 sync policy, per source | What triggers re-snapshot? | webhook · scheduled · manual + freshness monitoring (any combination) |
| P2 execution topology | Where do agent queries run? | A DW · B OLTP replica · C governed direct-OLTP · D API-only |
| P3 lineage evidence | What attests data flow? | pipeline-tool present? · SQL-parse (always on) · human annotations expected? |
| P4 doc maturity, per source | What documentation exists? | L3 real docs · L2 comments/DDL/history · L1 bare schema |
| P5 publish capability | What can the BI target do? | full · template_link · none (+ tenant-dependent flags) |

**Standing rulings applied here:** least-privileged access mode first (HLR §9.3); a topology fitting no case goes to the Open Decisions register as a case-matrix extension, never a one-off hack (HLR §9.1). **Exit:** topology record signed off by R2/R3; credential/approval requests filed (the long pole starts ticking).

## 4. Step 1 — Platform install

**Actors:** R3, supported by R5. **Components:** core (MCP server, gateway, sync orchestrator, job API, dashboard), Postgres, connector runner(s). **Governing specs:** platform-architecture §3–§4; job protocol §3 (runner networking is outbound-only — firewall conversation is one sentence).

| Variation | Path |
|---|---|
| Small / VM | Docker Compose bundle |
| Enterprise K8s | Helm chart (same images) |
| Air-gapped | Offline image bundle; git server and IdP must be reachable in-network |

Wire OIDC (customer IdP → MCP OAuth + dashboard session), register the vault (credential *references* only — the product never stores secrets, J-4), create the runner's vault identity. **Exit:** dashboard reachable, OIDC login works, a runner claims a `test_connection` no-op against a stub.

## 5. Step 2 — KB repo bootstrap

**Actors:** R5 (mechanical) + R2 (review). **Components:** generator (bootstrap mode). **Governing specs:** KB repository spec §3, §10; ruling K-7.

Create the KB repo on the **customer's git server**; the generator bootstraps: root `index.md` and `conventions.md` (written once, human-owned thereafter — conventions content is *rendered from the step-0 topology record*: system classes, the P2 execution ruling, quota notes, trust behaviors); `.contextlayer/` (`sources.yaml`, `sync-policy.yaml` from the P1 rulings, `roles.yaml` skeleton, `profiles/` templates, `dashboard.yaml`); and the **KB CI workflow** (checks KB-1…KB-9) installed on the repo — from this commit forward, every change to the KB is schema-validated, link-checked, and (later) benchmark-guarded.

**Customer KBs are private from bootstrap.** (Ruling D-96.3b.) The repo is created private and stays private; visibility is a customer decision made deliberately, never a default nobody re-decided. A KB accumulates a readable map of the estate — schema semantics, entity key mappings, certified metrics, report lineage — and that map is exactly what a public repo publishes. The pilot KB (`AlperCamli/DataAnalyticsTool`) is **public by explicit owner choice, as a reference estate on the owner's own data**, and says so in its `index.md`; it is the stated exception, not the pattern to copy.

**Exit:** repo exists **and is private**, CI green on the bootstrap commit, `conventions.md` reviewed by R2 (their first ownership act).

## 6. Step 3 — Connect sources → first snapshots

**Actors:** R3 (ops owner — registers connections, holds credentials), R5 (config), R2 (steward — reads). **Components:** dashboard **Connections** module, the Connections API behind it, connector runners, job API. **Governing specs:** connector manifests (capability spec §3 — `config_schema` is the contract each `config` block is validated against), job protocol (claim/lease/deliver), snapshot spec (validation on receipt, J-6), dashboard spec §3/§4.

**Amended 2026-08-06 (A-3 + B-2).** This step used to describe a vendor CLI writing the connection registry directly — E2's stand-in since D-63.8, and the reason CP-8 graded this step ASSISTED. It is written out. There is now one governed API, a browser module in front of it, and a CLI that is a peer client of the same endpoints; nothing below requires a vendor engineer or a database shell.

### 3.1 Register each source

Sign in to the dashboard at `<core-url>/app/` with the customer's own IdP identity and open **Connections**. Registering, changing, deleting and testing are **ops acts** and are checked server-side against the caller's OIDC roles (`CORE_DASHBOARD_ADMIN_ROLES`, default `ops` — R3's group in `roles.yaml`); a steward sees the same screen read-only; anyone else is refused by the server. Nothing about that gate lives in the browser.

Per source, by P1 case — the `config` block is the connector's own schema, so its fields are the ones that connector documents:

| Case | Concrete flow | Notes |
|---|---|---|
| A — DDL files | Customer hands DDL/migrations → register with `mode: ddl-file` (`ddl_files`, `image`) → `snapshot` job runs an ephemeral container | Zero live access needed; fastest possible start. Test reports **no credential tested** here, because there is none — the source is a set of files |
| B — live | Read-only role created by the customer's DBA → register with `mode: live` and a **credential reference** → `live` mode snapshot | Mode invariance (snapshot C-3) guarantees a later A→B upgrade produces no spurious diffs |
| C — API | Service account (GA4 read access, GSC verified property) → register with `mode: api` and a credential reference | Quota policy from the manifest; deferral semantics J-5 already handle throttling |
| D — locked | Replica DSN or scheduled offline exports | The snapshot boundary hides the difference from everything downstream |

**Credential references only, enforced.** A connection stores `env://NAME` (or `vault://PATH` once A-4 lands) — never a password, DSN, or key. The form says so and has no field to type a secret into; a payload carrying credential material is refused with `raw_secret_rejected` naming the *field* and never echoing the value (J-4). The value itself lives where the runner's resolver reads it, and rotating it needs no change to the connection.

**Registration is proved, not asserted.** The response is the row re-read from the store after the write; a write the store did not take answers `write_not_observed` and reports no success. This closes the D-84 class by construction — "registered" is the store's statement, not the writer's.

### 3.2 Test each source

Press **Test connection** (or `cli.js sync test SYSTEM`). This enqueues a `test_connection` job, which a runner claims and executes with the connector's **builtin probe** (capability §3 `health_probe: builtin`): the config gate, plus each preflight surface the connector declares — for Postgres, connecting as the introspection role and checking it holds neither SUPERUSER nor BYPASSRLS (D-71.2), and the G3 execution-role wall.

Read the verdict literally. A capability the probe could not exercise is listed as **unprobed** and is *not* a pass: publisher adapters (Looker Studio, Power BI) report `unprobed: [publish]` today, because the CI-5 tenant probe is unbuilt. If no runner hosts the connector, the answer is `pending` with the job id — never a failure of the source.

**When a credential is wrong**, the probe fails `auth_error` and the module renders a **re-auth prompt** naming the credential *reference* whose value needs refreshing, with what to do about it. That is the whole loop: fix the value where the resolver reads it, press test again.

### 3.3 Arm the sync policy

Wire the triggers per source in `.contextlayer/sync-policy.yaml`: CI webhook on their migrations/pipeline repo (`/v1/hooks/{system}`, JP-4 — the per-hook secret is `cli.js sync hook set SYSTEM`, printed once), and/or a schedule, and/or manual resubmission with a freshness threshold (OD-3). Take the first snapshot from the module's **sync now** (or `cli.js sync now SYSTEM`).

**Failure handling is already specified:** bad credentials → `auth_error` → the re-auth prompt above; unreachable source → retries → health warning; invalid snapshot → dead-letter (a connector bug, our problem).

**Exit:** the dashboard is reachable and the customer's own identity signs in; every source appears in **Connections** with health; **Test connection** passes on each (or names, per source, exactly which capability went unprobed and why); one accepted snapshot per system; health **green** — meaning an accepted snapshot inside that system's freshness threshold with no failed last job. Health that reads `amber` or `unknown` is a statement about the estate, not a formatting problem: `amber` means no snapshot has been accepted yet or no policy entry states how old one may get, and `unknown` means `sync-policy.yaml` could not be read at all. None of the three is a green with an asterisk.

## 7. Step 4 — Generation: the machine KB

**Actors:** none (deterministic) + R2 merges. **Components:** generator, core SQL lineage parser. **Governing specs:** KB spec §3–§4 (machine docs, front-matter), formats spec §3 (graph.json), generator idempotency (KB-8).

The generator renders every snapshot object into machine-owned docs (`*.schema.md`, per-system/per-schema `index.md` with hot/stub placeholders) and derives lineage: the core parses every captured view/model definition into column-level edges (evidence tier `sql-parse` — even pipeline-less customers get a full graph, P3), merging any `LineageProvider` output where step-0 found tooling. Everything lands as the **initial generation PR**; KB CI validates; R2 merges — their first drift-flow experience, deliberately on a zero-risk all-additive PR.

**Exit (phase-1 gate):** an agent reading only the merged machine KB can correctly describe the estate — verified by a scripted session against `search_context`/`get_table`/`get_lineage`.

## 8. Step 5 — Enrichment: human semantics (the P4 ladder in action)

**Actors:** R2 under the Steward profile; R5 pairs on the first batch. **Components:** Claude Code + `enrich` skill, `harvest` jobs (KnowledgeProvider), MCP read tools. **Governing specs:** skill spec §6 (state machine, CP-E1..E3), KB spec §4–§6 (front-matter, `depends_on` duty), HLR §8 P4.

Per source, by maturity level:

| Level | Flow | Evidence grading in `sources` |
|---|---|---|
| L3 — real docs | `harvest` jobs pull the customer's docs (Drive/Confluence/wiki) → enrich converts each into canonical human docs, `mentions` seeding `depends_on` | `customer doc: <uri>` — fast path to `verified` |
| L2 — comments/DDL/history | enrich drafts grounded in DB comments, structure, and (where present) usage evidence | `observed in N queries` / `from DB comment` |
| L1 — bare schema | enrich drafts by inference from names (+ opt-in masked samples) | `inferred from column names` — **human verification mandatory** before `verified` |

Discipline enforced by the machinery, not by diligence: drafts land as PRs under the session user's identity (K-IDENT), always `status: draft` (the skill *cannot* certify — KB-7 blocks a `verified` without a human-set `last_verified`), never touching machine files (KB-3 warns, regeneration reverts). Scope follows the usage principle: hot objects first, stubs stay stubs. **The customer's review of these PRs is the certification act** — each merge with `status: verified` is a human putting their name (`last_verified`) on a doc. **Exit:** hot objects across all sources carry human docs; every L1-sourced doc that agents will rely on for reporting is human-verified.

## 9. Step 6 — Entities & metrics

**Actors:** R2 + the business counterparts who own definitions. **Components:** enrich skill (drafting), MCP `get_lineage` (evidence). **Governing specs:** KB spec §4.3–§4.4 (entity/metric front-matter, `maps:`, `implementations:`), formats spec §4.5 (blend keys), snapshot §4.4 rationale (cross-system relations are human knowledge — no source can attest them, so this step cannot be automated away).

Entity docs are drafted for the concepts the pilot's report requests actually need (the 10–50 seed requests tell us which — typically 3–6 entities: customer/user, product/page, order/conversion, region…): concrete key mappings per system, routing guidance (which system answers which question, per the P2 ruling), and — where P5 said `cross_source: blending` — the documented blend keys that journey J3 will depend on. Metric docs are seeded **from the customer's own SQL** in the benchmark packet: their de facto definitions become certified `metrics/` entries, each with per-system `implementations` and an owner. **Exit:** every seed report request resolves to documented entities and certified (or explicitly draft-flagged) metrics — checked by running `search_context` per request.

## 10. Step 7 — Profiles, roles, dashboard

**Actors:** R3 (role mapping) + R2 (profile content). **Components:** dashboard Profiles module, profile compiler. **Governing specs:** platform-architecture §5, HLR §7.1 (+ the `benchmark` profile amendment), MCP §3 (server-side enforcement), KB spec `.contextlayer/` layout.

Map OIDC groups → `roles.yaml` visibility (directory-level, KB-A) and instantiate the four profile templates with the customer's specifics: Reporter (which systems executable, which workspaces publishable, limits), Explorer (opt-in publish, OD-4), Steward, `benchmark`. Departmental flavor goes in each profile's CLAUDE.md fragment — *not* into forked docs (§11). Export the one-click Claude Code setup per profile. **Exit:** a pilot user in the right OIDC group connects Claude Code with the exported setup and `tools/list` shows exactly their allowlist (MT-1 live).

## 11. KB storage & distribution model (the central + local question)

**Ruling: one physical source of truth, many scoped access forms — projection and compilation, never forked copies.**

The KB is a **git repository on the customer's own git server** (locked decisions #2/#5) — not a file, and not on our infrastructure. Ops Postgres holds only operational state (snapshots, audit, ledger, benchmarks); no knowledge lives there. On top of that single repo, four access forms cover every "local copy" need:

| Consumer | Form | Freshness | Writes | Governing mechanism |
|---|---|---|---|---|
| Agents & business users (per department/role) | **Role-scoped live projection** via the MCP server — each role sees a filtered slice computed at read time | Always current (merged HEAD + latest snapshot); trust blocks computed live | None (read surface) | `roles.yaml` visibility + profile allowlists, enforced server-side (M-3/M-4) |
| Departmental flavor | **Profile CLAUDE.md fragment** — conventions, preferred metrics, tone | Versioned in the KB repo itself | Via profile PRs | Platform-architecture §5 |
| Stewards (editors) | **Git-native working copies**, incl. sparse-checkout clones of just their department's directories | Git-current; pulls like any repo | **PR-only** back to the central repo | Ordinary git + KB CI + branch protection |
| Offline sites / no-MCP teams (edge case) | **Compiled read-only bundle** — a generated export of a role's projection, stamped with `kb_ref` + `generated_at`, carrying an expiry warning | Frozen at compile time; self-declares its age | None; never a write surface, never valid for execution decisions (validation always runs against the live snapshot) | Generated artifact, same philosophy as the profile-compiled setup |

**Why not physical partial copies served to agents:** a copy is stale the moment sync merges a drift PR — reintroducing the disease the product cures; contamination flags never reach it; visibility enforcement degrades from read-time (auditable, revocable) to distribution-time (neither); and trust blocks are *uncomputable* locally (`hash_match` requires the latest snapshot). The hybrid intuition is right — departments should see a scoped, relevant slice — and rows 1–2 deliver exactly that while keeping the slice virtual, fresh, and enforced. Row 3 covers the legitimate "local partial copy" for people who *edit*; row 4 covers the rare case where a live connection genuinely cannot exist.

The compiled bundle (row 4) is new surface: recorded as **Open Decision OB-1** — build only when a real offline consumer appears; the format is a compilation target of existing content, so deferring costs nothing.

## 12. Step 8 — Golden benchmark baseline

**Actors:** R5 runs; R2 validates verified outputs. **Components:** `benchmark` skill under the `benchmark` profile + the deterministic scoring harness. **Governing specs:** skill spec §8 (SK-4 — runs are audit-tagged and excluded from adoption metrics), product spec §11.

Convert the seed requests into the golden suite (request + analyst-verified SQL/result). Run three conditions — no KB (live-discovery baseline), machine KB only, enriched KB — establishing the value curve per layer. Wire the suite into KB CI (KB-9): from now on, any KB change that degrades accuracy is caught pre-merge. **Exit:** baseline scores recorded in ops Postgres; the dashboard Benchmarks module shows the three-condition comparison.

## 13. Step 9 — Readiness gate & handover

The gate is a checklist, every item mechanically verifiable:

1. All configured systems: snapshot accepted, health green, sync triggers armed (step 3 exits).
2. Machine KB merged; scripted estate-description session passes (step 4 exit).
3. Hot objects documented; all L1-derived report-path docs human-verified (step 5 exit).
4. Every seed request resolves to entities + certified metrics (step 6 exit).
5. Profiles enforce correctly for a real pilot user (step 7 exit, MT-1).
6. Benchmark baseline recorded and CI-wired (step 8 exit).
7. A staged drift drill: introduce a breaking change in a test object → sync PR appears with correct contamination flag → R2 runs `review-sync` → repair PR → docs re-verified. (Rehearses journey J2 end-to-end before it happens for real.)
8. First real journey J3: a pilot business user, Reporter profile, one of the seed requests, through resolution → validation → execution → confirmation — with publish per the P5 ceiling set in step 0.

**Amendment (D-72.4 / security review #2 F3, 2026-07-21) — credential assertions at the gate.** Item 9 below is additive. It exists because every other item on this list checks something the *platform* does, and these three check what the **customer's own infrastructure** grants us — the layer where a mistake is invisible from inside the product and unrecoverable by any amount of correct code. Each is verified by attribute, never by role name.

9. **Role and credential least-privilege, all three identities.** For every SQL system in the estate:
   - **Execution** (`example_exec`, `deploy/execution-role.sql`) — read-only *at the database level*: none of SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS, no write grant reachable through role membership, no schema CREATE. *Evidence:* the executor's startup check passes against the configured `execute_dsn` (G3), and the file's VERIFY queries return empty.
   - **Introspection** (`contextlayer_introspect`, `deploy/introspection-role.sql`) — neither SUPERUSER nor BYPASSRLS, and no SELECT grant on customer tables (it reads `pg_catalog`, which needs none). *Evidence:* one accepted live snapshot under the dedicated role, byte-identical to the previous role's on unchanged source state (D-71.2).
   - **KB sync** (`contextlayer-sync` PAT, P-H / D-66.7) — fine-grained, scoped to the single KB repository, with contents + pull-request write and nothing else.

   The three are **distinct identities with distinct secrets**, and no DSN is the estate's default `postgres`.

   *Check attributes, not names.* A managed-Postgres `postgres` role may report `rolsuper = false` and still hold BYPASSRLS — observed on Supabase, where it is the BYPASSRLS half of the check that fires (D-71.2). A gate item written against "is it the superuser?" would pass the exact connection this item exists to catch.

**Handover:** R2 owns the steward loop (sync PRs, ledger triage in KB Health, certification); R3 owns Connections health and profiles; R5 drops to release-driven upgrade support. The fault ledger is now the growth engine: every agent dead-end from real usage lands in R2's triage queue and becomes the next enrichment batch — onboarding doesn't end so much as hand its motor to the customer.

## 14. Open decisions (playbook-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| OB-1 | Compiled read-only KB bundles (§11 row 4) | Not built until a real offline consumer exists; format = compilation of role projection | First air-gapped-site or no-MCP-team requirement |
| OB-2 | Who authors entity drafts in step 6 — enrich skill vs R5 hand-drafting for the first customer(s) | Skill-drafted, R5-paired review, always customer-certified | After 2–3 onboardings show which is faster |
| OB-3 | Staged drift drill (gate item 7) as a shipped fixture vs per-customer improvisation | Ship a standard drill fixture (test schema + scripted change) with the product | Build during phase 4 (sync engine) |
| OB-4 | Onboarding duration targets per topology class | Measure the first three; no promises before data | Third onboarding |
| OB-5 | Profile↔database-role pairing: a profile granting `execute_sql` must be paired with a database role scoped no wider than that profile's visible surface (filed by D-72.5; origin security review #2 F2) | Stated as a deployment obligation, not yet a mechanical gate item — D-71.1 makes the KB visibility map govern the execution surface, but the map is our gate and the database role is the wall, and nothing today checks that the wall matches the gate | Next playbook revision for wording; **load-bearing at the first customer with more than one execute-granted profile**, where the two surfaces can first diverge |
