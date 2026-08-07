# B-1 — the gate demo (operator runbook)

**The steward's first real morning.** Everything below happens in a
browser, as your own IdP identity, against the live pilot stack and its
real backlog. No `psql`, no `docker exec`, no admin CLI — the point of
this checkpoint is that a steward can run their morning from the product,
so reaching for a terminal invalidates the demo rather than shortcutting
it. (Two exceptions are named where they occur: standing the stack up,
and the enrich skill's own session, which is a Claude Code session by
design.)

Read the page once before starting. Roughly 60–75 minutes, in two halves
you can run on different days: **acts 1–5** are the morning (KB Health,
Ops, drift review, triage), **acts 6–11** are the knowledge-request loop
(D-101.5's end-to-end).

---

## 0. Where this run stands

You have run most of this page. The first hour produced findings
**B1-F1..F4**; acts 5.2 through 8 produced **B1-F5..F8**, one of which
(B1-F6, the deleted prices) became an owner ruling of its own — **D-115**.
The fixes for all of them are in the build you are about to run against.
Read from the live pilot through the governed APIs, **2026-08-07 15:xx**:

| Act | State | Evidence |
|---|---|---|
| 1–4 | done | recorded in the table below this one; clauses met |
| 5.1 — read the queue | done | 14 issues now: 6 open · 4 dismissed · 1 triaged · 2 resolved · 1 batched |
| 5.2 — acknowledge | **done** | 1 `capability_gap` triaged — B1-F4's *"this one needs a person"*, with D-81 quoted on the card |
| 5.3 / 5b — a contaminated doc | **done** | `missing_doc` **resolved** by KB PR #40 (`subscriptions.plan_code`), drafted over a live contamination flag under explicit override |
| 6 — submit a request | **done** | 1 `enrichment_request`, filed by `reporter`, occurrences **2** — the second filing is B1-F6's proof (see below) |
| 7 — the verdict | **done, approve only** | approved by `alper`. **No request was rejected** — the reject-with-reason half of the loop is *unexercised live*; it has tests, not a demo |
| 8 — deliver the batch | **done** | `batch-61e70bc8-69ff-45fc-b628-9f756c8ec88c`, 1 request |
| 9 — the skill drafts | **done 2026-08-07 by the session** | see act 9 — run headless with the compiled steward bundle against the live core |
| **10 — merge as R2** | **yours, and next** | the batch PR is open and waiting |
| **11 — the resolution reaches the filer** | **yours, after the merge** | |

**The one act that is still nobody's and should be somebody's:** act 7's
**rejection**. The runbook asked for three requests so a rejection would be
exercised; one was filed. Two minutes in the browser closes it — file a
request you would genuinely decline, reject it with a reason, then sign in
as that filer and read the reason in **What came back**. Until then, that
clause is honest as *"tested, not demonstrated"* and is recorded that way
in the gate check.

**On the batched request, and worth having in your head before act 10:**
the issue holds **two** filings of the same sentence. The first (09:46) was
stored with every numeral deleted; the second (10:46), after D-115 landed,
carries **4.99 / 14.99 / 3.75 / 99.99 / 1.92** intact and is flagged
`number`. `list_gaps` returns the **latest** filing, so the skill drafted
from the intact one.

---

## 1. What this run proves

| # | Gate clause (plan §4, B-1 + D-101.5) | Act |
|---|---|---|
| 1 | Freshness map consuming `sync_enabled` — the two-silent-days shape now visible | 2, and 2b for the disabled state |
| 2 | Doc-status counts | 2 |
| 3 | Drift-PR queue routing to the git provider, **no merge affordance** | 4 |
| 4 | Triage queue ordered by occurrences / distinct_subjects, and actionable | 5 |
| 5 | LED-R5 neutralization asserted on the render path | machine-checked (DT-3); try it yourself at 5.2 by filing a gap containing `<script>` |
| 6 | Gap resolution surfaces to the filer — the UI-D badge | 11 |
| 7 | Knowledge Requests queue with DT-11 / DT-12 green | machine-checked; visible at 7–8 |
| 8 | **The demonstration**: request (with proposal) → verdict → batch → enrich PR merged as R2 → requester sees the resolution | 6–11 |
| 9 | Skill spec §5's volunteered-knowledge clause (D-114.3c) — a session files the request itself, with the user's words | **6a, and only 6a**: the shipped test is a grep over the skill file and is explicitly not evidence of this (D-78) |

**What is already machine-checked, before this page was written.** Do not
re-prove these by hand; the run is about whether the shipped screens are
usable by a person on the real estate.

- `core/test/dashboard-kbhealth.test.ts` (13) — the freshness map against
  the policy, DT-9 in both states *and* agreeing with `/healthz`, doc
  counts per caller's visibility, contamination paths, DT-3, the no-merge
  property asserted over the server sources *and* the shipped bundle, the
  lineage read view's node-by-node filtering.
- `core/test/dashboard-b1.test.ts` (41) — DT-10 (the badge, its ack, and
  a re-verdict firing it again), the governance-audit rows, Ops
  re-enqueue leaving the dead job dead, DT-5, the `batched → approved`
  return, and the **whole D-101.5 loop end to end without an agent**:
  verdict → batch → merged PR with one trailer → exactly that request
  resolved → the filer's inbox showing it.
- `core/test/dashboard-ledger.test.ts` (B-0) — DT-11 and DT-12 at the
  server, unchanged and re-run.
- `tests/test_skill_conformance.py` (43) — the S1b citation, trailer and
  no-verbatim rules as CI regression tests. **These are not AS-18's
  evidence** (D-78): they cannot fail when the skill misbehaves.

**What only this run can show**: that the morning works. And **AS-18's
behavioral half** (act 9's alternative), which needs a model call.

## 2. Words used below

- **Contaminated** — a breaking change landed under something this doc
  relies on. The doc may now be wrong; nothing has decided that it is.
- **Stale** — a source's newest snapshot is older than the threshold
  `sync-policy.yaml` sets for it. Only a source *in* the policy can be
  stale; one outside it has no threshold to cross and says so.
- **Approve** — *worth drafting*. It changes ledger state and nothing
  else: no document, no pull request, no certification. Certification is
  you merging a reviewed diff under your own name.
- **Batch** — up to ten approved requests handed to the enrich skill as a
  work list. The trigger drafts nothing.
- **Returned** — the skill could not draft a request without guessing, so
  it handed it back with a note. Approved, waiting for evidence.

## 3. Before you start

| Prerequisite | How to check |
|---|---|
| Suites green at this commit | `cd core && npx vitest run` (expect **360 passed / 4 skipped / 30 files**) and `.venv/bin/python -m pytest -q` (expect **792 passed / 14 skipped / 1 failed**) — that one failure is `test_no_contamination_in_current_kb`, which is **estate state** (34 docs awaiting triage), not this code, and act 5 is where you start working it down. **Both were run at `e5f2de3` on 2026-08-06 and match exactly** — you do not need to re-run them |
| *(if you do re-run the core suite)* | On a loaded machine — the pilot stack up, pytest running alongside — vitest reports `2 failed` **suites** with `Error: [vitest-worker]: Timeout calling "fetch"`. That is the module transformer timing out, not a test failing: `npx vitest run test/conformance.test.ts test/connections.test.ts` on its own passes 40/40 in 30 seconds. Read the error line before treating a red count as a regression |
| Stack running the build that contains B-1 | act 0 |
| Vault unsealed | `curl -s localhost:8100/healthz \| grep -o '"sealed":[a-z]*'` → `"sealed":false` |
| Your identity carries `steward` | the pilot steward account carries `["steward","ops"]` |
| Browser sign-in works | **A4-F5**: on a single-machine install the issuer must resolve from your browser too. If sign-in redirects to a host your browser cannot reach, set `CL_HOST_ADDR=127.0.0.1` and restart, per playbook §4 |

### Act 0 — rebuild and restart

**Already satisfied, and verified rather than assumed (2026-08-06 19:30).**
The running stack carries B1-F1..F4 in both halves — the API serves the
per-kind `disposition` with **D-81 quoted in its `why`**, and the bundle
served at `/app/app.js` carries *"This one needs a person"*, *"A skill
can close this"*, *"Came back from a batch"* and the re-enqueue chain
line. Migrations `0012`/`0013`/`0014` are applied (the inbox answers, the
return state renders, the dead-letter split computes). **You can start at
act 5.2.**

Run act 0 only if you want a clean start, or if something below does not
match this page:

```bash
cd ~/Desktop/DataProject
make stack-pilot          # runs check-toggle-env.sh first; heed it
```

Then confirm the build actually carries B-1:

```bash
curl -s localhost:8100/healthz | python3 -m json.tool
```

`dashboard_enabled: true`, `sync_enabled: true`, `vault.sealed: false`.
A core started without the right env answers `ok` here and 404 at
`/app/` — that pair is what cost two days once, which is why the packet
states the whole toggle set.

Migrations `0012`, `0013` and `0014` are new in this build (the inbox
acks, the return-to-queue columns, and the re-enqueue pointer — `0014`
also moves the handful of existing pointers out of the `error` object,
where the first cut wrongly put them). `make stack-pilot` applies them at boot;
if the core exits at startup complaining about a column, it did not.

---

## THE MORNING

### Act 1 — sign in

Open `http://localhost:8100/app/`. Sign in as yourself.

**Look at the sidebar.** Connections, KB Health, Gap Triage, Ops, Publish
are live. Setup, Profiles, Audit and Benchmarks are listed and marked
unbuilt — that is deliberate (UI-10): a menu that hides what is coming
teaches nobody. Below them, **What came back** is your reply path; it
carries a number when something you filed has been answered.

*Record:* a screenshot of the shell.

### Act 2 — KB Health: the TRUE backlog

Open **KB Health**. Read it top to bottom before doing anything.

**Freshness.** Five sources. Expect **ga4 and gsc stale** — ga4 by weeks,
gsc by days, both against a 3-day threshold. Looker Studio and Power BI
are *not sync sources* and say so: freshness is not their verdict, and
calling them green would be a claim about a snapshot nobody expects.

**Document status.** Expect roughly **2 verified, 6 draft, 34
contaminated** of 42 human-owned docs. That number is the morning's real
work. It is also *yours*: the note under the tiles says the counts cover
what your roles can see, because another role legitimately reads a
smaller total.

**Contamination.** 34 rows, each naming the object whose change
contaminated the doc and **how the contamination reached it** — a direct
dependency, a walked lineage chain, or `unknown`. Read a few `unknown`
ones: an unknown path means the doc relies on something it never
declared, which is worth a look for that reason alone.

*Record:* the freshness table and the doc-status tiles. **These numbers
are the demo's test data, not a defect.**

### Act 2b — DT-9, deliberately (5 minutes, optional but cheap)

The clause is that a *configured but disabled* sync engine is visible
rather than silent. Prove it on purpose:

```bash
cd ~/Desktop/DataProject
docker compose exec -T core sh -c 'echo' >/dev/null   # (no-op; see note)
```

Simplest honest route: stop the stack, set `SYNC_ENABLED=0` in the env
file the overlay reads, `make stack-pilot`, reload KB Health. A banner
appears naming the count of systems the policy configures and stating
that no trigger will fire. Put it back to `1` and restart.

If you skip this act, say so in the evidence — the automated test covers
the clause (DT-9, both states, and agreement with `/healthz`), and the
gate does not depend on doing it by hand.

### Act 3 — Ops: trigger the stale syncs

Open **Ops**.

**Jobs** opens on the dead-letter tab, showing **the jobs that still
need somebody** — not every job that ever died. A dead job you have
already re-enqueued is kept as the record of the original failure and
moved out of the way; the line above the list gives both numbers and a
toggle for the handled ones, and a handled row says whether its chain
ended in a success. (That split is finding B1-F2's first half: after one
morning of act 3, eleven dead rows turned out to be three problems and
eight pieces of history.)

Expect roughly **3 needing attention** and **8 already handled** once you
have worked through this act.

**Read the errors before pressing anything.** Several of these jobs were
queued *before* the vault migration and carry `env://SUPABASE_DSN` in
their payload; the runner has had no `env` resolver since A-4, so those
jobs failed with `auth_error: no resolver for its scheme`. That tail is
finding **B1-F1** (`results/phase2/b1/FINDINGS.md`) and it is the reason
this act is worth doing on the real estate rather than a fixture.

Press **Re-enqueue as me** on the supabase snapshot job.

**What to look at, in order:**

1. If the job's captured references differ from the connection's current
   ones, a panel says so and shows both. That is the fix: the new job is
   built from the connection's registration, **not** from what the dead
   job captured — so a job queued before A-4 now runs against
   `vault://…` and can actually succeed.
2. The screen then **follows the new job** and reports its outcome in
   place: succeeded, or dead-lettered with the new error. Wait for it.
   If it dead-letters again, read the error — the second failure is a
   different fact from the first, and pressing again would replay the
   same configuration.
3. The dead row is still dead-lettered, with its error, now carrying
   "already re-enqueued as …". It is the evidence that something failed,
   and nothing here rewrites it. Its button is gone: the chain continues
   from the newest job, not from a job two attempts old.

Then go to **Connections** and press **Sync now** on ga4 and on gsc — the
two stale sources act 2 showed you. (Sync lives on the connection because
that is the thing being synced.)

*Record:* the captured-vs-current panel if it appears, the new job's
outcome, and the unchanged dead row with its successor named.

**A note on jobs you cannot re-enqueue.** `execute` and `publish` jobs
refuse, and say why: their payload is somebody's statement, identity and
granted guardrails, not a connection's configuration. Re-running one
would re-run a stranger's request with nobody waiting for the answer.
Two of the dead rows are `execute` jobs from the benchmark harness —
press one to see the refusal, and read it.

### Act 4 — the drift-PR queue

Back to **KB Health**, bottom section.

**An empty queue is very likely, and it is a pass.** Drift PRs exist only
when a source's schema actually moved; if nothing changed in Supabase
since the last sync, the correct answer is *no open drift PRs*, and the
screen says exactly that rather than showing you a zero. Read the dark
state — it names why the list is empty — and record it. **That is act 4
complete.** The gate clause here is *routing without a merge affordance*,
and its no-merge half is machine-checked two ways (no merge-shaped path
in the server sources, none in the shipped bundle), which does not depend
on a PR existing.

**If a PR is listed** (because act 3's syncs found drift, or because you
have staged some): each row is a link out to GitHub, carrying no
credential. There is no merge button. The product never merges (SO-B);
reviewing the diff and merging it is your act, in your provider, under
your own sign-in. Follow one link and see where it takes you.

**If you want to see the queue populated on purpose** — worth doing once,
but it is a bigger act and it is optional here — stage a breaking change
the way A-1's drill did (`results/phase2/a1-drill/`): change a column in
Supabase, run the sync, and the pipeline opens a real drift PR you can
then review with `review-sync`. That is A-1's demo, not B-1's, and B-1's
clause does not need it.

*Record:* either the populated queue with its links and the absence of a
merge control, or the dark state and the sentence it gives you.

### Act 5 — work the gap queue

**What this act is for:** proving that a steward can look at what the
estate is missing, decide what is worth doing, and hand that decision to
something that does the work. You will not write a document by hand at
any point.

**Three actors, and you are only one of them.** This is the whole shape
of the product, so it is worth having in your head before you start:

| Who | Does | Cannot |
|---|---|---|
| **The dashboard** (you, here) | decides *what is worth doing* | write documents, open PRs, merge |
| **The enrich skill** (a Claude Code session) | writes the documents and opens **one pull request** | decide what is worth doing, merge |
| **You, in your git provider** | read the diff and **merge** | — |

Nothing crosses those lines. That is why triaging feels like it "only"
changes a status: changing the status *is* your act, and it is what tells
the skill where to work.

#### 5.1 — read the queue

Open **Gap Triage → Gap triage** tab. Expect around 10 open issues,
ordered by how many times each was hit and by how many different people
hit it — not by date. The top of the list is the estate's own argument
about what matters.

Press **History & proposal** on the top one. You get the event stream:
every time this gap fired, which detector or which person, and when.

#### 5.2 — decide, on two or three of them

Each open gap now offers two buttons.

**Acknowledge — "this is real."** The gap moves to `triaged`. **What that
buys depends on the kind**, and the panel on each gap says which:

- **A skill can close this** (`missing_doc`, `missing_entity`,
  `missing_join_path`, `uncertified_metric`, `doc_schema_mismatch`,
  usually `coverage_gap`) — acknowledging puts it on the enrich skill's
  work list, and you run the skill in 5.3.
- **This one needs a person** — most importantly **`capability_gap`**,
  which is the kind four of your six open issues are. These carry DDL a
  customer DBA must apply, usually a reporting view; the object does not
  exist yet, so there is nothing to document and no skill can close it.
  Acknowledging records that you have seen it. **The next move is yours:**
  apply the DDL, re-sync so the new object lands in a snapshot, and only
  then does documenting it become ordinary enrichment. (`guardrail_hit`
  is ops config; `abandoned_journey`, `benchmark_regression` and
  `result_disputed` are signals for you to interpret.)

The **Working the queue** panel splits your acknowledged items along
exactly that line: *the enrich skill can close these* / *these need you*,
each with its next act.

**Dismiss — "not worth doing."** Needs a reason, and the reason is kept.
The row is not deleted: if the same gap happens again it reopens by
itself and the next person reads why you declined it. That is on purpose
— a `wont_fix` that eleven more people hit deserves a second look, and
the count is the argument.

Acknowledge two or three. **Acknowledge at least one `capability_gap`
too** — it is the case that proves the distinction, and seeing it land in
"these need you" rather than on the skill's list is the point of the act.
Dismiss one with a real reason.

**Your six open rows, as of 2026-08-06 19:30** — so you can see the split
before you open the screen rather than after:

| Kind | Title | A skill can close it |
|---|---|---|
| `capability_gap` | `supabase.reporting` (**3 occurrences** — the top of your queue) | no |
| `capability_gap` | `gsc.standard.impressions, ga4.standard.screenPageViews` | no |
| `capability_gap` | `supabase.reporting.v_user_signups_by_day` | no |
| `capability_gap` | `supabase.public` | no |
| `missing_doc` | `supabase.public.subscriptions.plan_code` | **yes** |
| `coverage_gap` | `certified exceeded limit metric overage` | **yes** |

The useful pair to acknowledge is **`supabase.reporting`** (the
`capability_gap` at the top, which is also the one act 7.0's reporting
views are about) and **`supabase.public.subscriptions.plan_code`** (the
`missing_doc`). Two rows, two different answers, one verb — read both
panels side by side and check that the `capability_gap` one **names D-81
on screen**. If both panels say the same thing, B1-F4 has regressed and
that is the finding.

**Note what this leaves the skill in 5.3:** with only one `missing_doc`
and one `coverage_gap` acknowledgeable, the enrich batch will be small.
That is correct and not a thin demo — the four it *doesn't* pick up are
the demonstration.

#### 5.3 — hand it to the skill

Open a **Claude Code session with your steward bundle** and say:

```
Run the enrich skill. Take the acknowledged items from the fault ledger
as the batch, ground each claim in evidence you can cite, and open one
pull request.
```

The skill reads the triaged items **of the kinds it can close** —
`list_gaps` is in the steward profile, and the skill filters by kind
rather than taking everything acknowledged, so your `capability_gap`
rows stay where they are. It gathers evidence for each, drafts the docs with graded
`sources`, re-renders the machine docs, runs the KB validation locally,
and opens **one pull request** for the batch. Anything it cannot ground
it skips and names in the PR body rather than guessing at — that is its
central rule, and a batch that covers 5 of 8 with the other 3 explained
is a correct outcome, not a failure.

#### 5.4 — merge it, and that is the certification

Read the pull request. **Read the diff, not the body** — the body is what
the skill claims, the diff is what will be true of the knowledge base.

Check three things:
- every drafted doc says `status: draft` (the skill never certifies);
- the `sources` on each doc are graded honestly — `observed in N queries`
  means somebody observed it, `inferred from column names` means nobody
  did;
- the PR body's "ungrounded gaps" section names what it could not close.

If it is right, **merge it under your own name**. That merge is the act
that puts knowledge into the estate, and nothing in this product can
perform it for you. That is the single most important line in the
dashboard spec, and this is where you feel it.

Reload **KB Health**. The doc-status counts have moved.

*Record:* the queue before, what you acknowledged and dismissed (with the
reason), the PR the skill opened, and the counts after.

---

### Act 5b — the contaminated docs (optional, and read this first)

Act 2 showed you 34 contaminated docs. **Repairing them is not a B-1 gate
clause**, and this runbook originally told you to fix one by hand — which
was wrong, and contradicted the product's own design. Do not hand-edit
the KB.

**What a contaminated doc actually is:** a breaking change landed under
something the doc relies on, so the doc *may* now be wrong. Nothing has
decided that it is. Repair means re-reading it against what the source
says today and either confirming it or correcting it — and that is
grounding work, which is a skill's job, not a text editor's.

**The proven agent path is A-1's** (`results/phase2/a1-drill/`): a
breaking change produces a sync PR, the steward runs the `review-sync`
skill on it, and the skill prepares a **repair PR** the steward merges.
That loop is shipped and was rehearsed live at A-1.

**What is not built:** an entry point for contamination that arrived in a
*past* sync PR, which is what these 34 are. The enrich skill's work list
covers ledger items, undocumented hot objects and harvested docs — not
"docs marked contaminated some time ago". So repairing this backlog today
means pointing a session at specific docs by hand, which works but is not
a product surface. **That gap is filed** (`results/phase2/b1/FINDINGS.md`,
B1-F3's tail) and belongs to A-5, whose gate is precisely "every
report-path L1 doc human-verified".

If you want to try one anyway, the honest instruction is:

```
Read systems/supabase/reporting/<doc>.md and the object its front-matter
names as the contamination source. Re-ground every claim in the doc
against what the machine doc says now. Correct what is wrong, keep what
is still true, and open a PR — leave status as draft, do not certify.
```

Then read the diff and merge it, as in 5.4. One doc is plenty; 33 left is
an honest number to record.

## THE KNOWLEDGE-REQUEST LOOP (D-101.5)

The end-to-end demonstration. **Six acts, and one of them is not yours.**

### Act 6 — submit a real request, with a proposal

Sign out. Sign in **as a reporter** — **use `eda`**. Two reasons, and the
second one is operational: her identity already exists from A-2, so a
second real human's request goes through the loop; and **her inbox is
empty** (verified 2026-08-06), whereas the generic `reporter` account
already carries **2 unread** resolutions from earlier runs. Act 11 asks
you to read a badge appearing — starting from zero is what makes that
unambiguous. If neither is convenient, any reporter identity that is not
your steward one will do; the point is that filer and verdict-giver are
different people.

Open **Gap Triage**. Note the queue is scoped to *what you filed* — the
server says so in a banner, and it is a server scope, not a filter the
page applied.

**There are two ways in, and the session one is the one that matters.**

**6a — from a session. This is the act, not an option.** Open a Claude
Code session with the reporter's setup bundle and ask a **real question**
of the estate — something you actually want to know, not a prompt written
to trigger the feature. Then, when the answer surfaces something the
knowledge base should have said, just *say so*, in your own words:

> "That's right — but the KB should really say that a refund is counted
> in the month the credit note is issued, not the month of the order."

The agent files it for you: `flag_gap(kind: enrichment_request)` carrying
your words as the `proposal`, under your own identity, into the same
queue the form writes to.

**Since the amendment this session applied, that behaviour is a spec
clause** — skill spec §5, D-114.3c — and not merely an instruction in a
skill file. So this act is the **only behavioural evidence the clause
has**: the shipped test greps the file for the instruction, which catches
its absence and proves nothing about what an agent does (D-78). Watch
four things, each of which is the clause failing if it is missing:

1. **It files without asking.** A session that says *"shall I note that?"*
   has already lost the request if you say "don't worry about it".
2. **Your words go in verbatim.** The `proposal` is your sentence, not a
   tidied summary of it — the doc later drafted from it cites you by name,
   so a paraphrase is the agent's prose wearing your authority. You will
   see the stored text in act 7; compare it to what you typed.
3. **It says "I've filed it", never "I've added it"** or "the KB now
   says". Nothing enters the knowledge base until somebody merges a diff.
4. **It relays what came back** — `routed_to`, and `occurrences` if
   somebody has asked before.

This is the path a reporter actually takes — they are mid-question, not
mid-form — and it is why the queue exists at all. It was the missing half
of the loop until finding **B1-F2** (`results/phase2/b1/FINDINGS.md`):
the tool and the queue were both built and no skill knew the move, so in
practice it was a queue only browser users could file into.

**If any of the four is wrong, stop and write down exactly what the agent
said.** That transcript is worth more than a clean run — it is a finding
against a spec clause, and it is the class of defect this whole checkpoint
keeps turning up.

**6b — from the browser (the fallback).** Open **Gap Triage**. Note the
queue is scoped to *what you filed* — the server says so in a banner, and
it is a server scope, not a filter the page applied. Use the form at the
bottom, choose **Knowledge request**, and fill in **What it should say**.

**File three in total.** One is the run; three is the demonstration, and
each one exercises a different half of the loop:

| # | What to file | What it is for |
|---|---|---|
| 1 | **The real one** — volunteered mid-session in 6a, with your words as the proposal | the loop end to end: verdict → batch → PR → resolution (clause 8) |
| 2 | **Deliberately vague** — something no evidence could settle, e.g. *"the churn number should be written down"* | act 9's honest-skip: the skill **returns** it with a note rather than guessing |
| 3 | **One worth declining** — something you would genuinely say no to (already documented, or out of scope) | act 7's **rejection with a reason**, and the badge it fires |

Number 3 is the one added by D-114's gate instruction: rejection and its
reply path are a different act from approval, and the runbook previously
had you approve everything, which never exercised them.

*Record:* all three issue ids; **the sentence you typed and the agent's reply,
verbatim** (this is the clause's evidence, so a paraphrase of it is not
evidence); and, once you reach act 7, whether the stored `proposal`
matches what you typed word for word. If the agent claimed it had *added*
something to the KB rather than filed a request, or tidied your words,
write that down — either is a finding.

### Act 7 — the steward's verdict

Sign out. Sign back in as **yourself**.

Open **Gap Triage → Knowledge requests**. All three requests are there,
open.

Press **History & proposal** on the first. The proposal is shown in its
own frame, labelled as the requester's words, quoted — not in the
product's voice. Read the label: if this is approved and drafted, the doc
is written in the KB's voice and *cites* the submission rather than
containing it. **Compare the quoted text to the sentence you typed in
6a** — word for word. A tidied proposal is finding-worthy (skill spec §5,
bound 1).

**Approve #1 and #2. Reject #3 with a real reason.** Read the sentence
above the button before you press either: approving means *worth
drafting*; it writes ledger state and nothing else. Rejecting keeps the
row rather than deleting it, and the reason you type **is shown to the
person who filed it** — so write it as something you would be content to
have read back to you.

**Then watch the reply path fire, immediately.** Sign out, sign in as
`eda`, and look at **What came back**: the rejection is there with your
reason, before any batch or any PR exists. That is DT-10's badge on the
rejection half — a distinct act from act 11's resolution half, and this
is the only place in the run that exercises it. Do **not** press *Mark
all as read* yet; leave it, so act 11 shows a badge that grew rather than
one that appeared from nothing. Sign back in as yourself.

*Optional, and worth doing once:* before approving, sign in as the
reporter and press Approve on their own request. You get the server's
403, printed as the server's own words. The button was not hidden from
them — hiding it would have taught them nothing, and the client is never
the thing that says no.

*Record:* the two approved states with your name and timestamp on them;
the rejected one with its reason; the stored proposal beside the sentence
you typed; and `eda`'s badge carrying the rejection.

### Act 8 — deliver the batch

Still in **Knowledge requests**, the **Approved worklist** panel now shows
the count — **2**, not 3: the rejected one is not work. Press **Deliver
batch to the enrich skill**.

Read the response: a batch id, a count, and a sentence stating that
nothing has been written to the knowledge base and no pull request
exists. The trigger hands over a work list. That is all it does.

*Record:* the batch id.

### Act 9 — the enrich skill drafts — **RUN 2026-08-07, by the session**

**This act is a Claude Code session, by design** — authoring intelligence
lives in the customer's session (RA-1), not in the product. It has now
been run once, headless, with the **compiled steward bundle** against the
live pilot. What follows is both the record of that run and the procedure
if you want to run it again.

Three things changed under this act since the page first described it, and
each was a defect the act found by being attempted:

- **B1-F8** — the page told the session to `curl` the ledger API with
  `$CL_TOKEN`. **There is no such token in a real session**: the bundle
  carries no credential (PA-1) and the MCP client's token is not in the
  shell. The batch is now read with the tool the session already holds:
  `list_gaps(status: "batched", kind: "enrichment_request")`, which
  returns each request's filing — the words, and the filer identity and
  date **as the server recorded them**, which is what the citation uses.
- **B1-F5** — nothing had told the session where its KB clone goes. The
  skill now provisions one at **`~/cl-steward/kb`** from the remote the
  bundle names, and builds its validation venv from the KB's own vendored
  wheel.
- **B1-F9** — a request the skill cannot draft is **handed back in
  words**, not returned: `batched → approved` has no session-reachable
  inlet, so the skill names it in the PR body and tells you it needs
  returning. Filed, not fixed; the recommendation is a `return_request`
  MCP tool.

The prompt was the skill's own entry point plus the one thing the ledger
cannot say — **D-116.2's provenance ruling**, that the subscription
figures are the owner's confirmed values and are cited
`customer-confirmed, Alper, 2026-08-06` rather than to the reporter whose
identity carries the filing, with that decision recorded in the PR body:

```
A steward has approved and delivered a batch of knowledge requests. Use
the `enrich` skill in its queue-driven batch mode (S1b), following the
skill exactly, end to end: provision your working copy, read the batch,
draft what you can ground, re-render and validate, and open one pull
request against the KB.
```

**Check these before act 10, in the PR:** the mapping section exists; one
`CL-Resolves` trailer per request actually satisfied and no others; the
provenance line is present and explains itself; and — new, per D-116.4 —
**the PR reports a CI check that ran.** The skill runs
`ci_gate.py <pr>` for exactly this and distinguishes *failed* from
*never reported*; if it reports exit 2, that is a stop, not a pass.

*Alternative, for AS-18's machine evidence rather than the product
demonstration:*

```bash
# The launcher needs a postgres and the variable that points at it —
# without CORE_TEST_DATABASE_URL it dies on "Vitest failed to access its
# internal state" (finding B1-F11; the command on this page used to omit
# both, which is why nobody had run it).
docker run -d --rm --name cl-as18-pg -e POSTGRES_PASSWORD=pg \
    -p 127.0.0.1:55432:5432 postgres:16
cd core && CORE_TEST_DATABASE_URL="postgres://postgres:pg@127.0.0.1:55432/postgres" \
    node_modules/.bin/vite-node test/fixture-deployment.ts -- --out /tmp/cl-fixture.json
cd .. && .venv/bin/python -m tools.skill_scenarios \
    --connection /tmp/cl-fixture.json --model claude-opus-5 \
    --out results/phase2/b1-as18 --only enrich-batch
```

That runs the same skill against the fixture deployment with a staged
batch — two requests, one groundable only to its proposal and one
undraftable — and asserts every AS-18 clause mechanically. It costs a
model call. **Neither substitutes for the other**: the fixture run proves
the clauses, the live act proves the mode is performable at all, which is
the thing B1-F8 showed it was not.

**Run 2026-08-07: PASS, 9 of 9** (`results/phase2/b1-as18/scenarios.json`).
The line worth reading is not the verdict but the tool trail —
`list_gaps → get_table → search_context → get_table …`, with **no shell
tool in the allow-list and no token in the environment.** The previous
version of this scenario handed the agent a bearer token the product gives
nobody, which is exactly how it passed while B1-F8 sat in the shipped
skill.

### Act 9's outcome, 2026-08-07 — **the PR was rejected, and the rule changed**

Recorded here because the page above describes the act and this is what it
produced. The session opened **KB PR #42** (one doc, one `CL-Resolves`, CI
green in 3 seconds, `ci_gate.py` exit 0) and the owner **rejected it** on
its content:

> "there is information from the CV Builder code base which we don't want
> because it is cheting for a test like this."

That is now **ruling D-117**, and it changes S1b: a request-driven doc is
grounded in **the request and the estate's own facts** — snapshot, machine
sibling, existing KB docs — and nowhere else. No application source, no
other repositories, no hunting for a second source. Where the request is
too thin to draft from, the skill **asks**. And where the doc that should
carry the knowledge is `contaminated`, the item **waits for that doc** and
is not redirected onto a writable neighbour.

**What that means for the batch in front of you.** The pricing request's
home is `systems/supabase/public/subscriptions.md`, which is
`contaminated` — so under D-117 it defers, and this batch drafts nothing
until that doc is repaired. Two ways forward, either of which closes the
loop; both are in `GATE-CHECK.md` §1:

1. file a request whose target doc is uncontaminated, approve it, deliver,
   re-run act 9 — the shortest path to a merged enrich PR;
2. repair `public.subscriptions` first (act 5b), then re-deliver this batch
   — answers the question actually asked.

**One thing worth keeping from the rejected PR**, and it is in the ledger
rather than the diff, so it survived: the app's own constant says the
annual price is **$99.90** (`ANNUAL_TOTAL_PRICE`, and
`PLAN_VALUE_USD.annual = 99.9`, last changed 2026-06-28) against the
**$99.99** in the request. Filed as `4c4ecb3d-fb41-4489-8d12-a13c0dd99a5f`.
If $99.99 is right, **the pricing page has been showing the wrong price
since June**; if $99.90 is, the ledger figure is a typo. Only the Stripe
Price behind `STRIPE_ANNUAL_PRICE_ID` settles it.

The governance half of that PR — `conventions.md`'s solo-operator section
— was moved to **KB PR #43** so it did not die with the rejection. That
one is yours to merge whenever you like; it touches no document content.

### Act 10 — merge as R2 — **STOP**

**This is yours and nobody else's.**

Read the PR's diff. Not the body — the diff. The body tells you what the
skill claims; the diff is what will be true of the knowledge base.

Check specifically:
- every doc is `status: draft` (the skill never certifies, CP-E3);
- no requester text appears verbatim anywhere in the diff (DT-12's other
  half — the doc should cite the request, not quote it);
- the `sources` on a request-only-grounded doc reads
  `customer-provided, <name>, <date>` **and nothing sturdier**. If it
  also claims "inferred from column names" or "observed in N queries",
  that is the CP-E5 violation the rule exists to catch, and it is a
  finding worth recording rather than merging past.

And one mechanical check before you press anything: **the PR must show a
CI check that ran and passed.** An absent check is not a passing one —
PR #40 sat for seventeen minutes with no run at all, looking exactly as it
would have if KB CI had been green (D-116.4). If the checks area is empty,
close and reopen the PR to fire one and wait for it.

If it is right, **merge it under your own name**. That merge is the
certification act (KB-7). Nothing in this product can perform it, and
that is the single most important line in the whole dashboard spec.

**And on this deployment, that merge is a bypass merge** — you are the
only human with write access, so required review cannot be satisfied and
GitHub will say so. That is now ruled and written down rather than left to
look like a governance failure: **solo-operator mode**, D-116.3, playbook
§11.1, and the KB's own `conventions.md` says it in the customer's words.
The bypass *is* the certification act; what it is not is a second pair of
eyes, and nothing in the record claims one. When a second person gets
write access, required review comes back.

### Act 11 — the requester sees the resolution

Within a minute of the merge, the core's resolution sweep reads the
trailer and closes the issue.

Sign in **as `eda`**. Look at the sidebar: **What came back** carries a
badge, and it should now read **2** — the rejection you left unread at
act 7, plus this resolution. A badge that grew is a stronger reading than
a badge that appeared: it says the count is per-item and server-held, not
a boolean somebody flipped.

Open it. The resolved request is there, with a link to the merged pull
request — the diff that answered them, which is the thing worth reading.
The rejected one sits beside it with your reason. Both are the same
mechanism; only the verdict differs, which is the point.

Press **Mark all as read**; the badge clears. Reload, and it stays
cleared: "seen" is server state under their identity, not something the
browser remembered.

**One more check, and it is cheap.** Sign in as yourself and open your
own **What came back**: it is empty, and it should be. You gave the
verdicts; you did not file the requests. The badge is per-filer, not
per-role — which is why it is a table keyed on `(subject, issue)` rather
than a column on the issue.

**The loop is closed.** Somebody asked, a steward judged, a skill drafted
what it could ground and honestly handed back what it could not, a human
certified by merging a reviewed diff, and the person who asked was told.

*Record:* the badge before, the resolved item with its PR link, and the
badge cleared after.

---

## 4. Same-day evidence extraction

The B-0 APIs are the extraction path (stamps included):

```bash
cd ~/Desktop/DataProject
# Your morning's governance acts — now including connection writes,
# verdicts, batches and returns (D-114.1).
./results/phase2/a2/extract-audit.sh 2>/dev/null || \
  curl -sS -H "authorization: Bearer $CL_TOKEN" \
    "http://localhost:8100/v1/dashboard/audit?limit=200" > results/phase2/b1/audit.json

curl -sS -H "authorization: Bearer $CL_TOKEN" \
  "http://localhost:8100/v1/dashboard/kb-health" > results/phase2/b1/kb-health.json
curl -sS -H "authorization: Bearer $CL_TOKEN" \
  "http://localhost:8100/v1/dashboard/ledger?status=all&limit=100" > results/phase2/b1/ledger.json
```

Commit those three plus your screenshots under `results/phase2/b1/`.

**One thing the audit extract will show that it did not before:** rows
whose `tool` starts with `dashboard.` — the governance writes D-114.1
added. A windowed row count is therefore no longer a count of tool calls
alone. That is the point, and it is stated here so nobody reads it as
contamination of the record later.

## 5. What this run cannot show

- **The gate demo is not a substitute for the suites**, and the suites
  are not a substitute for it. What only a person can show is whether the
  morning *works*: whether the freshness map told you something you
  didn't know, whether the contamination list was actionable, whether the
  verdict screen made the approve/certify distinction land.
- **Write that down.** In the CP-8 field-note style, and per D-108.3's
  lesson: notes are a named artifact of a run, not an optional extra.
  `results/phase2/b1/FIELD-NOTES.md`. A run that takes none writes that
  sentence down instead.
- **In-session gap surfacing is unbuilt.** The badge is the shipped F-10
  mechanism (UI-D). A line inside the requester's own session remains a
  skill-side candidate and is not in this build.

## 6. STOP

**The morning is the operator's.** Every act above happens under a real
identity on the real estate, and two of them — merging the repair in act
5 and merging the batch PR in act 10 — are certification acts that no
session may perform. Run it at your pace; stop at any act whose result
does not match this page and record what happened instead.

A recorded mismatch here is worth more than a run that was quietly
helped into passing.
