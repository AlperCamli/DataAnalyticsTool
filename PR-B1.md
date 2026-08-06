# B-1 — KB Health, Gap Triage & Knowledge Requests

Checkpoint B-1 of the Phase-2 plan. Four dashboard modules, the reply
path that closes the F-10 loop, the enrich skill's queue-driven entry,
and the operator's gate runbook. Task 0 rode along: D-113 recorded,
D-108's two bracketed clauses resolved on the operator's attestation, and
playbook §4's exit condition made true for the install shape A4-F5 found.

**Suites:** core **345 passed / 4 skipped / 30 files** (was 306/4/28 at
A-4). Python **792 passed / 14 skipped / 1 failed** — the contamination
triage, 34 docs, estate state, untouched by this work.

---

## What ships

### KB Health (`src/kbhealth.ts`, `web/src/KbHealth.tsx`)

One governed read, `GET /v1/dashboard/kb-health`, assembling the whole
module: per-source freshness against `sync-policy.yaml`, the sync
configuration state, doc-status counts at KB HEAD, the contaminated set
with the lineage paths that carried the contamination, and the drift-PR
queue. Plus `GET /v1/dashboard/lineage` for U-15's read view.

Three properties are rules rather than conveniences:

- **One computation, two surfaces.** The freshness rows and doc-status
  counts are computed here and **imported by the MCP `report_freshness`
  tool**, which previously derived its own. A dashboard that could
  disagree with `report_freshness` about whether a source is stale is a
  dashboard nobody can cite as evidence. Asserted by a test that calls
  both and compares.
- **DT-9 reads the core's own resolved config**, not a second fetch of
  `/healthz`. Same `cfg.sync.enabled`, two renderings — and the test
  asserts the two surfaces agree in both states. The banner names the
  count of systems the policy configures, because "sync is disabled"
  alone reads like a setting rather than a fault.
- **Nothing here can merge.** The drift queue is links out. The absence
  is asserted over the server sources *and* the shipped bundle: a merge
  button is not the risk, a code path is.

Contamination paths are graded and the grade is reported —
`recorded` / `declared` / `derived` / `self` / `unknown`. An unknown path
is `null`, never `[]`: an empty list reads as "no hops", and the
difference is a triage fact (the doc relies on something it never
declared).

### Gap Triage & Knowledge Requests (`web/src/GapTriage.tsx`)

Pixels over B-0's API and **no new authority**. Verdict controls, the
deliver-batch trigger and the filing form are rendered for everybody; a
caller without the steward profile reads the server's own 403. DT-11 was
proven server-side at B-0 and is re-run here through the UI's call shape.

The proposal renders inert and is *labelled* as the requester's words,
quoted — chrome reads as endorsement unless something says otherwise.
Reopen state carries D-106.5's sentence ("rejected before, refiled by N
more") with the prior verdict preserved.

### The reply path (`web/src/Inbox.tsx`, migration 0012)

UI-D's badge, served by `GET /v1/dashboard/inbox`: what this caller filed
that reached a terminal verdict, with the rejection reason or the merged
PR's link. Acknowledgement is a **server** write, so the badge does not
return on reload, in a second tab, or on another machine — the client
persists nothing and could not. A re-verdict after a refiling fires it
again, by comparing the acknowledged verdict time against the current one.

**In-session surfacing remains unbuilt** and is named as unbuilt in the
code, the runbook and DECISIONS.

### Publish + Ops (`web/src/Publish.tsx`, `src/ops.ts`, `web/src/Ops.tsx`)

Deliveries with attestation history and the **dangling** state F-15
named, loudest on the screen rather than a column to notice. Runs, jobs,
the dead-letter queue with re-enqueue **as the user** — a new job with
the dead one's payload; the dead row keeps its error and its terminal
state, because it is the evidence that something failed. Webhook secrets
shown once from the creation response (DT-5), with no endpoint that could
return one: the store holds a sha256.

### A4-F1 — Connections gains its edit affordance

The card renders the stored config and the credential references, and
**Edit** opens them prefilled through the same governed PUT. What is
edited is a *reference*, never a value; there is no password field on the
screen; and the payload validator still refuses material. What comes back
after a save is the store's read-back.

### D-110.3a closed — governance writes enter the audit record

Dashboard spec §5.1's filed gap, authorized by the operator under D-113's
fence and closed here rather than at B-4. The contract widens from "one
row per MCP call" to "one row per governed act"; no schema change was
needed. Connection upsert/delete/test, ledger verdicts, batches and
returns each write a row carrying the acting identity — **including
denied**, because a reporter's refused verdict is exactly the row an
auditor came for. Every existing consumer filters by `tool`, so none
re-reads differently; asserted.

One visible consequence, stated rather than discovered later: audit-window
row counts now include governance rows.

### enrich S1b (`core/skills/enrich/SKILL.md`)

D-101.4's queue-driven mode as a section of the same skill, not a fork.
Input is the delivered batch read through the governed ledger API as the
session user. Two rules, both honesty rules: the approved request is a
citation of the **customer-provided** class, taken from what the ledger
recorded and never re-typed from the request body; and a request the
skill cannot draft **returns to the queue** with a note, drops out of the
trailers, and is named in the PR body.

### The transition that had no mechanism

Fault-ledger §4's diagram draws `batched → approved` ("returns with the
skill's note") and nothing implemented it — so CP-E5's honest exit had
nowhere to go, and a skill facing an undraftable request could only guess
or drop it. Built: `POST /v1/dashboard/ledger/issues/:id/return` with a
**required** note, clearing `batch_id` and keeping the verdict.
Occurrences are deliberately not incremented — a skill saying "I could
not write this" is not another person asking for it.

*Flagged, not done:* §4's "Additive DDL" sentence enumerates the four
verdict columns and does not mention `return_note` / `returned_at`. The
transition is specified in the same section, so this implements the spec;
the enumeration is now incomplete and its one-line correction is outside
this session's fence.

---

## Conformance

| Test | Where |
|---|---|
| DT-3 render neutralization on the KB Health path | `dashboard-kbhealth.test.ts` |
| DT-5 webhook secret shown once, no read path, not in the audit args | `dashboard-b1.test.ts` |
| DT-9 both states + agreement with `/healthz` | `dashboard-kbhealth.test.ts` |
| DT-10 the badge, its ack, and a re-verdict firing it again | `dashboard-b1.test.ts` |
| DT-11 / DT-12 | `dashboard-ledger.test.ts` (B-0, re-run) + the UI's call shape |
| §7.3 no-merge, over server sources **and** the shipped bundle | `dashboard-kbhealth.test.ts` |
| Governance audit rows, allowed and denied | `dashboard-b1.test.ts` |
| D-101.5's loop without an agent: verdict → batch → merged PR → resolution → badge | `dashboard-b1.test.ts` |
| `batched → approved` return, its required note, its refusals | `dashboard-b1.test.ts` |
| S1b citation / trailer / no-verbatim rules (CI regression, **not** AS-18's evidence) | `tests/test_skill_conformance.py` (15 new) |
| AS-18 behavioral scenario (D-78 layer b) | `tools/skill_scenarios.py --only enrich-batch` — **ships, not run** |

**D-78 applied honestly:** AS-18 spans an agent's judgement and the
product's mechanics, and one test cannot cover both. The agent half is
the scenario and needs a model call; the product half is deterministic
and runs on every commit. Neither is reported as covering the other, and
the validators are explicitly not the evidence.

---

## One incidental fix

`parsePolicy` accepted a **list** under `systems:` — `Object.entries` over
an array yields "0", "1", "2" as system names, so a malformed policy
parsed cleanly, matched no real system, and synced nothing without
complaining. Now an error. Found while writing DT-9's negative case; it
is the same silent-failure family this checkpoint exists to surface.

---

## What this build does not claim

- **The gate demo has not been run.** `results/phase2/b1/GATE-RUNBOOK.md`
  is the operator's morning: KB Health showing the true backlog → Ops →
  drift review → contamination triage → the knowledge-request loop end to
  end, stopping at act 10 for the R2 merge. A PR merged by this session
  would not be a human certifying a reviewed diff, which is the whole of
  KB-7.
- **AS-18's behavioral half has not been run.**
- **A4-F5's code-level fix is not done** — only the playbook's honesty
  defect closed.
- **D-107.3 / D-107.4 register rows are still unfiled**, flagged at
  A-3/B-2 and unchanged here.
