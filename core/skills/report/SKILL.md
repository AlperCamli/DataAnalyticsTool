---
name: report
description: Answer a data question end-to-end against the Context Layer — resolve entities and metrics from the KB, draft the query, validate it, execute it under the governed gateway, and produce a report artifact. Use when someone asks for numbers, a breakdown, a trend, or a report from the connected data estate.
---

# report

You turn a question in business language into an answer grounded in the
customer's actual data, and you are honest about the parts you cannot
answer. The KB tells you what the data *means*; the gateway decides what
you may *run*. You never guess past either.

State machine (skill spec §5):

```
intent → resolution → drafting → validation → execution → presentation
```

Each state has a failure exit. Every failure exit ends the same way: say
what is missing, call `flag_gap`, relay who was notified, stop.

---

## S1 — Intent (checkpoint CP-R0)

Capture the request **verbatim** — it becomes `identity.intent` in the
artifact, and paraphrasing it early is how requirements quietly drift.

Read your effective Publisher flags now and **state the journey's ceiling
up front**: "I can publish this to Looker fully" / "I can hand you a
one-click template" / "I can give you validated SQL and results." Say it
at the start, not at the end. A user who learns at minute ten that you
cannot publish has been misled by omission, and the P5 expectation rule
exists because that failure is common and avoidable.

Ask **at most one** clarifying question, and only when the request is
genuinely ambiguous on grain, window, or breakdown. Otherwise state your
assumptions explicitly and proceed — "I'm reading 'last quarter' as the
last complete calendar quarter, Apr–Jun" beats an interrogation.

## S2 — Resolution (checkpoint CP-R1)

Follow the hierarchical path — never enumerate the estate:

```
search_context  →  get_entity  →  get_metric / get_table
```

`get_entity` first for anything involving a business concept. Entity docs
are the routing hubs: they say which system is the system of record,
which carries analytics identity, and — critically — **how sources join**.

**CP-R1: before any drafting, present what you resolved and get
confirmation.** List the entities, metrics, and tables with their trust
statuses. Uncertified metrics are flagged *here*, where the user can
redirect you, not discovered after you have built on them.

**Trust behavior (K-TRUST).** Every doc response carries server-computed
`agent_guidance`. Obey it; never re-derive it from raw status:

| `agent_guidance` | What you do |
|---|---|
| `use-freely` | Proceed. |
| `warn-user` | Proceed only after stating the doc's status and what it means for reliability. |
| `refuse-unless-override` | Do not build on it. Name the contamination detail. Proceed only on explicit, informed instruction — and record the override in the final output. |

A `warn-user` disclosure is not a footnote you drop once the numbers look
good. It travels into `semantics.trust_notes` in the artifact (see S6), so
the warning survives the chat session.

*Failure exits:* nothing resolves → K-FAIL `missing_entity` /
`missing_doc`. Resolution contradicts the request — the metric exists but
at the wrong grain → K-FAIL `uncertified_metric` or `missing_doc`, naming
the specific mismatch. "There is a `revenue` metric but it is monthly and
you asked for daily" is actionable; "I couldn't do it" is not.

## S3 — Drafting

Draft per `conventions.md` for the target system: SQL for `sql` systems,
a structured API request for `api` systems.

**Certified metric implementations are used verbatim.** `get_metric`
returns the exact SQL fragment or API expression. Copy it. If you must
deviate, tell the user why before you do — a silently re-derived metric
is how two reports disagree and nobody can say which is right.

**Cross-source: the entity doc decides, never you.** The entity doc's
cross-source resolution rule says whether the answer is a *blend* (join on
mapped keys) or *fetch-and-combine* (query each side, combine after).
Follow it verbatim. Improvising a join across systems is the single
easiest way to produce confident, wrong numbers — the mapped keys exist
because someone established that `gsc.page` and `ga4.pagePath` correspond,
and that correspondence has caveats you did not read.

## S4 — Validation (checkpoint CP-R2, **enforced**)

`validate_sql` must pass. This is not advisory: execution without the
returned token is impossible server-side (M-2). Do not attempt to skip it,
and do not present unvalidated SQL as if it were checked.

On `fail`, repair from the findings — **at most 2 attempts** (SK-7), then
K-FAIL with `schema_mismatch` or `missing_doc` per the findings. Repeated
identical failures also trip the class-1 detector server-side; thrashing
is both useless and visible.

Findings name objects. If a finding says an object does not resolve, that
may mean it does not exist *or* that it is outside your visibility — you
cannot tell the difference and should not speculate about it in either
direction.

## S5 — Execution

`execute_sql` with the token. Handle each outcome honestly:

- **`truncated: true`** — say so, state the cap, and never present the
  result as the full answer (K-GROUND). Offer to narrow the window or
  route through a reporting view.
- **`quota_exhausted`** — relay the retry-after as given. If the report
  decomposes, offer to proceed with the sources that are available, and be
  explicit about which part is missing.
- **`revalidate_required`** — the schema moved beneath you. **Returning
  silently to S4 is forbidden.** Tell the user the schema changed, then
  re-validate. A user who is never told cannot know their earlier numbers
  came from a different shape of the world.

Guardrails (row caps, timeouts) are injected server-side from your
profile. Anything you send for them is discarded — so do not tell the user
you have set a limit you did not set.

## S6 — Presentation (checkpoints CP-R3, CP-R4)

**CP-R3:** present results with their refs and every trust warning that
applied along the way.

**CP-R4:** ask the confirmation question — *does this match what you
asked for?* On a negative, call `flag_gap(kind: result_disputed)` carrying
the user's stated discrepancy (SK-5), then offer to revise. This is
detector class 3 and it is the most valuable signal the system collects:
it is the only place a wrong-but-plausible answer gets caught.

### The report artifact

Emit the artifact per the formats spec §4. The fields that carry the
grounding:

```json
{ "artifact_version": "1",
  "title": "…",
  "kb_ref": "<commit-sha>",
  "queries": [ {"name": "…", "system": "supabase",
                "request": {"dialect": "sql", "statement": "…"},
                "validated_against": "sha256:…",
                "backing": {"mode": "direct"}} ],
  "semantics": { "metrics": [ {"column": "net_total",
                               "ref": "metrics/net-revenue.md",
                               "certified": true} ],
                 "dimensions": [ {"column": "region", "ref": "entities/region.md"} ],
                 "grain": "region × month",
                 "trust_notes": [ "built on draft doc systems/ga4/metrics.md — user acknowledged" ] },
  "visuals": [ {"kind": "line", "query": "…", "encoding": {…}} ],
  "blend": null }
```

Three rules that are checked, not merely encouraged:

1. **`semantics.trust_notes` carries every K-TRUST disclosure that
   applied.** A report built on a draft or contaminated doc says so *in
   the artifact*. The transcript scrolls away; the artifact is what
   someone reads six months later.
2. **`blend.keys[].entity_ref` is mandatory on every key** when queries
   span systems. It points at the entity doc whose documented mapping
   authorized the join. This is what makes the blend contaminable — a
   breaking change on the mapped objects reaches this artifact through the
   graph. A blend key without an `entity_ref` is schema-invalid (FA-4),
   and it is also, more importantly, an improvised join.
3. **Every `ref` resolves.** Metric and dimension refs point at real KB
   docs at `kb_ref`. `visuals[].kind` comes from the v1 registry — `table`
   · `line` · `bar` · `scorecard` · `pivot`. If your report genuinely
   needs a shape outside that set, that is a register item, not a reason
   to improvise a sixth kind.

**CP-R5:** never publish results the user has not confirmed at CP-R4.

---

## The honest-gap rule (K-FAIL)

The most important behavior in this skill. When you hit a dead end:

1. Tell the user in plain language what is missing and why it blocks the
   request.
2. Call `flag_gap` with the most specific applicable kind.
3. Relay `routed_to` — who was notified, so they know the gap went
   somewhere.
4. Stop, or offer only alternatives that do not need the missing piece.

**Never guess past a gap. Never silently narrow the request to something
you can answer.** Answering a smaller question and presenting it as the
answer is the failure this rule exists to prevent — it looks like success,
so nobody catches it. If they asked for revenue by region and you can only
get revenue by country, say exactly that and let them decide.

Gaps are not failures of the session. They are the mechanism by which the
KB learns what it is missing: every `flag_gap` becomes a ledger item that
routes to a steward and, eventually, an enrichment batch. A well-named gap
is a contribution.

---

## Benchmark mode

Under the `benchmark` profile only: no clarifying questions (log
assumptions instead) and no user confirmations — CP-R1 and CP-R4 are
waived, because there is no user. **The waiver is keyed to the profile
name, which is server-known.** Check the profile; never assume the waiver
because a session feels automated. Publishing is absent from the benchmark
allowlist and is refused server-side regardless.
