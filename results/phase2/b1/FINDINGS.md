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

---

# The knowledge-request loop (acts 6–11)

The findings below come from the second half of the runbook — the
D-101.5 loop — and from implementing the fixes D-116 authorized for them.
F5–F8 were found by the operator on 2026-08-06/07; F9–F11 were found while
fixing them, which is the pattern this checkpoint keeps producing.

## B1-F5 — the skill had nowhere to write

**Found 2026-08-06 by the operator, entering act 9.** The runbook says
*"in a Claude Code session with the steward setup bundle"*, the skill's
S3–S5 say *"both commands from the KB clone root"*, and **nothing told the
session where that clone is or to make one.** A steward following the page
into a fresh session reaches S3 with no working copy, S4 with nothing to
validate, and S5 with nothing to push.

*What "not provisioned" meant in practice, from this machine's own
evidence:* `~/cl-steward/kb` **did** exist before today — its reflog shows
an earlier session improvising a clone there and cutting KB PRs #40 and
#41 from it. That is the failure mode, not its absence: a path invented by
one session, written down nowhere, and unavailable to the next. D-116.7
makes the improvisation the convention.

The bundle made it worse than an omission. It carries `.mcp.json`,
`CLAUDE.md` and skills — and **not the address of the knowledge base it
serves**, which is on `/healthz` and nowhere a session reads. So a session
that worked out that it needed a clone could not have known what to clone.

### Fixed (D-116.7)

`~/cl-steward/kb`, self-provisioned by the skill: clone on first use from
the `kb_remote` the compiled bundle now names, `git pull --ff-only` after,
and **stop** on a dirty or diverged copy rather than resetting somebody's
uncommitted work. Four properties worth keeping:

- **Outside `~/Desktop` and `~/Documents`.** Those are OS-protected on
  macOS; a session reaching into them stalls on a consent dialog nobody is
  watching. The convention that the pilot's own KB lives at `~/Desktop/kb`
  is a *human's* convention and could not be the skill's.
- **One fixed path**, so the second session finds the clone rather than
  making a second one.
- **No credential in the bundle** (PA-1, still canary-asserted): git auth
  is the operator's own helper. Verified on this machine — a fresh clone
  pushes without extra configuration.
- **A reporter's bundle says none of this**, because a reporter has no
  working copy. Absent, not merely inapplicable.

*And the half the five-line proposal missed, which is the same defect:*
S4 asks for a local render + validate and **the library that does both was
not provisioned either**. It is vendored in the KB (`.github/vendor/*.whl`
— the same wheel KB CI installs), so S0 now builds a venv from the clone's
own wheel and refuses to draft if it cannot. A working copy that cannot
run its own self-check is half a fix.

**Test:** `core/test/compile.test.ts` — a steward bundle names the remote
and the path, a reporter's does not, an unconfigured core says so in
words, and the three stamp differently (PA-2).

## B1-F6 — the ledger deleted the numbers out of a person's sentence

**Found 2026-08-06/07 by the operator, on act 6, with the pilot's own
subscription prices.** Recorded in full at **DECISIONS D-115**, which this
file does not restate. The one-line shape:

> typed: "…we have a weekly subscription **4.99** dollars…"
> stored: "…we have a weekly subscription dollars…"

The steward then approved a request whose payload was gone, and **nobody
was told at any point.** Fixed by D-115 on the owner's ruling: LED-R2
narrows to *derived* text, authored text is stored verbatim and its value
patterns are **flagged to both humans**, nothing is refused and nothing is
rewritten.

**Live evidence that the fix landed, read out of the pilot ledger this
session** — the same issue holds both filings, which is the clearest
before/after this project has:

| Filed | Stored | Flags |
|---|---|---|
| 09:46:59 (pre-fix) | "…weekly subscription **dollars**. monthly subscription is **dollar** which is per week…" | `{}` |
| 10:46:15 (post-fix) | "…weekly subscription **4.99** dollars. monthly subscription is **14.99** dollar which is **3.75** per week, similarly annual subscription **99.99** dollars which is **1.92** dollars weekly." | `{number}` |

Per **D-116.2** the figures are confirmed correct by the owner and the
batched request stands — no deletion, no re-file — with the provenance
line `customer-confirmed, Alper, 2026-08-06` in anything drafted from it,
because the values were session-typed during the fix rather than by the
reporter whose identity the filing carries.

## B1-F7 — the act that put content in was the one act nobody audited

**Found 2026-08-07 while writing D-115.** D-114.1 widened the audit
contract to *"one row per governed act"* and enumerated the acts:
connection writes, verdicts, batches, returns. Every one of them
*changes* a request. **Filing one — the act that creates it — wrote no
audit row at all.**

That is not a bookkeeping complaint. When the pre-D-115 scrub deleted the
values out of a submission, the only record of the filing anywhere was the
ledger row whose content had just been damaged. No pre-scrub column, no
audit row, no copy: it is one of the reasons D-115 could state flatly that
the values were unrecoverable.

### Fixed (D-116.6)

Both inlets call the existing helper — `dashboard.ledger.file.human_filed`
and `dashboard.ledger.file.enrichment_request`, one row per filing, denied
included as everywhere else. `result_meta` carries
`{issue_id, occurrences, value_flags}`: **the fact of the act and what
detection found in it, never the text.** The words stay in the ledger
event under the ledger's own retention (L-8/LED-R6) — a second copy in the
audit table would be a privacy regression sold as an improvement. The MCP
inlet (`flag_gap`) already wrote its row per call and is unchanged.

**Test:** `core/test/dashboard-b1.test.ts` — filing a request leaves a row
under the filer's identity with a digested args field; the row points at
the issue; the request's own words are **not** in it; and the other inlet
gets the same treatment.

## B1-F8 — S1b told the session to use a token that cannot exist

**Found 2026-08-06 by the operator, entering act 9.** The skill's
queue-driven batch mode opened with:

```bash
curl -sS -H "authorization: Bearer $CL_TOKEN" \
  "$CL_CORE_URL/v1/dashboard/ledger?status=batched&kind=enrichment_request"
```

**A compiled bundle carries no credential** (PA-1, deliberately, asserted
by test), and the OAuth token the MCP client holds is not reachable from
the session's shell. So `$CL_TOKEN` is empty in exactly the sessions this
mode was written for, and the *first step of the mode* was unperformable
for anybody following the page as written. The mode had never been run
live; the fixture harness sets `CL_TOKEN` from the fixture IdP, which is
precisely why AS-18 could pass while the shipped instruction could not be
followed.

### Fixed (D-116.5) — the tool, not a token

MCP spec **§6.11.1** (additive, diff first): `list_gaps` filters
`approved|batched`, and every issue carries the filing behind it —
`filing: {by, at, description, proposal?, value_flags}`. One call, over
the channel the session is already authenticated on:

```
list_gaps(status: "batched", kind: "enrichment_request")
```

`by`/`at` are server-set (LED-R3), so the citation rule — *never re-typed
from the body of the request* — stops being a rule to remember and becomes
the shape of the data. S1b now says so in the imperative: *if `list_gaps`
is not in your tool list your profile does not grant it; say so and stop;
do not go looking for a token.*

**Verified live on the pilot** (post-rebuild, 2026-08-07): the batched
request comes back over MCP as `filed_by: reporter`, `at:
2026-08-07T10:46:15.807+00:00`, `value_flags: ['number']`, description
carrying **4.99 / 14.99 / 3.75 / 99.99 / 1.92** intact; the same call with
a reporter's token is `permission_denied` and returns no issue.
**Test:** MT-15 in `core/test/dashboard-ledger.test.ts`, plus the narrowed
LED-R7 assertion in `core/test/mcp-ledger.test.ts`.

## B1-F9 — the return half of the loop has no session-reachable inlet

**Found 2026-08-07 while fixing B1-F8, and *not* fixed.** Widening the
read closed one half of S1b. The third per-item outcome —
*undraftable → return it to the queue* — is a governed **write**:

```
POST /v1/dashboard/ledger/issues/<id>/return
```

and it is reachable by **nothing a session has**. There is no MCP tool for
it, and the dashboard has no control either: `GapTriage.tsx` *renders* a
return note (`issue.returned`) and offers no way to create one. So the
`batched → approved` transition D-114.12 built exists in the schema, in
the API, and in the §4 diagram — and can be performed only with a bearer
token, by an operator on a command line.

**Consequences, stated rather than smoothed over:**

- S1b's honesty rule is now *"hand it back in words"*: name the item in
  the PR body's returned section with what would unblock it, keep it out
  of the trailers, and **tell the steward it needs returning**. The skill
  is forbidden from saying it *returned* something it could not.
- **AS-18's clause moved.** The returned item's ledger state is no longer
  asserted of the skill; the harness performs that write. Recorded in the
  scenario table with the reason, so the softening is visible.

**Recommendation (one line each, needs authorization):** either a
steward-gated MCP `return_request(issue_id, note)` — smallest surface,
symmetric with `list_gaps`, and the loop closes entirely on one channel —
**or** a *Return to queue* control on a `batched` card in Gap Triage,
which is a new screen element and therefore a B-3 conversation. The MCP
tool is the recommendation.

## B1-F10 — build residue rode into the compiled bundle

**Found 2026-08-07 while adding `enrich/ci_gate.py`.** `readSkill` walked
every file beside `SKILL.md`, and the moment anything imports a
skill-local Python tool — including this repo's own pytest suite — a
`__pycache__` appears next to it. Observed directly: a steward bundle
compiled on this machine listed
`__pycache__/ci_gate.cpython-312.pyc` among the skill's files. The
`report` skill has had one since the Power BI work.

Two claims it falsified. The archive is documented as **deterministic**
(*"two downloads of one profile state are byte-identical"*) — a
machine-specific `.pyc` is not. And the **setup stamp** covers every skill
file, so running the test suite on a bundle-serving machine moved the
stamp and told every session its setup was stale, for a reason no operator
could see.

**Fixed:** `__pycache__`, `*.pyc` and dotfiles are excluded from the walk;
`core/test/compile.test.ts` asserts a scratch skill's `helper.py` ships and
its `__pycache__`, `.pyc` and `.DS_Store` do not. The scenario harness had
the right instinct already (`_prepare_workdir` ignores `__pycache__`),
which is how the bundle and the harness came to disagree.

## B1-F11 — the AS-18 command on the runbook page could not run

**Found 2026-08-07 running it.** The runbook's fixture command —
`vite-node test/fixture-deployment.ts` — exits immediately with *"Vitest
failed to access its internal state"*. The launcher's own comment in
`core/test/helpers.ts` explains why: importing `vitest` at module scope
crashes vite-node, so the import is gated on `CORE_TEST_DATABASE_URL`
being set, *"which the standalone launcher always supplies"*. The command
on the page does not supply it.

Consistent with the page's own admission that **neither AS-18 route had
been run by the session that wrote it**. It is a two-part fix and both
parts are on the page now: a postgres to point at, and the variable.

```bash
docker run -d --rm --name cl-as18-pg -e POSTGRES_PASSWORD=pg \
  -p 127.0.0.1:55432:5432 postgres:16
CORE_TEST_DATABASE_URL="postgres://postgres:pg@127.0.0.1:55432/postgres" \
  node_modules/.bin/vite-node test/fixture-deployment.ts -- --out /tmp/cl-fixture.json
```

**Result once it ran: AS-18 PASS, 9 of 9** — and the assertion that
matters most is invisible in the pass line. The scenario's tool trail is
`list_gaps → get_table → search_context → get_table …`: **no `curl`, no
`CL_TOKEN` in the environment, and no shell tool in the allow-list at
all.** The old version of this scenario handed the agent a bearer token
the product does not give anyone, which is exactly how it could pass while
B1-F8 sat in the shipped skill.

## B1-F12 — the doc was better than the rule allowed (owner ruling D-117)

**Found 2026-08-07 by the operator, reading act 9's pull request.** Not a
defect in the machinery — every part of the loop worked — but a rule the
product did not have and now does. Recorded here because the *shape* is
worth keeping: **a skill doing its best work can still be doing the wrong
work, and only the owner can say so.**

The skill grounded the pricing request in the customer's application
source: `plan-definitions.ts` for the catalogue, `pricing.test.ts` pinning
it, `billing.service.ts` for the lifetime behaviour. By the S2 ladder that
is excellent — app code beats a stated figure. The owner's ruling:

> "there is information from the CV Builder code base which we don't want
> because it is cheting for a test like this … the system should only add
> the requested information to the KB and maybe ask questions to get more
> detail about it but it shouldn't get information from other sources"

Two reasons, both real: a KB claim sourced from a private codebase is
**invisible to every drift mechanism this product has** — no snapshot
covers it, no contamination scan reaches it, nothing notices it going
stale — and a demonstration that reaches outside the estate is not a
demonstration of the estate.

And the second half, on the contaminated target:

> "if we can't update the public table's context since it is contaminated
> we can add this context later when it is drafted or verified"

The skill had put the prices on `v_subscriptions_by_plan` because
`public.subscriptions` was `contaminated` with `refuse-unless-override`,
and said so in the PR body as a deliberate second choice. The ruling makes
the right move **defer**, not redirect.

**Applied:** skill spec §6 S1b + the shipped skill — request-driven items
are grounded in the request and the estate's own facts, a question is a
legitimate outcome of a batch, and a blocked target waits for its doc.
**The cost is recorded once in D-117** and not argued: reading the app
found a **nine-cent disagreement** on the annual price (`$99.90` in the
app since 2026-06-28 against the `$99.99` in the request) that
request-only drafting would have written down silently. It survives
anyway, because `flag_gap` put it in the **ledger** —
`4c4ecb3d-fb41-4489-8d12-a13c0dd99a5f` — where out-of-estate findings
belong: **notice it, file it, do not document it.**
