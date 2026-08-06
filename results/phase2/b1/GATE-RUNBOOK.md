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

You have already run part of this page — that first hour is what produced
findings **B1-F1..F4**, and the four fixes are in the build you are about
to run against. Extracted from the live pilot through the governed read
APIs, **2026-08-06 19:30**:

| Act | State | Evidence |
|---|---|---|
| 1 — sign in | done | — |
| 2 — KB Health | done | 5 sources; **ga4 stale** (17d against a 3d threshold), **gsc stale** (6.3d); supabase fresh; Looker Studio / Power BI correctly *not sync sources*. Docs **2 verified / 6 draft / 34 contaminated** of 42 |
| 3 — Ops / dead letter | **done** | `dead_letter: {open: 3, superseded: 8}` — the 11 rows resolved into 3 real problems and 8 pieces of history, which is B1-F2's first half working |
| 4 — drift queue | done | `drift_prs: {available: true, prs: []}` — the empty-and-says-why state, **which is the pass** |
| 5.1 — read the queue | done | 10 issues: **6 open, 4 dismissed** (yours, with reasons) |
| **5.2 — acknowledge** | **not started** | **0 triaged.** Of the 6 open: **4 `capability_gap`**, 1 `missing_doc`, 1 `coverage_gap` |
| **5.3–11** | **not started** | the knowledge-request queue is **empty** — 0 `enrichment_request` rows. Act 6 creates the demo's data |

So: **restart the stack (act 0), then start at 5.2.** Acts 1–4 are worth
a glance on the way past — the screens changed under you when B1-F1..F3
landed — but their clauses are recorded above and do not need re-running.

**One number to have in your head before 5.2:** four of your six open
issues are `capability_gap`. That is the kind B1-F4 is about, and act 5.2
asks you to acknowledge one on purpose.

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

Sign out. Sign in **as a reporter** — ideally as Eda, whose identity
already exists from A-2, so a second real human's request goes through
the loop. If that is not convenient, use any reporter identity that is
not your steward one; the point is that filer and verdict-giver are
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

**Either way, file a second request that is deliberately vague** —
something no evidence could settle, like "the churn number should be
written down". That one is act 9's honest-skip case, and the demo is
weaker without it.

*Record:* both issue ids; **the sentence you typed and the agent's reply,
verbatim** (this is the clause's evidence, so a paraphrase of it is not
evidence); and, once you reach act 7, whether the stored `proposal`
matches what you typed word for word. If the agent claimed it had *added*
something to the KB rather than filed a request, or tidied your words,
write that down — either is a finding.

### Act 7 — the steward's verdict

Sign out. Sign back in as **yourself**.

Open **Gap Triage → Knowledge requests**. Both requests are there, open.

Press **History & proposal** on the first. The proposal is shown in its
own frame, labelled as the requester's words, quoted — not in the
product's voice. Read the label: if this is approved and drafted, the doc
is written in the KB's voice and *cites* the submission rather than
containing it.

**Approve both.** Read the sentence above the button before you press it:
approving means worth drafting; it writes ledger state and nothing else.

*Optional, and worth doing once:* before approving, sign in as the
reporter and press Approve on their own request. You get the server's
403, printed as the server's own words. The button was not hidden from
them — hiding it would have taught them nothing, and the client is never
the thing that says no.

*Record:* the approved states with your name and timestamp on them.

### Act 8 — deliver the batch

Still in **Knowledge requests**, the **Approved worklist** panel now shows
the count. Press **Deliver batch to the enrich skill**.

Read the response: a batch id, a count, and a sentence stating that
nothing has been written to the knowledge base and no pull request
exists. The trigger hands over a work list. That is all it does.

*Record:* the batch id.

### Act 9 — the enrich skill drafts

**This act is a Claude Code session, by design** — authoring intelligence
lives in the customer's session (RA-1), not in the product.

In a Claude Code session with the steward setup bundle:

```
Use the enrich skill in queue-driven batch mode. A batch has been
delivered — read it from the governed ledger API and draft from it.
```

The skill reads the batch through `/v1/dashboard/ledger?status=batched`
as you, drafts what it can ground, and:

- cites each approved request as `customer-provided, <name>, <date>`,
  taken from **what the ledger recorded**, never re-typed from the
  request body;
- writes in the KB's voice and does not paste the requester's words;
- **returns the vague request to the queue** with a note saying what
  evidence would unblock it, and leaves it out of the trailers;
- opens one PR carrying the request→doc mapping and one `CL-Resolves`
  trailer per request it actually satisfied.

**Check three things before you go further.** In the PR: the mapping
section exists; there is exactly one trailer, for the answered request;
the returned one is named with its reason and appears in no trailer. Back
in **Gap Triage**, the vague request now reads *approved* with a "came
back from a batch" note — approved work waiting for evidence, not failed
work.

*Alternative, if you want AS-18's machine evidence instead of or as well
as this:*

```bash
cd core && node_modules/.bin/vite-node test/fixture-deployment.ts -- \
    --out /tmp/cl-fixture.json
cd .. && .venv/bin/python -m tools.skill_scenarios \
    --connection /tmp/cl-fixture.json --model claude-opus-4-8 \
    --out results/phase2/b1-as18 --only enrich-batch
```

That runs the same skill against the fixture deployment with a staged
batch and asserts every AS-18 clause mechanically. It costs a model call
and is the checkpoint's conformance evidence for AS-18; the live act
above is the product demonstration. **Neither substitutes for the other,
and neither has been run by the session that wrote this page.**

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

If it is right, **merge it under your own name**. That merge is the
certification act (KB-7). Nothing in this product can perform it, and
that is the single most important line in the whole dashboard spec.

### Act 11 — the requester sees the resolution

Within a minute of the merge, the core's resolution sweep reads the
trailer and closes the issue.

Sign in **as the requester**. Look at the sidebar: **What came back**
carries a badge.

Open it. The resolved request is there, with a link to the merged pull
request — the diff that answered them, which is the thing worth reading.
Press **Mark all as read**; the badge clears. Reload, and it stays
cleared: "seen" is server state under their identity, not something the
browser remembered.

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
