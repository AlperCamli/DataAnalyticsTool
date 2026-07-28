# Contract Specification — Report Authoring (v1)

Status: v1 draft for implementation. Entry condition for the replaced CP-7/M3 target per Ruling D-91: text-to-report via Power BI. This spec owns the contract by which a plain-language request in a customer's Claude Code session becomes a finished, AI-designed, trust-annotated Power BI report in the customer workspace — with zero manual wiring by the reporter.

It is written to the D-91.4 invariants, which are its spine and are restated here as rulings RA-1..RA-5. Everything agentic happens in the customer's Claude Code session (no LLM in the product); the data plane is deterministic and core-owned; the visual plane is the agent's, recorded back into the artifact; trust renders inside the report; all Microsoft surfaces get the D-89 guardrail treatment.

Closes register item **CI-F by supersession** (D-91.6). Authorizes the four additive amendments named in §12, each diff leading its PR per the amendment fence.

---

## 1. Scope

**In scope:** the session topology (which MCP servers a reporting session connects and what each may do); the authoring pipeline as a normative stage sequence extending the report skill's CP-R flow; the model-delivery contract (data plane); the design and PBIR-authoring rules (visual plane); the artifact's new `layout` section; the attestation flow through `publish_report`; failure and revision semantics; external-surface guardrails; conformance tests.

**Out of scope (owned elsewhere, consumed here):** SQL validation and execution (MCP spec §5/§6, gateway), artifact base format (formats spec — amended additively here), publish-job transport (job protocol, publish engine §8.2 gates), profile compilation (platform-architecture §5), the Looker template-link adapter (remains a registered secondary target under its own documented limits).

## 2. Design rulings

| # | Ruling | Rationale |
|---|---|---|
| RA-1 | **All authoring intelligence runs in the customer's Claude Code session via the report skill.** The core ships no model, makes no design decisions, and renders no visuals; its publisher leg is a deterministic function of the artifact | Product decision #3 unchanged; the session is where customer-licensed intelligence already lives |
| RA-2 | **The data plane is core-owned and deterministic.** The semantic model's data is delivered by the core publisher leg from the artifact's validated, reporting-view-backed SQL results. The agent never holds database credentials and never feeds a model directly; SK-6 survives as the rule on what may feed a model | The governance story is the product; an agent-fed model would re-open every credential and validation boundary the gateway closed |
| RA-3 | **The visual plane is the agent's.** Pages, chart choices, and layout are decided per request, with the five-kind registry (FM-2) as design guidance, not enforcement, for this target. The chosen design is written into the artifact's `layout` section BEFORE attestation | AI-designed output must remain reproducible and auditable: creativity in the design, determinism in the record |
| RA-4 | **Trust disclosures render as a visible element of the report itself** — a dedicated section on the primary page (or a clearly-linked "About this report" page), populated verbatim from the artifact's trust_notes, with the artifact id and generated date | Template-link proved disclosures die in chat scrollback; the report is the only surface every viewer sees |
| RA-5 | **PBIR authoring is our thin tooling inside the skill** (deterministic JSON generation + Fabric API deployment). Microsoft's official MCP servers (remote + local modeling) are the only external agentic surfaces; no community MCP dependency ships in the product. Every Microsoft API surface we emit against carries a pinned reference (URL + retrieval date) and a CI conformance check per the D-89 pattern | Preview surfaces drift; drift must die in our CI, not in a customer's session. Third-party agent tooling is outside our release path and cannot be conformance-tested by us |
| RA-6 | **Model delivery v1 = core push-model leg.** The core creates/updates a push semantic model per artifact: one table per result set, typed per the QE-5 encoding, relationships from the artifact's blend keys, measures only as delivered from artifact metadata. Fabric lakehouse/DirectLake is the recorded escalation when an estate outgrows push limits, not a v1 path | Push keeps the data plane a pure core function with no new storage tier, no gateway, and no credentials outside the core. Its size/rate limits are irrelevant at pilot scale and the escalation is additive |
| RA-7 | **Author → deploy → verify, deterministically, before attesting.** The skill reads back the deployed report definition and asserts (a) it equals the authored PBIR (hash), and (b) every field reference resolves against the delivered model schema. Visual verification (screenshots via Desktop) is optional operator tooling, never a gate step | The agent must never attest work it hasn't confirmed landed; read-back + field lint is checkable everywhere the product runs, screenshots are not |
| RA-8 | **One artifact id = one report identity, revised in place.** A revision re-delivers the model (same dataset id, rows replaced) and/or updates the same workspace report definition; attestation records both ids + definition hash per revision. Data-only changes touch the model only; layout changes touch the definition only; both are recorded | This is the promise Looker could not make: a saved report that updates instead of orphaning copies |
| RA-9 | **Refusal semantics are publisher-agnostic and unchanged.** Undocumented blend keys are refused naming the documented set with a flag_gap ledger entry; CP-R4 confirmation still precedes any publish; CP-R5 still blocks unconfirmed results | The target changed; the honesty rules did not |
| RA-10 | **The session's Power BI access is scoped by the service principal, not by trust.** The SP is a member of the designated workspace(s) only; PBI-side RLS is not enforced under SP auth (Microsoft preview behavior) and is not relied upon — delivered data is already exec-role reporting-view aggregates. Recorded in the threat model | Least privilege at the workspace boundary; no security property depends on a preview behavior |

## 3. Session topology

A reporting session (compiled from the reporter profile) connects:

1. **Context Layer MCP** (ours) — grounding, trust blocks, validate_sql, execute_sql, publish_report, flag_gap. Unchanged surface; publish_report gains the §7 contract.
2. **Power BI remote MCP** (Microsoft, hosted) — optional in v1: querying existing semantic models for verification reads. Tenant setting must be enabled; tools consuming Copilot capacity may be disabled in client config.
3. **Power BI local Modeling MCP** (Microsoft) — optional in v1 under RA-6 (the core delivers the model; the skill uses Modeling MCP only if measure/format refinement is required and only against the delivered model, never to create data connections).
4. **Skill-local PBIR tooling** (ours, per RA-5) — deterministic PBIR generation + Fabric REST deployment using the SP token from the session environment; no DB credentials present.

The profile's `tools.allow` continues to gate our surface per M-3; the Microsoft surfaces are gated by SP scope (RA-10) and by the skill's own procedure. The compiled CLAUDE.md fragment states the boundary in plain language: *data comes only from Context Layer tools; Power BI tools shape and place, never fetch source data.*

## 4. The authoring pipeline (normative stage order, extends CP-R)

1. **Resolve & confirm** — CP-R1..R4 unchanged: ground, disclose trust, resolve ambiguities, obtain the human confirmation. CP-R5 gate holds.
2. **Shape** — final validated, view-backed SQL per result set; blend keys only with `entity_ref` (RA-9).
3. **Mint/reuse artifact id** — F-5 unchanged; revisions per RA-8.
4. **Design** — the agent decides pages, visual kinds (registry-guided), encodings, and titles; writes the `layout` section (§6.2) into the artifact.
5. **Request model delivery** — `publish_report` call #1, mode `deliver_model`: core validates the artifact (formats + layout schema, MT-10, certification honesty, blend checks — all existing gates), runs the publish job, executes the artifact SQL through the gateway path, creates/updates the push model, returns `{workspace_id, dataset_id, table schemas as delivered}`.
6. **Author** — skill generates PBIR against the returned schema (field refs must match delivered names/types), including the RA-4 trust element.
7. **Deploy** — skill-local tooling deploys the definition to the workspace via Fabric API (create on revision 1, update in place thereafter).
8. **Verify** — RA-7 read-back: deployed hash == authored hash; every field ref resolves. Failure → fix and redeploy or fail loudly; never attest unverified.
9. **Attest** — `publish_report` call #2, mode `attest`: core records `{artifact_id, revision, workspace_id, dataset_id, report_id, definition_hash, verified_at}` in the audit/attestation store and returns the report URL. The artifact (with layout) is the durable record of what shipped.
10. **Hand off** — the reporter receives the workspace report URL. `pending_human_steps` is empty or `["open the report"]` — the D-91.1 gate condition.

## 5. Data plane — model delivery contract

- One push semantic model per artifact id, named `cl-<artifact-id-short>`, in the configured workspace. Tables named per result-set alias; column names/types from the result schema under QE-5 encoding (temporal → date/dateTime, numeric-as-string → decimal with documented precision note, else native).
- Relationships created only from artifact `blend.keys[]` (each carrying `entity_ref`); cardinality declared in the artifact, defaulting to many-to-one toward the dimension side named by the entity doc's role.
- Revision delivery replaces rows atomically per table (clear + push, or staged swap where the API allows); model/table identity is stable across revisions.
- Delivery failures use the existing publish-job failure taxonomy; partial delivery (some tables succeeded) fails the job — the model is complete-or-previous, never half-new (the SY-1 atomicity instinct applied to models).
- Push-model limits (table/row/rate caps) are checked at delivery; exceeding them is an actionable `capability` failure naming the limit and the RA-6 escalation path — never a silent truncation.
- GA4/GSC-backed result sets are delivered by the same leg from gateway-executed API results; their refresh cadence is a register item riding sync-policy (D-91.5).

## 6. Visual plane — design rules and the layout section

### 6.1 Design rules (skill-normative)
Registry kinds (table, line, bar, scorecard, pivot) are the default palette; other PBIR visual types are permitted where the data shape genuinely warrants, recorded in `layout` with a one-line justification. Documented data caveats bind design: a series without a calendar spine must not render as an interpolating line (the Act-1 lesson, now a rule); clipped window edges are annotated; small-cell sensitivity noted in the trust element. Titles and labels come from human-doc semantics, not column names, where docs exist.

### 6.2 Artifact `layout` section (formats-spec amendment, additive)
```json
"layout": {
  "designed_by": "report-skill@<version>",
  "pages": [ { "name": "Overview",
    "visuals": [ { "kind": "bar", "registry_kind": "bar",
      "table": "weekly_signups", "x": "week_start", "y": "new_users",
      "title": "Weekly new signups (trailing 90 days)",
      "notes": "bars not line: no calendar spine in backing view" } ] } ],
  "trust_element": { "page": "Overview", "placement": "footer",
                     "content_from": "trust_notes" },
  "pbir_hash": "sha256:…"   // set at stage 6, verified at stage 8
}
```
Schema is versioned with the formats spec; unknown keys rejected; `trust_element` is required (RA-4) and its `content_from` must be `trust_notes`.

## 7. Attestation — publish_report contract (MCP-spec amendment, additive)

`publish_report` gains a `mode` argument for `powerbi`-class targets: `deliver_model` | `attest` (template-link targets keep the existing single-shot contract). Both modes run the full existing validation gates; `attest` additionally requires a prior successful `deliver_model` for the same `{artifact_id, revision}` and verifies the submitted `definition_hash` is well-formed. All calls audited as today; attestation rows are the F-4-style permanent record. A revision that never reaches `attest` is visible as delivered-but-unattested in ops — a loud dangling state, not a silent one.

## 8. Failure & revision semantics

| Stage | Failure | Outcome |
|---|---|---|
| deliver_model validation | any existing gate fails | refused with the existing actionable errors; nothing created |
| model delivery | push/API error, limit exceeded | job fails per taxonomy; model remains at previous revision |
| author | schema mismatch vs delivered tables | skill regenerates against returned schema; persistent mismatch → flag, never guess field names |
| deploy | Fabric API error | bounded retries; then fail loudly; no attest |
| verify | hash or field-ref mismatch | redeploy once; then fail loudly; no attest |
| attest | no matching delivery | refused (`revalidate_required`-class); prevents attesting stale work |

Revisions per RA-8. Deleting a report is a human/workspace act, not a product operation in v1 (register: lifecycle/teardown).

## 9. External-surface guardrails (D-89 pattern, mandatory)

A pinned-reference table ships in the adapter/tooling module: Power BI push-dataset REST surface, Fabric report-definition (PBIR) surface, and each Microsoft MCP tool schema the skill relies on — each with reference URL + retrieval date. CI conformance asserts every emitted endpoint/field/tool-call shape appears in the pinned set; unknown → our `ConfigError` before any Microsoft call. Preview drift therefore fails our CI, not a customer session.

## 10. Security & identity

SP credential lives in the customer secret store under the existing reference discipline; sessions receive a scoped token via the compiled setup, never the raw secret where the platform can avoid it. SP is workspace-member only (RA-10). No DB credentials exist session-side (RA-2). Tenant MCP setting enablement is an onboarding-playbook checklist addition. Threat-model addendum: PBI-side RLS non-enforcement under SP auth recorded as accepted (data pre-aggregated by exec-role views); the trust element mitigates misreading, not access.

## 11. Conformance tests

| # | Test | Implements |
|---|---|---|
| AT-1 | deliver_model on a valid artifact creates the model with QE-5-faithful types; re-delivery replaces rows, same ids | RA-6, §5 |
| AT-2 | Blend keys without entity_ref → schema-invalid; undocumented blend → refused naming documented set + flag_gap | RA-9 |
| AT-3 | Layout section without trust_element → artifact invalid | RA-4, §6.2 |
| AT-4 | Authored PBIR referencing a field absent from delivered schema → verify fails, no attest | RA-7 |
| AT-5 | attest without prior deliver_model for the revision → refused | §7, §8 |
| AT-6 | Revision: data-only change re-pushes rows, report definition untouched; layout change updates same report_id; attestation rows record both paths | RA-8 |
| AT-7 | Emitting an endpoint/field outside the pinned reference set → ConfigError in our validation, CI test proves it | RA-5, §9 |
| AT-8 | Partial model delivery (one table fails) → job fails, model remains at previous revision entirely | §5 |
| AT-9 | Fixture end-to-end: request → deliver → author → deploy → verify → attest against a fixture workspace/stubbed Fabric API; audit shows both publish_report calls | §4 |
| AT-10 | Session-side credential canary: no DB credential material reachable in the compiled session environment | RA-2 |

## 12. Register actions and authorized amendments (additive, diffs leading)

1. **Capability spec**: `Publisher` flag registry gains `create_report: api` class and the `deliver_model`/`attest` result shapes; Power BI reference declaration added beside Looker's.
2. **Formats spec**: artifact `layout` section (§6.2) added; five-kind registry annotated advisory-for-api-targets (FM-2 disposition).
3. **MCP spec**: `publish_report` mode contract (§7).
4. **Skill spec**: report skill authoring flow (stages 4–10) as S8; conformance additions AS-x as needed.
5. **Register**: CI-F closed by supersession (D-91.6); new items — GA4/GSC refresh cadence under this target (home: sync policy); report lifecycle/teardown (home: this spec); Fabric/DirectLake escalation trigger (home: this spec, RA-6).
6. **Playbook**: tenant setting + SP provisioning join the onboarding checklist.

## 13. Open decisions (spec-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| RA-A | Measures: delivered from artifact metadata vs agent-added via Modeling MCP | Delivered only; Modeling MCP off in v1 | First report needing a measure the artifact can't express |
| RA-B | Remote MCP verification reads in the loop | Off by default (RA-7 read-back suffices) | First field-mapping bug read-back misses |
| RA-C | Report theming/branding | Product-default theme JSON in PBIR tooling | First customer branding ask |
| RA-D | Multi-artifact workspaces & naming collisions | `cl-<artifact-id-short>` prefix, one workspace per deployment | First shared-workspace customer |
| RA-E | Scheduled re-delivery (standing reports) | Manual/skill-triggered revisions only in v1 | SP-4 recurring-demand evidence at revival of BASELINE-1 |
