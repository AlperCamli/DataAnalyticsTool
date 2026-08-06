# B-1 findings

## B1-F1 — re-enqueue replayed a captured payload, so a pre-A-4 job could never succeed

**Found 2026-08-06 by the operator, on the gate runbook's act 3**, the
first time anyone pressed *Re-enqueue as me* on the pilot's real
dead-letter queue. Reported in three parts, which turned out to be one
fault and two of its symptoms.

### What was seen

> I clicked Re-enqueue as me, and it appeared like it goes to the running
> then immediately came back to the dead_lettered again. […] tracking the
> process of re-enqueue is not clear enough. Also, we have this in the
> queue, and create another dead lettered instance everytime I enqueue it:
>
> ```
> snapshot
> supabase · dead_lettered · attempt 1/5 · 0s ago
> auth_error credential reference 'env://SUPABASE_DSN': no resolver for
> its scheme (configured: vault://)
> ```

The chain was in the data:

| job | created | payload ref | outcome |
|---|---|---|---|
| `01KYW10ST…` | 2026-08-04 12:05 (**pre-A-4**) | `env://SUPABASE_DSN` | config_error |
| `01KZBD5CW…` | 11:26 | `env://SUPABASE_DSN` | auth_error |
| `01KZBD90G…` | 11:27 | `env://SUPABASE_DSN` | auth_error |
| `01KZBDF6C…` | 11:31 | `env://SUPABASE_DSN` | auth_error |

Meanwhile `sync_systems` holds
`vault://secret/contextlayer/connections/supabase#introspect_dsn`.

### The fault

**A job's payload is a *capture* of the connection registry, taken at
enqueue time. Re-enqueue replayed the capture.** So a job queued before
the A-4 vault migration carried the reference that used to be right, the
runner has had no `env` resolver since, and every press produced a fresh
dead job with the same impossible reference. The button could not have
worked, and pressing it harder made the queue longer.

This is the **fan-out rule** — the registry is the one source for what a
connection uses, and a captured copy that disagrees with it is not
evidence, it is a stale duplicate. It is also **A-4's removal rule from
the other side**: `env://` was removed as a resolver, and the job queue
turned out to be a place the old reference survived. A-4 found the same
shape in the G3 execution preflight (A4-F6); this is its sibling, and it
survived A-4 because nothing re-read old job payloads.

*Not* found by A-4's own checks, and worth saying why: every live
surface was green. The connection row was flipped and probed green, the
core resolved its config, five probes passed. The stale references were
in rows nobody reads until someone presses a button that had not been
built yet.

### Two symptoms, both real defects of their own

- **The pointer was in the wrong place.** The first cut wrote
  `error.reenqueued_as` onto the dead job — a success fact inside the
  field that says why the job died. The operator's phrasing ("the fault
  is written to the succeed but not erased from dead letters") is exactly
  what that looks like from outside.
- **Nothing followed the new job.** The UI answered "queued" and stopped,
  so the outcome had to be discovered by noticing a new row in a list the
  operator had just left. For a button whose whole purpose is to retry
  something, not reporting the retry's result is most of the feature
  missing.

### Fixed

1. **The payload is rebuilt from the current registration**, never
   replayed. The connection's stored `payload` is already
   `{config, credentials}` — the same shape a snapshot or probe job takes
   — so the substitution is clean rather than a translation. The
   connector name and version constraint come from the registration too.
2. **The response reports the difference** when the captured references
   and the current ones disagree, because the operator is about to see a
   different outcome from the same button and the reason belongs in the
   answer.
3. **No registration → refused**, with the reason: running a
   configuration the estate no longer has would prove nothing.
4. **`execute` and `publish` are refused.** Their payloads are not the
   registry's to rebuild — they carry a person's statement, their
   identity and the guardrails they were granted. Re-running one means
   re-running somebody else's request under their recorded identity with
   nobody waiting for the answer; for publish it would re-deliver a
   report to a BI tool because an operator was clearing a queue. The line
   is *whose request the payload holds*, not batch-vs-interactive.
5. **A second press on the same dead row is a 409** naming the successor.
   Three presses produced three parallel branches from one stale point;
   the chain continues from the newest job or not at all.
6. **`reenqueued_as` is its own column** (migration 0014), with the
   existing rows moved out of `error` rather than left behind.
7. **The UI follows the new job** to a terminal state and reports it in
   place — including "it failed too, read this before pressing anything
   else" — and renders the chain on the dead row.

### Tests

`core/test/dashboard-b1.test.ts`, five of them, staged in the pilot's own
shape: a dead job carrying `env://GONE_SINCE_THE_MIGRATION` against a
connection registered at `vault://…`. Asserted: the new job's payload
carries the current reference and contains no `env://` anywhere; the
response reports captured-vs-current; a second press 409s with the
successor's id; an unregistered system refuses; an `execute` job refuses
with the reason. Each fails with the old behaviour.

### What it says about the runbook

Act 3 said "press Re-enqueue as me" as if the interesting part were the
button. On this estate the interesting part was that the button exposed
a stale-reference tail A-4 left behind. The act is rewritten to say so,
and to have the operator read the captured-vs-current line rather than
watch for a state change.

---

## B1-F2 — the queue only browser users could file into

**Found 2026-08-06 by the operator**, mid-demo, in one sentence that
described the whole product rather than a screen:

> in the gap triage, I can't add the gaps to the enrich queue, but only I
> can fill the form and send that request by hands. However, the system
> should work like, while a reporter using the system, They can ask for
> an update in the KB and the agent should add the requests to a queue,
> then steward should approve or reject the requests, and the approved
> one should go to for another enrich session. And collected in a PR to
> be merged.

That is, exactly, the pipeline B-1 built — with one end missing.

### What was actually missing

Every piece existed:

| Step | State before this finding |
|---|---|
| A session files a request | **`flag_gap(kind: enrichment_request, proposal: …)` shipped** at D-101.3, tested by MT-14, and `flag_gap` is in the reporter profile's allowlist |
| Steward approves / rejects | built, B-1 |
| Approved → enrich batch | built, B-1 |
| Batch → one PR → merge | built, B-1 (S1b) |

So the inlet was reachable and **nothing drove it**. No skill mentioned
`enrichment_request`; the report skill's K-FAIL section said "call
`flag_gap` with the most specific applicable kind" and never named the
kind that carries a proposal, so an agent facing a user volunteering
knowledge either filed it as `missing_doc` without their words or did
not file it at all.

The fault is precisely the one the ledger spec's §4 amendment legislated
against — *"one queue whether or not the requester has a browser open"* —
and D-101.3's own words for why the tool inlet exists: *"a queue only
browser users can file into is not the queue D-101 adopted."* It was that
queue. The spec had been satisfied on paper by a tool nobody was told to
call.

**Why no test caught it.** Every conformance test drove the tool
*directly*: MT-14 calls `flag_gap` with a proposal and asserts the row.
That proves the inlet works. Nothing asserted that a **skill** would ever
reach for it, and a capability with no caller passes every test written
against the capability.

### Fixed

The report skill gains a section — **"Knowledge requests: when the user
knows something the KB doesn't"** — which is deliberately *not* a failure
exit, because the triggering case is a session that went fine and a user
who volunteered something. It carries:

- the call shape, with **`proposal` = their words verbatim, `description`
  = the agent's summary of the gap**, and an explicit instruction not to
  tidy the proposal (it is drafting evidence, and a summarized proposal
  is the agent's prose wearing the user's authority);
- a kind-selection table, because "most specific applicable kind" was
  doing too much work unassisted;
- the rule that a dead end where the user *also* supplies the answer is
  **two filings, not one** — the gap that blocked the session and the
  knowledge they gave — since a proposal attached to the wrong kind never
  reaches the enrichment queue;
- what to say afterwards, and the honesty bound on it: **"I've filed
  it", never "I've added it"**, because nothing enters the KB until a
  human merges a reviewed diff;
- *"do not ask permission to file"* — a request that dies because the
  agent asked "shall I note that?" and got "don't worry about it" is
  knowledge the estate lost to politeness.

### Tests

`core/test/dashboard-b1.test.ts`, three: a reporter's session
`flag_gap(enrichment_request)` appears in the steward's Knowledge
Requests queue with its proposal on the event stream and the filer set
server-side; a session-filed request runs the full verdict → batch
lifecycle (no second-class rows by inlet); and the shipped report skill
file carries the instruction, the verbatim-words rule and the filed-not-
added sentence.

The third one is a grep over a markdown file, which is a weak test of
agent behaviour and is not pretending otherwise — the strong version is a
behavioural scenario, and it belongs with AS-18's. What it does catch is
the regression that just happened: the instruction being absent entirely.

### Flagged, not done

**Skill spec §5 has no clause for this.** The report skill's spec section
covers S1–S8 and K-FAIL; a user volunteering knowledge mid-session is not
in it. The behaviour is required by the *ledger* spec §4 and the *MCP*
spec §6.10, so shipping it implements a merged requirement rather than
inventing one — but §5 should gain a sentence, and that is a spec
amendment outside this session's fence. Proposed for the next task 0,
alongside the fault-ledger §4 DDL enumeration.

**No behavioural scenario yet.** Whether a real agent reaches for
`enrichment_request` when a user volunteers something is exactly the kind
of claim D-78 says must be evidenced behaviourally. The natural home is a
fourth scenario beside AS-18's; it is not built, and the skill-file grep
above must not be reported as covering it.

---

## B1-F2's first half — a dead-letter queue that showed history as faults

Reported in the same message:

> that specific job fixed but other instances of the same job are still
> in dead letters.

After act 3, the pilot's dead-letter list showed eleven rows. Six of them
had successors that had **succeeded** — the re-enqueue worked, the chain
ended well, and every link in it still sat in the list looking like an
open fault. Three of those six were one chain, four links long.

**The rule now encoded:** a dead job with a successor **has been acted
on**; its story continues at the newer job, so it is *superseded* and
kept as the record of the original failure rather than shown as
outstanding work. A dead job with **no** successor is the one that still
wants somebody.

The tab counts what needs attention (3 on the pilot, not 11), a line
above the list gives both numbers with a toggle, and a superseded row
states its chain's ending — *"Fixed. Re-enqueued 3 times; the last
attempt succeeded."* Computed server-side by walking `reenqueued_as`
with a recursive CTE, bounded at 20 hops.

---

## B1-F3 — a triage queue you could read and not act on

**Found 2026-08-06 by the operator, on act 5:**

> I can see the history and proposal and read it, but what else can I do.
> There are open gaps in the triage and I can't do anything to them. What
> should I do, what are the capabilities what does act 5 expect from me?

The answer was: nothing, and the runbook was wrong about the rest.

### What was missing

B-1 shipped the **Knowledge Requests** half of the Gap Triage module with
its full lifecycle — verdicts, batches, returns, resolution — and left
the **gap** half read-only. Fault-ledger §8 specifies the actions
plainly, and none of them existed:

> issue view shows the event stream, linked docs/PRs, and one-click
> actions: acknowledge (→ `triaged`), assign, dismiss-with-reason, or
> **"export enrichment batch"**

So a steward could open a gap, read its event stream, and close the tab.
Ten open issues and no verb.

**Why it passed review.** B-1's gate clause reads "triage queue ordered
by occurrences/distinct_subjects" — and the queue *was* ordered, and the
test asserted the ordering. The clause describes a property of a list and
says nothing about acting on it, so a read-only list satisfied it
literally. The spec section that says otherwise is in a different
document, and nothing joined the two.

### Fixed

`POST /v1/dashboard/ledger/issues/:id/triage`, steward-gated, ledger
state only (UI-11 governs the whole module, not only the request queue —
asserted against the KB's refs and PR store, as DT-11 is):

- **acknowledge** (`open → triaged`) — *this is real, work it*. The state
  the enrich skill's S1 reads first, so a triaged gap is on somebody's
  work list rather than in a pile.
- **dismiss** (`open|triaged → dismissed`) — with a **required** reason,
  bound by LED-R2 like every other human-authored string. The row is kept
  rather than deleted, and L-4 reopens it if the gap recurs, with the
  dismissal preserved — a `wont_fix` that eleven more people hit deserves
  a second look and the count is the argument.

**The two lifecycles are refused to each other.** `acknowledge` on an
`enrichment_request` is a 400: "acknowledge" means *this is real* and
"approve" means *worth drafting*, and one control for both would let a
request skip its verdict — which is UI-11's entire concern.

**And the response says what the state change buys**, because "triaged"
on its own tells a steward nothing and the true answer is one a product
hides by accident: *nothing drafts by itself; you run the skill*. A
**Working the queue** panel names the three actors and the two lines
between them — the dashboard decides, the skill drafts, a human merges.

### Not built, and why

**`assign`.** §8 lists it; `ledger_issues` has no assignee column and the
pilot has one team, so the control would set state nothing reads. A
button that does nothing is worse than an absent one. Filed rather than
faked.

**`export enrichment batch` as a separate act.** For `enrichment_request`
that is the existing batch trigger. For gaps, the scoped work list *is*
`status = triaged` — the enrich skill's S1 priority-1 input via
`list_gaps` — so acknowledging already emits it, and a second mechanism
would be two names for one thing. What was missing was saying so, which
the panel now does.

### The runbook was wrong, separately and worse

Act 5 told the operator to open `~/Desktop/kb`, edit a contaminated doc
by hand, and open a PR. They objected, correctly:

> I don't want to open a PR and manually fix the KB, but the steward
> should do these KB updates via an AI agent with our skills and mcp.

That is the product's own design and the runbook contradicted it. A-1
proved the agent path live (STOP-2: the steward's session ran
`review-sync` and **prepared repair PR #36**); telling an operator to
hand-edit is telling them to do by hand the thing the platform exists to
do. Act 5 is rewritten around triage → run the skill → review the diff →
merge, with the three-actor table at the top, and no hand-editing
anywhere.

**A real gap the rewrite exposed:** the enrich skill's S1 work list is
ledger items, hot undocumented objects, and harvested docs. **A doc
marked contaminated by a past sync PR is in none of those**, so the 34 on
the pilot have no product entry point — repairing them today means
pointing a session at named files, which works and is not a surface.
Filed here; it belongs to **A-5**, whose gate is exactly "every
report-path L1 doc human-verified". Act 5b now says this plainly instead
of pretending the backlog is one click of work.

---

## B1-F4 — acknowledging meant one thing and the screen claimed another

**Found 2026-08-06 by the operator**, immediately after B1-F3's actions
shipped:

> what is the conditions in triage, when a capability_gap is
> acknowledged what happens to it. Does it go to enrich as well, or does
> it go to somewhere else, if the problem is not about context enrichment

It does not go to enrich, and the screen said it did.

### The fault

B1-F3's triage panel told every gap the same thing: *"acknowledging puts
this on the enrich skill's work list."* That is true for a `missing_doc`
and false for a `capability_gap`, which is the kind **four of the pilot's
six open issues** are:

```
capability_gap: supabase.reporting                      (×3)
capability_gap: supabase.reporting.v_user_signups_by_day
capability_gap: supabase.public
capability_gap: gsc.standard.impressions, ga4.standard.screen…
```

These are **SK-6 reporting-view handoffs**: the report skill hit a
request that needed a view, produced the DDL, and filed it with the DDL
in `detail`. Closing one means *running a DDL statement against the
customer's estate*, which **D-81 forbids the product from doing** — so no
skill can close it, and the object does not exist yet, so there is
nothing to document either.

`routed_to` did not save this. It says which *role* hears about an issue
(everything routes to `data-team` here); it does not say what act closes
it, and those are different questions.

### The distinction already existed and had no mechanism

The enrich skill's S1 reads *"fault-ledger items **assigned to
enrichment**"* — so the spec knew not every ledger item is enrichment
work. But **nothing ever assigned one**, and `list_gaps` filters by
status, kind and system only. A skill obeying S1 literally would take
every `triaged` item, including the four DDL handoffs, and draft
confident documentation for views nobody has created. That is the
gap-vs-guess failure arriving through the front door with a steward's
acknowledgement on it.

### Fixed

**A disposition per kind**, computed server-side and rendered on every
issue: `enrichable`, `actor`, `next_act`, `why`. Each row is derived from
something written — the §4 registry's own description of `capability_gap`
("includes SK-6 reporting-view handoffs — the DDL rides in `detail`"),
D-81 for who may run DDL, L-3 for guardrail thresholds being ops config,
CP-E3/KB-7 for who certifies a metric.

| Kind | Enrichable | Next act |
|---|---|---|
| `missing_doc`, `missing_entity`, `missing_join_path` | yes | write the doc |
| `uncertified_metric` | yes | draft it — a **human** certifies |
| `doc_schema_mismatch` | yes | re-ground against the current snapshot |
| `coverage_gap` | usually | normally a missing doc |
| **`capability_gap`** | **no** | **apply the DDL as the customer's DBA, re-sync, and only then is documenting it enrichment** |
| `guardrail_hit` | no | tune the guardrail or add a view — ops config |
| `abandoned_journey`, `benchmark_regression`, `result_disputed` | no | a person interprets the signal |
| `human_filed`, `other` | no | decide which of the above it is |

**The triage panel now says the right thing per kind**, in two shapes —
*"A skill can close this"* / *"This one needs a person"* — each with its
next act and the rule behind it. The **Working the queue** panel splits
the acknowledged list along the same line.

**And the enrich skill filters by kind**, with the table in its S1 and
the sentence that matters: *writing a doc about an object that does not
exist is the failure this table prevents* — a reporting-view handoff in
the queue looks exactly like a documentation gap, same shape, same
`triaged`.

### Tests

Two in `core/test/dashboard-b1.test.ts`: `ENRICHABLE_KINDS` excludes
`capability_gap` and `guardrail_hit` while including `missing_doc` and
`uncertified_metric`; `capability_gap`'s disposition is non-enrichable,
names DDL and the DBA, and cites D-81 in its `why` so nobody
re-litigates it. Plus a grep asserting the shipped skill carries the
filter.

### Flagged, not done

**The kind → next-act table is not in a spec.** Every row is derived from
one, but the mapping itself is new: §4 gives kinds, §7 gives kind→role
routing, and nothing gives kind→closing-act. It belongs in fault-ledger
§7 beside the routing table, and that is an amendment outside this
session's fence — proposed for the next task 0 with the other two.

**`list_gaps` does not expose the disposition.** The skill filters by
kind instead, which needs no change to an MCP tool's response shape.
Adding the field would be additive and probably right; it is a spec
surface, so it is flagged rather than taken.
