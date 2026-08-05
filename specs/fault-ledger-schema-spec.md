# Contract Specification — Fault Ledger Schema (v1)

Status: v1 draft for implementation. The final spec of the roadmap (`high-level-requirements-and-user-journeys.md` §11): makes HLR §6 — three detector classes, never rely on agent self-awareness, dead-ends as the KB's growth signal — concrete as Postgres tables, detector rule definitions, ingestion contracts, the KB Health triage-queue contract, and the loop-closure mechanics back into journey J2. Consumes: MCP spec (audit stream, `flag_gap`), skill specs (enrich scoping, `result_disputed`), KB spec (PR flow), job protocol (health events). Partially resolves HLR Open Decision **OD-2** (the class-1 rule set becomes configuration data with shipped defaults) and resolves one entry through the **OD-5** process (§12).

The ledger lives in **ops Postgres** — it records what the system did and failed to do, never what the estate means (the git/Postgres rule).

---

## 1. Scope

**In scope:** the event/issue data model and DDL; the kind registry and its class-provenance rules; the four class-1 detector rules as configuration; class-2/3 ingestion; issue lifecycle, routing, and deduplication; the triage-queue contract (KB Health module + the `list_gaps` tool); loop closure via PR trailers; privacy and retention; conformance tests.

**Out of scope:** dashboard rendering, the audit record shape itself (MCP §8 — the ledger *reads* it), and enrichment content (the ledger routes work; the enrich skill does it).

## 2. Design rulings

| # | Ruling | Rationale |
|---|---|---|
| L-1 | Two levels: append-only **events** (high-volume, retention-limited) and fingerprint-deduplicated **issues** (lifecycle-bearing triage items) | Detectors fire constantly; a triage queue of raw events is unusable. Sentry-style grouping is the proven shape |
| L-2 | Detector **class is provenance on the event**; `kind` is the problem type; multiple classes can feed one issue | The same doc/schema mismatch may be caught by a detector or flagged by an agent — it is one problem |
| L-3 | Class-1 detector rules are **configuration data** (ops table, dashboard-editable, shipped defaults), not code | OD-2's "tune from pilot data" becomes a config change; rules are auditable and per-customer adjustable |
| L-4 | Recurrence after resolution **auto-reopens** the issue with a reopen counter | A repaired doc that keeps failing is a regression signal, not a new ticket |
| L-5 | Loop closure = PR trailer `CL-Resolves: <issue-id>`; the core resolves issues on merge of the carrying PR | Resolution is attributable to a diff, consistent with "everything through a PR" |
| L-6 | `flag_gap` returns the **issue** id (post-dedup) and its occurrence count | The agent can honestly say "already known, reported N times, routed to your data team" |
| L-7 | One new read-only, Steward-gated MCP tool: **`list_gaps`** — proposed and resolved through the OD-5 register (§12) | The enrich skill's scope priority 1 (ledger items) requires a read path from Claude Code; smallest possible surface addition, made through the front door |
| L-8 | Events never store secrets or full statements — object FQNs, digests, and short user-authored descriptions only; full SQL stays in the audit log it links to | The ledger is widely readable (triage); the audit log is the restricted deep store |

## 3. Data model

### 3.1 `ledger_events` (append-only)

```sql
CREATE TABLE ledger_events (
  event_id      uuid PRIMARY KEY,
  ts            timestamptz NOT NULL,
  detector_class smallint NOT NULL CHECK (detector_class IN (1,2,3)),
  kind          text NOT NULL,               -- §4 registry
  fingerprint   text NOT NULL,               -- §3.3
  system        text,                        -- when attributable
  object_fqn    text,                        -- when attributable
  subject       text,                        -- acting identity (null for system detectors)
  session_id    text,
  profile       text,
  audit_ref     uuid,                        -- MCP audit record that evidenced it
  kb_ref        text,                        -- KB commit at event time
  snapshot_ref  jsonb,
  description   text,                        -- short; user text for class 2/3 (L-8)
  detail        jsonb NOT NULL DEFAULT '{}'::jsonb,
  issue_id      uuid NOT NULL REFERENCES ledger_issues(issue_id)
);
CREATE INDEX ON ledger_events (issue_id, ts);
CREATE INDEX ON ledger_events (ts);
```

### 3.2 `ledger_issues` (the triage queue)

```sql
CREATE TABLE ledger_issues (
  issue_id      uuid PRIMARY KEY,
  fingerprint   text UNIQUE NOT NULL,
  kind          text NOT NULL,
  system        text,
  object_fqn    text,
  title         text NOT NULL,               -- generated: "<kind>: <object|query-terms>"
  status        text NOT NULL DEFAULT 'open' -- open | triaged | resolved | dismissed
                CHECK (status IN ('open','triaged','resolved','dismissed')),
  routed_to     text NOT NULL,               -- role, per §7 routing table
  first_seen    timestamptz NOT NULL,
  last_seen     timestamptz NOT NULL,
  occurrences   integer NOT NULL DEFAULT 1,
  distinct_subjects integer NOT NULL DEFAULT 0,  -- how many different users hit it
  reopen_count  integer NOT NULL DEFAULT 0,      -- L-4
  resolved_at   timestamptz,
  resolved_by   text,                         -- identity or 'pr'
  resolution    jsonb,                        -- {kind: enrichment_pr|doc_fix|config_fix|wont_fix|duplicate, pr_url?, note?}
  links         jsonb NOT NULL DEFAULT '{}'::jsonb  -- {docs: [], prs: [], entities: []}
);
CREATE INDEX ON ledger_issues (status, occurrences DESC, last_seen DESC);
CREATE INDEX ON ledger_issues (object_fqn) WHERE object_fqn IS NOT NULL;
```

### 3.3 Fingerprints (the dedup rule)

`fingerprint = sha256(kind ‖ scope)` where `scope` is, in priority order: the attributed `object_fqn`; else the entity/metric path; else, for coverage gaps, the **normalized query terms** (lowercased, stopwords stripped, sorted — so "regional net sales" and "net sales by region" group); else the session-independent detail the rule defines. Fingerprints are stable across users and sessions by construction — the count of `distinct_subjects` is what tells triage "eleven different people hit this wall," which is the strongest prioritization signal we have.

**Amendment (D-66.5 / security review #1 LED-R2, 2026-07-17) — query-term and description hygiene.** Query-term-derived scopes, the `title` generated from them, and class-2/3 `description` text **never carry data values**: the server scrubs them before storage — quoted literals, numbers and identifier-like digit runs, email addresses and similar value-shaped tokens are dropped (in addition to the skill-side K-GROUND discipline, which remains advisory only). Titles and descriptions are **length-bounded** (server-enforced caps) and are **visibility-filtered** at every read surface exactly like `object_fqn`-attributed issues (M-4): a triager sees only what their role could see at the source. The scrub is a storage rule, not merely a render rule — a value that never lands in the ledger cannot leak from it.

## 4. Kind registry (v1) and class provenance

| Kind | Classes that can emit | Typical scope |
|---|---|---|
| `coverage_gap` | 1 | normalized query terms |
| `doc_schema_mismatch` | 1, 2 (`schema_mismatch` flag) | object FQN |
| `guardrail_hit` | 1 | object/system + guardrail code |
| `abandoned_journey` | 1 | session pattern (fingerprinted on resolved-entity set) |
| `missing_doc` | 2 | object FQN |
| `missing_join_path` | 2 | entity path or FQN pair |
| `uncertified_metric` | 2 | metric path |
| `missing_entity` | 2 | normalized query terms |
| `capability_gap` | 2 | target + flag (includes SK-6 reporting-view handoffs — the DDL rides in `detail`) |
| `result_disputed` | 3 | artifact id + object set |
| `human_filed` | 3 | free (dashboard form) |
| `benchmark_regression` | 3 | kb_ref + suite request id |
| `enrichment_request` | 3 | target object FQN when given, else normalized request terms |
| `other` | 2 | free |

Registry growth is additive (mirrors S-5). `flag_gap`'s enum (MCP §6.10) maps 1:1 onto the class-2 rows; `schema_mismatch` flags land on the `doc_schema_mismatch` fingerprint so both classes corroborate one issue (L-2).

**Amendment (D-101.2, 2026-08-05) — `enrichment_request`: the knowledge-request queue.** The kind above is a human submission, not a detector finding: someone tells the estate what it is missing, optionally with the content they think should fill it. Anyone may file one. Two inlets, both recorded as class 3 by kind exactly as `result_disputed` is (§6): the dashboard's request form (Gap Triage & Knowledge Requests, dashboard spec §3) and `flag_gap` from a session (MCP §6.10) — one queue whether or not the requester has a browser open.

**Payload.** Optional target `object_fqn` and optional `proposal` (the requester's suggested content, stored in `detail.proposal`). Both optional by design: a request may be a hole ("nothing says how refunds are counted") or a proposal ("here is how we count them"). Every existing rule applies to it unchanged and without exception — **LED-R2** server-side scrub and length bounds on `proposal` exactly as on `description` (§3.3: a value that never lands in the ledger cannot leak from it); **LED-R3** identity, session, profile and refs are server-set and a client-supplied subject is ignored; **LED-R5** markdown/HTML-inert rendering at every surface that displays the text — the queue, `list_gaps`, and any PR body citing it; **LED-R7** counts-only for `distinct_subjects`.

**Fingerprint and dedup: unchanged** (§3.3). Scope is the target FQN when given, else the normalized request terms. Two people asking for the same thing produce **one issue with two events** (`occurrences=2`, `distinct_subjects=2`); the steward's verdict applies to the issue, and every event's proposal is drafting input for the batch. The prioritization signal is the one the queue already has — eleven people asking for the same doc is the strongest argument for writing it.

**Verdict states** (additive to §3.2's `status` domain, valid only for `kind = 'enrichment_request'`; every other kind's §7 lifecycle is untouched):

```
open ──approve──► approved ──deliver batch──► batched(batch_id) ──PR merge──► resolved
  │                             ▲                     │                        (L-5)
  │                             └── undraftable ──────┘  (returns with the skill's note)
  └──reject(reason)──► rejected
```

Additive DDL: the `ledger_issues.status` CHECK gains `approved | rejected | batched`; the table gains `verdict_by text`, `verdict_at timestamptz`, `verdict_reason text` (the rejection reason — human-authored text that will be shown to the filer, so LED-R2's bounds and scrub apply to it too) and `batch_id text`. All four are NULL for every other kind.

**What a verdict is, and is not** (dashboard spec UI-11). Approve means *worth drafting*. It changes **ledger state only**: it writes no KB content and makes no git call. The certification act remains exactly what it has always been — a human merging a reviewed diff under their own name (KB-7). Rejection sets `rejected` with its reason rather than deleting the row: the record of what was asked and declined is worth as much as the record of what was written, and a rejected request that eleven more people file is a decision worth revisiting.

**Resolution rides the existing L-5 lifecycle — no new mechanism.** The enrich skill's batch PR carries one `CL-Resolves: <issue-id>` trailer per request the batch satisfies; the core resolves those issues on merge (§9) with `resolution: {kind: enrichment_pr, pr_url}`. A batch resolves exactly the requests it satisfies and no others. An approved request the skill could not draft returns to `approved` carrying the skill's note (skill spec §6) — never silently dropped, never guessed at. Recurrence is unchanged (L-4): a resolved request whose fingerprint fires again reopens with `reopen_count += 1`, which for this kind reads *the doc we wrote did not answer the question* — precisely the signal worth having.

**Reply path.** Rejection reasons and batch-merge resolutions surface to the filer through the same channel as every other resolution (the F-10 reply path; mechanism per dashboard spec UI-D, asserted by DT-10).

## 5. Class-1 detector rules (shipped defaults; ops-config data per L-3)

Rules run in the core against the audit stream: cheap single-record rules synchronously on audit write; window rules in a periodic sweep (default every 5 min).

```
rule zero_result_search      (sync):   search_context with 0 results, or all results
                                       below confidence floor → coverage_gap
rule repeated_validate_fail  (window): ≥3 validate failures citing the same object_fqn
                                       within 24h (any users) → doc_schema_mismatch
rule guardrail_pattern       (window): ≥3 guardrail terminations (timeout|row_cap|
                                       quota_exhausted) on the same system within 24h
                                       → guardrail_hit
rule abandoned_journey       (sweep):  session with ≥1 resolution read (get_entity/
                                       get_metric) and ≥1 validate, no execute, and
                                       30 min inactivity → abandoned_journey
```

Each rule row in ops config carries: `enabled`, thresholds, window, and its fingerprint recipe. Two shipped-but-disabled rules are included for pilot evaluation: `execute_without_resolution` (the SP-1 heuristic — log-only) and `schema_mismatch_at_execute` (capability code from QE, single-shot; enabled by default actually — it is deterministic and severe). Threshold tuning is the OD-2 revisit, now a dashboard action.

## 6. Class-2/3 ingestion

**Class 2 — `flag_gap` (MCP §6.10):** the server validates kind, attaches identity/session/profile/refs, computes the fingerprint, upserts the issue (increment or create, update `last_seen`, `distinct_subjects`), inserts the event, and returns `{issue_id, occurrences, routed_to}` (L-6). Rate limit per MCP §7 guards flag spam; dedup makes residual spam harmless (one issue, high count).

**Class 3 — three inlets:** (a) `result_disputed` arrives as a `flag_gap` call made by the report skill on the user's negative confirmation (skill CP-R4/SK-5) — same pipeline as class 2, class recorded as 3 by kind; (b) **dashboard filing**: KB Health offers a form → `human_filed` events under the filer's identity; (c) **benchmark harness**: on a CI run whose score drops beyond the configured tolerance vs the previous kb_ref, the harness writes `benchmark_regression` events, one per degraded suite request — merged-but-degrading changes become triage items even when CI is configured report-only (KB-9 per-customer policy).

## 7. Issue lifecycle and routing

```
        (first event)                    (human in KB Health / list_gaps ack)
  ──────────────► open ──────────────► triaged ──┬──► resolved (manual or L-5 PR merge)
                    ▲                             └──► dismissed (wont_fix/duplicate…)
                    │ (new event post-resolution: L-4)
  resolved ─────────┘  reopen_count += 1, status → open, resolution preserved in history
```

`enrichment_request` runs the verdict lifecycle added by the D-101.2 amendment (§4) instead of the `open → triaged` path above; its terminal `resolved` state and its L-4 recurrence behavior are the same ones drawn here.

Routing (`routed_to`) is a kind→role table in ops config; shipped default routes **everything to the data-team role** (R2 owns triage per HLR §4) except `benchmark_regression`, which also notifies the merging author. Dismissed issues keep their fingerprint: recurrence reopens them too — a `wont_fix` that eleven more people hit deserves a second look, and the reopen counter says exactly that.

## 8. Triage-queue contract

**KB Health module (primary surface):** reads `ledger_issues` ordered by `(status='open' first, occurrences DESC, last_seen DESC)`, filterable by kind/system/routed_to; issue view shows the event stream, linked docs/PRs, and one-click actions: acknowledge (→ `triaged`), assign, dismiss-with-reason, or **"export enrichment batch"** — emitting the scoped work list the enrich skill consumes.

Per the D-101.2 amendment, the same module carries the **knowledge-request queue**: `enrichment_request` issues ordered by the same `(occurrences, distinct_subjects)` signal, the steward's approve / reject-with-reason verdicts (ledger-state writes, role-gated server-side), the approved worklist, and the "deliver batch" trigger that stamps `batch_id` on up to ten approved requests and hands them to the enrich skill. Batches are cut on demand or at ~10 approved — appending is permitted only to a still-open, still-small batch, so no batch becomes an immortal rolling PR.

**`list_gaps` tool (MCP; L-7):** `list_gaps(status=open|triaged, kind?, system?, limit=20)` → issues as `{issue_id, kind, title, object_fqn?, occurrences, distinct_subjects, first_seen, last_seen, links}`. Read-only; allowlisted in the Steward (and `benchmark`) profile templates only; visibility-filtered — an issue attributed to an object the caller's role cannot see is omitted (M-4 consistently applied). This is the enrich skill's S1 priority-1 input, straight from the session.

## 9. Loop closure (L-5)

A KB PR whose body carries one or more `CL-Resolves: <issue-id>` trailers resolves those issues on merge: the core (git-provider webhook it already has for CI triggers) sets `resolved`, `resolved_by: pr`, `resolution: {kind, pr_url}`. The enrich skill writes the trailer automatically for every batch item that originated from the ledger (amendment, §12). Post-merge events on the same fingerprint reopen per L-4 — which is precisely the test of whether the repair actually worked, measured by the same instrument that found the problem.

## 10. Privacy and retention

Events: retained 90 days (config), then deleted; issues: indefinite (they are the estate's institutional memory of its own gaps). L-8 storage rule: no secrets, no full statements — `audit_ref` points into the restricted audit log for deep forensics under the Audit module's own access roles. Class-2/3 `description` is user-authored text shown to triagers; the flag_gap path warns skills (kernel K-GROUND discipline) to describe the *gap*, not paste data.

**Amendment (D-66.5, 2026-07-17):** the K-GROUND discipline is not relied on — the §3.3 LED-R2 server-side scrub and length bounds apply to every stored `description` and query-term-derived `title`, and both are neutralized (markdown/HTML-inert) at every render point — `list_gaps` responses, the KB Health dashboard, and any PR body that cites ledger text (LED-R5, same class as review finding F4).

## 11. Conformance tests

| # | Test | Implements |
|---|---|---|
| FL-1 | Fixture audit stream through the four shipped rules → exactly the expected events and issue set | §5, L-3 |
| FL-2 | Same gap hit by 3 users across classes 1 and 2 → one issue, `occurrences=3`, `distinct_subjects=3`, both classes present in events | L-1, L-2, §3.3 |
| FL-3 | `flag_gap` on a known issue returns its id and count; on a novel gap creates issue and routes per table | L-6, §6, §7 |
| FL-4 | Merge of a PR with `CL-Resolves` → issue resolved with pr_url; subsequent matching event reopens with `reopen_count=1` | L-5, L-4 |
| FL-5 | `list_gaps` absent from Reporter `tools/list`; present for Steward; visibility-filtered issues omitted | L-7, M-3/M-4 |
| FL-6 | Canary secret / full SQL in a flag description path → not persisted beyond the audit log; ledger row carries digest/refs only | L-8 |
| FL-7 | Event retention sweep deletes >90d events, never issues; issue history intact | §10 |
| FL-8 | Benchmark CI drop beyond tolerance → `benchmark_regression` issues keyed to kb_ref, author notified | §6c |
| FL-9 | Rule threshold edited in ops config takes effect next sweep without deploy | L-3 |
| FL-10 | Dismissed issue reoccurring → reopened, `reopen_count` incremented | §7 |
| FL-11 | `enrichment_request` lifecycle: two requests on one target dedup to one issue (`occurrences=2`); a proposal carrying a canary value and a markdown payload is stored scrubbed and served inert; approve → `approved` with `verdict_by`/`verdict_at`, **no KB write and no git call**; deliver batch → `batched(batch_id)`; merge of the batch PR resolves exactly the trailered requests, an undraftable one returning to `approved` with its note; reject records the reason and the filer's reply path carries it | §4 amendment (D-101.2), LED-R2/R3/R5, L-5, UI-11 |

## 12. Amendments to other specs (additive) and register actions

> **Status: applied.** Folded into home specs in the consolidation pass; retained as the change record.

1. **MCP tool reference:** new tool **`list_gaps`** (§8 here) — entered into and resolved through OD-5 as that register requires; MCP §6 gains the tool entry, gating class **S** (Steward). `flag_gap`'s response is amended from `{ledger_id, routed_to}` to `{issue_id, occurrences, routed_to}` (L-6).
2. **Skill specifications §6:** enrich S5 writes `CL-Resolves:` trailers for ledger-originated batch items (§9).
3. **KB repository spec §9:** PR conventions gain the `CL-Resolves` trailer.
4. **HLR §10:** OD-2 partially resolved — the rule set and thresholds are now ops configuration with shipped defaults (this spec §5); remaining open scope is threshold *values* tuning from pilot data.
5. **HLR §7.1 profile table:** Steward tools gain `list_gaps`.

## 13. Open decisions (spec-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| FL-A | Priority scoring beyond the sort order (kind weights × object hotness × recency decay) | Simple sort (status, occurrences, last_seen) in v1 | If R2 triage feedback says ordering misleads |
| FL-B | Notification channels (email/Slack) on routing | Dashboard-only in v1; the queue is R2's home screen | First customer ask; would be a connector-class addition |
| FL-C | Auto-dismiss for `abandoned_journey` singletons (noisy kind by nature) | Keep, but this kind requires ≥2 occurrences before an issue opens | Pilot noise measurement |
| FL-D | Cross-issue linking (this `missing_join_path` blocks those 3 `coverage_gap`s) | Manual `links` field only in v1 | If triage shows frequent causal clusters |
| FL-E | `distinct_subjects` privacy stance (counts only vs listing who) | **Closed** (D-66.5) — counts-only affirmed by security review #1 (LED-R7); LED-R2 scrub + LED-R5 render neutralization added (§3.3/§10 amendments) as conditions of closure | — |
