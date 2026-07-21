---
name: benchmark
description: Run one golden-suite journey under the benchmark profile and emit a machine-readable journey record for the scoring harness. Use only for benchmark runs; never for user-facing reporting.
---

# benchmark

You run **one journey per invocation**: take a golden-suite case, answer
it the way the `report` skill would, and emit a journey record. You do not
score yourself. The harness does that, deterministically, against
analyst-verified outputs.

State machine (skill spec §8): `load → journey → hand-off`

---

## What makes this skill different

**There is no user.** That single fact drives every deviation from
`report`:

- **No clarifying questions.** Resolve every ambiguity — window, grain,
  filter — with a stated, reasonable assumption, and log the assumption in
  the record's `notes`.
- **No confirmations.** CP-R1 (resolution confirmation) and CP-R4 (result
  confirmation) are **waived**. There is nobody to confirm with.

**The waiver is keyed to the `benchmark` profile, which the server
resolves — not to a session that feels automated.** Check the profile. If
you are not on it, you are in a user-facing session and the checkpoints
apply in full. This is ruling SP-2, and scenario AS-8 guards it.

Publishing is absent from the benchmark allowlist and is refused
server-side regardless of what you attempt. Adoption metrics exclude runs
tagged with this profile (SK-4), so benchmark traffic can never inflate
the pilot's "reports by non-analysts" number.

## R2 — fairness is the experiment

The journey prompt is **byte-identical across all three conditions**. The
only thing that varies is what context you can reach:

| Condition | What you have |
|---|---|
| `enriched-kb` | The full customer KB — entities, metrics, human docs, machine docs |
| `machine-kb` | Machine-rendered docs only; every purpose slot reads `—` |
| `no-kb` | No context tools at all. Discover live: `information_schema`, the GA4 metadata endpoint, GSC's fixed schema |

**Never tune your approach to the condition.** Do not try harder because
the KB is thin, and do not coast because it is rich. The whole point is to
measure what the context is worth, and an agent that compensates for a
poor condition destroys the measurement it exists to produce. Answer each
case the same way; let the conditions differ by themselves.

If you find yourself reasoning "this is the no-kb condition so I should…",
stop. That sentence has no valid ending.

## S1 — Load

Read the case from the golden suite: its request, the systems in scope,
and nothing else. **Do not read the case's `expected_objects` or its
verified SQL**, even if they are reachable — those are the answer key, and
a journey that has seen them measures nothing.

## S2 — Journey

Run `report`'s S1–S5 in benchmark mode: resolve → draft → validate →
execute. Same tools, same trust behaviors (K-TRUST still applies — a
contaminated doc is still refused, and the refusal is part of the
measurement), same hierarchical retrieval discipline.

Ground every object in something you actually saw this session. If you
cannot ground it, do not use it — say what is missing. **A journey that
honestly reports a gap is a valid data point; a journey that invents a
plausible table is a corrupt one**, and it corrupts the condition's score
in the direction that flatters us.

For a question spanning systems with no shared row-level key, reconcile by
magnitude — compare independently computed totals. Never fabricate a join
key.

Execution failures are data. Read the error, correct the query, retry
within the repair budget (at most 2, SK-7). The harness scores first-try
validate-pass rate, so an honest first attempt matters more than a
polished third.

## S3 — Hand-off (checkpoint CP-B1)

Emit the journey record — the harness's file-ingestion path reads it
unchanged. Fields the scorer depends on:

| Field | What it carries |
|---|---|
| `case_id`, `condition`, `rep` | The R8 key |
| `model_id`, `backend` | Run identity |
| `context_reads` | Every context ref resolved this session |
| `declared_objects` | Your self-reported object set — **recorded, never scored** (R4) |
| `drafts[]` | Each drafted request: `system`, `request`, `complete`, `final`, `validation`, `executed`, `outcome` |
| `tokens`, `tool_calls` | Cost accounting, informational |
| `notes` | Your logged assumptions |

Mark `final: true` on the drafts that constitute your answer — those are
what R4/R5 score. Mark `complete: true` on any draft that was a genuine,
executable attempt; an abandoned partial is `complete: false`, and the
distinction is what makes the first-try metric honest.

**CP-B1: you never score yourself.** Do not judge whether your answer was
right, do not compare against anything you think the expected result is,
and do not adjust a record to look better. The harness compares against
analyst-verified outputs; your job ends at reporting faithfully what
happened, including the parts that went badly.

---

## A note on cost (ruling D-77)

AI usage cost is the operating user's responsibility — in development and
in the product. Skills execute in the customer's own Claude Code under
their own licenses; the platform ships no model, no keys, and no billing
management, and it does not gate on spend. `cost_usd` is recorded in the
journey record when the runtime reports it, informational only. When it is
absent it stays absent — never coerced to zero, because "unknown" and
"free" are different facts.
