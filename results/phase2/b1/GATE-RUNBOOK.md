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

## 1. What this run proves

| # | Gate clause (plan §4, B-1 + D-101.5) | Act |
|---|---|---|
| 1 | Freshness map consuming `sync_enabled` — the two-silent-days shape now visible | 2, and 2b for the disabled state |
| 2 | Doc-status counts | 2 |
| 3 | Drift-PR queue routing to the git provider, **no merge affordance** | 4 |
| 4 | Triage queue ordered by occurrences / distinct_subjects | 5 |
| 5 | LED-R5 neutralization asserted on the render path | machine-checked (DT-3), visible at 5b |
| 6 | Gap resolution surfaces to the filer — the UI-D badge | 11 |
| 7 | Knowledge Requests queue with DT-11 / DT-12 green | machine-checked; visible at 7–8 |
| 8 | **The demonstration**: request (with proposal) → verdict → batch → enrich PR merged as R2 → requester sees the resolution | 6–11 |

**What is already machine-checked, before this page was written.** Do not
re-prove these by hand; the run is about whether the shipped screens are
usable by a person on the real estate.

- `core/test/dashboard-kbhealth.test.ts` (13) — the freshness map against
  the policy, DT-9 in both states *and* agreeing with `/healthz`, doc
  counts per caller's visibility, contamination paths, DT-3, the no-merge
  property asserted over the server sources *and* the shipped bundle, the
  lineage read view's node-by-node filtering.
- `core/test/dashboard-b1.test.ts` (26) — DT-10 (the badge, its ack, and
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
| Suites green at this commit | `cd core && npx vitest run` (expect **345 passed / 4 skipped / 30 files**) and `.venv/bin/python -m pytest -q` (expect **792 passed / 14 skipped / 1 failed**) — that one failure is `test_no_contamination_in_current_kb`, which is **estate state** (34 docs awaiting triage), not this code, and act 5 is where you start working it down |
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

Migrations `0012` and `0013` are new in this build (the inbox acks and
the return-to-queue columns). `make stack-pilot` applies them at boot;
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

**Jobs** opens on the dead-letter tab. Expect **8 dead-lettered jobs**.
Pick one and read its error. Press **Re-enqueue as me** on one of them.

Look at what happens: a *new* job id, and a line saying the dead job is
unchanged. Confirm on the same screen — the dead row is still
dead-lettered with its error. That is deliberate: the dead row is the
evidence that something failed, and a re-enqueue that flipped it back to
`queued` would erase the fault while looking like a fix.

Now go to **Connections** and press **Sync now** on ga4 and on gsc — the
two stale sources act 2 showed you. (Sync lives on the connection because
that is the thing being synced.)

*Record:* the new job id and the unchanged dead row.

### Act 4 — the drift-PR queue

Back to **KB Health**, bottom section. If the syncs from act 3 produced
drift, an open PR is listed here.

**Read the affordances.** Each row is a link out to GitHub. There is no
merge button — and the absence is asserted two ways in the suite: no
merge-shaped path exists in the server sources, and none in the shipped
browser bundle. The product never merges (SO-B); reviewing the diff and
merging it is your act, in your git provider, under your own sign-in.

Follow one link. Merge or don't — that decision is yours and it happens
*there*, which is the whole point.

*Record:* the queue with its links, and the absence of a merge control.

### Act 5 — triage the contamination

This is the morning's real work and the reason the checkpoint exists.

Open **Gap Triage → Gap triage** tab. Expect ~10 open issues, ordered by
occurrences then distinct subjects — the queue's own argument for what
matters, not a date sort.

Pick the top issue. Press **History & proposal**: the event stream, each
event with its detector class and (because you are a steward) its
subject. Note what is *not* there: the queue itself carries counts only,
never who.

Then take one contaminated doc from act 2 and repair it properly:

1. In `~/Desktop/kb`, read the doc and the object that contaminated it.
2. If the doc is still true, clear the contamination marking and say why
   in the commit message. If it is wrong, fix the claim.
3. Open a PR. **Merge it yourself as R2** — that merge is the
   certification act, and nothing in the product can do it for you.
4. Reload KB Health. The contaminated count is one lower.

One doc is enough for the gate. Thirty-three left is an honest number to
record.

**Act 5b — LED-R5, if you want to see it.** File a gap (form at the
bottom of Gap Triage) whose text contains `<script>alert(1)</script>` and
some `**markdown**`. It renders inert — as characters, not as markup —
and the stored row was already scrubbed before it got here. The suite
asserts this (DT-3); this is just the human version.

---

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

Use the form at the bottom. Choose **Knowledge request**. Write something
real about the pilot estate — a genuine hole you know of. Fill in **What
it should say** with the content you believe is right.

Submit. Read the confirmation: the issue id, the occurrence count, and
who it routed to.

File **a second request** that is deliberately vague — something no
evidence could settle, like "the churn number should be written down".
That one is act 9's honest-skip case, and the demo is weaker without it.

*Record:* both issue ids.

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
