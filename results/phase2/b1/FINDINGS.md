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
