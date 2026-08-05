# B-0 — Read APIs before pixels

Phase-2 Track B, checkpoint B-0 (`plans/phase2-development-plan-v1.md`),
implementing `specs/dashboard-spec.md` §5 under rulings D-102 (browser
auth, steward audit scope) and D-101 (the enrichment-request queue).

**Entry verified before building.** `specs/dashboard-spec.md` on `main`
(`41f3d70`, amended `c635e26`); DECISIONS.md carries D-100, D-101, D-102
(and D-103, D-104); the fault-ledger amendment (`1b470fb`) and the MCP
§6.10 amendment (`c7e5bd1`) both landed. No spec was edited by this PR —
the amendment fence held; the two spec observations below are flagged,
not acted on.

## Gate (verbatim from the plan)

> governed read endpoints for audit, publish deliveries, and ledger
> triage — each subject/role-filtered server-side, each with a
> conformance test proving a reporter cannot read another subject's rows;
> extract-audit.sh a client of the audit API.

All four clauses are met, each by a test rather than by review. The
`extract-audit.sh` clause is met to a stronger standard than asked: the
CP-7 gate's committed evidence is reloaded into a scratch estate, the
runbook's own script is run over the same window, and **all five evidence
files reproduce byte for byte** through the API.

## What landed

| Area | File |
|---|---|
| Browser session auth (OIDC authorization-code + PKCE, cookie, CSRF) | `core/src/session.ts` |
| The three read APIs + §5's write inlets | `core/src/dashboard.ts` |
| Authorization-code leg on the existing verifier | `core/src/oidc.ts` |
| Triage reads, verdict lifecycle, batch trigger | `core/src/ledger.ts` |
| `flag_gap(proposal?)` + `enrichment_request` kind | `core/src/mcp.ts` |
| Sessions, auth states, verdict columns | `core/migrations/0009_dashboard.sql` |
| Evidence extractor, now an API client | `results/cp7-gate/extract-audit.sh` |

**One verifier, asserted by construction.** D-102.1's load-bearing clause
is that the dashboard resolves identity through the *same* verifier the
MCP path uses. `session.ts` calls `OidcClient.resolveIdentity` — the same
function, the same per-request IdP introspection — and `dashboard.ts`
never resolves identity at all. A test greps both modules for
`rolesClaim`, `introspection_endpoint`, `realm_access` and
`preferred_username` and fails if any reappears, so a second role
resolver cannot grow here quietly. The inherited consequence is real: an
IdP-side revocation lands on the very next dashboard call, asserted.

**The client cannot be trusted with a subject, because it is never
given one.** `subjectScope()` is the single place scope is decided: a
steward may name a subject or omit one (scope `all`, D-102.2); anyone
else is pinned to their resolved identity and a crafted `subject=` is a
403. CP-8's `fetch-all-filter-client` trap is structurally excluded — the
rows never leave the server.

## Requirement → test map

Every §5 clause and every named DT item, mapped to the test that proves
it. No clause is unmapped.

### §5 preamble — every endpoint

| Clause | Test |
|---|---|
| authenticated by the caller's OIDC session | auth: *walks the OIDC authorization-code flow…*; *no cookie is a 401 on every B-0 endpoint* |
| role-and-subject filtered server-side per §4 | reads: the three DT-1 tests below |
| paginated | reads: *defaults to the server page size and caps an over-large request*; *walks a keyset cursor without repeating or skipping a row* |
| stable JSON shapes versioned with the core | reads: `api_version` asserted on each endpoint |

### §5.1 Audit read

| Clause | Test |
|---|---|
| query by time window | reads: *filters by tool and window* |
| query by subject (self-only unless role permits) | reads: *DT-1: a reporter reads only their own rows*; *a steward may filter to one subject* |
| query by tool | reads: *filters by tool and window* |
| query by decision | reads: *denied and filtered decisions are included, with their reason* |
| records as stored (args digests) | reads: *rows carry the audit record as stored* |
| decisions incl. denied/filtered | reads: *denied and filtered decisions are included…* |
| `extract-audit.sh` becomes a client; direct-DB path retires | extract: *holds no database credential and no direct-DB path* + four byte-for-byte reproduction tests |

### §5.2 Publish deliveries read

| Clause | Test |
|---|---|
| by artifact id | reads: *DT-1: a crafted subject is refused, and another's artifact id returns nothing* |
| by window | reads: *filters by window* |
| model deliveries | reads: *a steward reads every delivery* |
| attestations | reads: *reports the dangling state and per-revision definition hashes* |
| dangling (delivered-unattested) state | reads: *reports the dangling state…* (asserts both polarities) |
| per-revision definition hashes | reads: *reports the dangling state and per-revision definition hashes* |

### §5.3 Ledger triage read + workflow writes

| Clause | Test |
|---|---|
| open issues and enrichment requests | reads: *a steward reads the whole queue* |
| ordered by occurrences/distinct_subjects | reads: *orders the queue by the (occurrences, distinct_subjects) signal* |
| visibility-filtered per M-4 | reads: *an issue the caller did not file is not readable by id* |
| counts-only subjects (LED-R7) | reads: *LED-R7: subjects are counts, never identities* |
| server-scrubbed text (LED-R2/R5) | ledger: *stores a hostile proposal scrubbed, and serves it inert* |
| `human_filed` inlet under server-derived identity | ledger: *files a gap under the filer's server-derived identity (LED-R3)* |
| enrichment-request inlet, proposal scrubbed and length-bounded | ledger: *opens an enrichment request with an optional proposal*; *bounds an oversized proposal at the same limit as a description* |
| steward verdict writes (approve / reject-with-reason) | ledger: the four DT-11 tests |
| ledger state only per UI-11 | ledger: *a steward's approve records identity and timestamp — and makes no git call* |
| recorded with steward identity + timestamp | ledger: same test |
| "deliver batch" trigger marking approved batched | ledger: *is steward-gated, bounded, and stamps approved requests batched* |
| `flag_gap`'s optional proposal (MCP §6.10 amendment) | ledger: *MT-14: flag_gap carries the same proposal treatment from a session* |

### Named conformance items

| # | Test |
|---|---|
| **DT-1** (all three endpoints) | reads: *DT-1: a reporter reads only their own rows* / *…a crafted subject for another identity is refused server-side* (audit); *…a crafted subject is refused, and another's artifact id returns nothing* (deliveries); *…a crafted filed_by for another identity is refused server-side* (ledger) |
| **DT-11** | ledger: *a reporter's verdict call is a 403*; *a steward's approve records identity and timestamp — and makes no git call*; *a reject records the reason, scrubbed*; *verdicts apply to knowledge requests only, and only once* |
| **MT-14** | ledger: *MT-14: flag_gap carries the same proposal treatment from a session* |
| **FL-11** (partial — see below) | ledger: *FL-11: two requests on one target dedup to one issue with occurrences=2*; the proposal, verdict, and batch legs above |
| Session auth (D-102.1) | auth: 12 tests — flow, cookie attributes, state replay, 401s, expiry, revocation, CSRF ×3, logout, open-redirect |

**DT-11's hardest clause is asserted twice.** "Approve makes no git call
and writes no KB content" is checked behaviourally — the KB's full ref
list and the PR store are fingerprinted before and after an approve and
must be unchanged, as must remote `main` — and structurally: neither
`dashboard.ts` nor `session.ts` may import `gitkb.js`. Approve is not
certify; the diff remains the review, the merge remains the act.

## Test results

`core`: **250 passed across 23 files, all green** on the final run
(`npx vitest run`). An earlier run failed one test —
`property.test.ts > dedupe invariant holds under arbitrary interleavings`
— which is **pre-existing and unrelated to this PR**; it is intermittent
because it depends on which interleavings fast-check happens to generate,
and the underlying defect is described below. The four new suites (56 of
those 250 tests) are:

| Suite | Tests |
|---|---|
| `dashboard-auth.test.ts` | 12 |
| `dashboard-reads.test.ts` | 23 |
| `dashboard-ledger.test.ts` | 14 |
| `dashboard-extract.test.ts` | 7 |

## Pre-existing bug found (NOT fixed here — out of B-0's scope)

`deferJob` re-queues a leased batch job unconditionally, so it can
collide with the partial unique index `jobs_dedupe_queued` (job spec §8's
"at most one queued batch job per (system, type)"):

```
enqueue(system S) → claim (S is now leased, so the index no longer sees it)
                  → enqueue(system S)  ← allowed, second job queued
                  → defer the leased one → UPDATE … SET state='queued'
                  → duplicate key value violates "jobs_dedupe_queued"
```

Confirmed **deterministically on a pristine `HEAD` worktree with none of
this PR's code present** (`core/src/queue.ts:556`). The property test only
surfaces it on the interleavings that happen to generate that sequence,
which is why it reads as a flake. It belongs to the job protocol, not the
dashboard, so it is reported rather than patched inside a B-0 PR.
Recommend a follow-up ruling on the intended semantics: does a deferral
of a job whose key was re-enqueued become a merge into the queued job, or
a dead-letter?

## Spec observations (flagged, not acted on — fence held)

1. **Proposal length bound.** The §4 and §6.10 amendments both say a
   proposal's treatment is *identical* to a description's, including "the
   same server-enforced length bound" — which is 500 characters. That is
   implemented exactly (`PROPOSAL_MAX = DESCRIPTION_MAX`, aliased so the
   two cannot drift). It is worth a future ruling whether 500 characters
   is the right ceiling for *suggested content*, which is a different
   thing from a gap description. Not changed here.
2. **Verdict transitions.** The §4 diagram shows verdicts cast on `open`
   requests, so that is what is implemented; anything already decided is a
   409 rather than a silent overwrite of another steward's decision. The
   amendment separately notes that "a rejected request that eleven more
   people file is a decision worth revisiting", which today has no
   transition. Recommend a ruling on whether `rejected → approved` is
   permitted, and by whom.

## Exit-criteria honesty

**Done and proven:** the gate's four clauses, DT-1 on all three
endpoints, DT-11, MT-14, the session-auth negatives, pagination bounds,
and byte-for-byte evidence reproduction.

**Deliberately not in this PR** (scope fence): no pixels, no views, no
frontend module — UI-A's SPA is B-1; no auditor role (B-4); no changes to
MCP tool enforcement or the publish path; no enrich-skill batch mode
(B-1); no write surfaces beyond §5's named inlets. DT-2, DT-3..DT-10 and
DT-12 are render-path and module tests and belong to B-1/B-3/B-4.

**FL-11 is partially covered.** Its dedup, proposal, verdict, no-git and
batch legs are green here. The remaining legs — batch PR merge resolving
exactly the trailered requests, an undraftable item returning to
`approved` with the skill's note, and the filer's reply path — need the
enrich skill's batch mode, which is B-1. They ride the existing L-5
CL-Resolves lifecycle and are not re-implemented.

**Not verified live.** Everything here is proven against the conformance
rig and the committed CP-7 evidence in a scratch database. Nothing has
been run against the live pilot estate, and the runbook's extraction step
has been *updated* (it needs a steward token now) but not re-run on the
pilot. That is an operator act.

**Deployment note.** The dashboard is enabled with the MCP surface —
same identity domain, same KB, one release train (UI-9) — and can be
turned off with `CORE_DASHBOARD_ENABLED=0`. Migration `0009` must be
applied before the surface answers.
