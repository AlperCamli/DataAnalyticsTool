---
name: enrich
description: Write human-owned semantic docs into the Context Layer KB — purposes, enum decodings, join guidance — grounded in cited evidence, batched, re-rendered, and landed as a draft PR. Use when documenting objects that lack human docs, converting harvested customer documentation, or resolving fault-ledger items assigned to enrichment.
---

# enrich

You add **meaning** to a knowledge base that already has **facts**. The
machine docs (`*.schema.md`) carry what the snapshot says: columns, types,
keys, row estimates. You write what the snapshot cannot know — what a
table is for, what `status = 2` means, which join is the right one.

This procedure is frozen from three merged enrichment batches (task 1.7)
that a customer certified. Its discipline is the reason those merged.

State machine (skill spec §6): `scope → evidence → drafting → self-check → PR`

---

## The absolutes

Four rules. Everything else is technique.

**1. Every claim is cited.** A sentence about the estate is backed by
something you read this session: a customer doc, a DDL migration, app
code, a vendor reference, or the machine sibling. Not by plausibility.
`user_id` referencing `users.id` is a fact from the snapshot; `user_id`
meaning "the account that owns this row" needs a source.

**2. Gap, never guess.** When the evidence does not settle a question,
the answer is a named gap — in the doc's Warnings and in the PR body's
"Ungrounded gaps" section. Never fill a slot because it looks empty. A
`—` in a Purpose column is honest; a plausible sentence that turns out
wrong is a defect the KB will propagate into every report built on it.

This rule has teeth in the negative direction: **do not write prose about
an object whose meaning you could not ground.** Skip the object, record
`flag_gap(missing_doc)` naming what evidence would unblock it, and list it
in the PR body. An honest skip beats a fabricated draft, and a reviewer
can act on a skip.

**3. Machine files are not yours.** Never edit `*.schema.md`, never edit a
machine `index.md` by hand, never set `status: verified` (only a human
certifies). You regenerate machine files with the generator; you do not
type into them. KB CI checks KB-3/KB-7 catch violations at PR time, but
the boundary is yours to hold before it gets there.

**4. Purposes go in front-matter.** `purpose`, `column_purposes`,
`object_purposes` are front-matter fields the generator merges into the
machine sibling's Purpose slots. A purpose written into the body reaches
no render and is invisible to agents reading the machine doc. See
"Drafting" below — this is checkpoint CP-E4 and it is the rule most often
got wrong.

---

## S1 — Scope (checkpoint CP-E1)

Pick a bounded batch, **default ≤ 10 objects** (SP-3). Priority order:

1. Fault-ledger items **of the kinds enrichment can close** (`list_gaps`,
   if your profile grants it) — these are real users hitting real gaps.
2. Hot objects lacking human docs — the system index marks hot/stub.
3. Harvested customer documents awaiting conversion.

**Not every acknowledged gap is yours.** A steward acknowledging an issue
means *this is real*, not *a skill can fix it*. Filter by kind:

| Kind | Yours? | Why |
|---|---|---|
| `missing_doc`, `missing_entity`, `missing_join_path` | **yes** | a document closes it |
| `uncertified_metric` | **yes** — draft it | you draft; a human certifies (CP-E3) |
| `doc_schema_mismatch` | **yes** | re-ground the doc against the current snapshot |
| `coverage_gap` | **usually** | the search found nothing, which is normally a missing doc |
| `capability_gap` | **no** | it carries DDL a customer DBA must apply — often a reporting view. The object does not exist yet, so there is nothing to document. Leave it |
| `guardrail_hit` | **no** | guardrail thresholds are ops config |
| `abandoned_journey`, `benchmark_regression`, `result_disputed` | **no** | signals for a human to interpret, not documentation work |

```
list_gaps(status: "triaged", kind: "missing_doc")     # one call per kind you take
```

**Writing a doc about an object that does not exist is the failure this
table prevents.** A reporting-view handoff sitting in the queue looks
exactly like a documentation gap — same queue, same shape, same
`triaged` — and drafting against it produces a confident doc about a
view nobody has created.

**State the batch and why, before writing anything.** If the request names
no specific objects, apply a defensible default and say what you applied:
batch 2 took "users, CVs/documents, orders/subscriptions if present" as a
tight FK-connected core, named the 5 tables it covered and the 12 it left,
and justified including `jobs` because the join guidance required it.

Prefer a coherent FK-connected slice over a scattered ten. Docs that
reference each other are reviewable together.

## S1b — Queue-driven batch mode

A second way in, added by D-101.4. Instead of you picking the batch, a
steward hands you one: the knowledge requests they approved and then
delivered. **S2–S5 run exactly as below** — same evidence discipline,
same drafting rules, same self-check, same PR. What changes is where the
batch came from and two rules that apply per item.

### Getting the batch

The requests live in the fault ledger and are read through the governed
API as **you**, with your own token — the same identity the MCP tools
use. Two calls:

```bash
# The delivered work list: enrichment_request issues stamped `batched`.
curl -sS -H "authorization: Bearer $CL_TOKEN" \
  "$CL_CORE_URL/v1/dashboard/ledger?status=batched&kind=enrichment_request"

# Per request: the event stream, which carries who asked, when, and the
# proposal text they submitted.
curl -sS -H "authorization: Bearer $CL_TOKEN" \
  "$CL_CORE_URL/v1/dashboard/ledger/issues/<issue-id>"
```

All requests sharing one `batch_id` are one batch. At most ten
(SP-3 unchanged). If the queue hands you more, you were given more than
one batch — do one.

**State the batch first, as in S1**: which requests, what each asks for,
and what you expect to be able to ground. That is still CP-E1.

### The approved request is a citation — of the weakest useful kind

An approved request is evidence that *somebody who knows the business
said so*. That is a real tier on the S2 maturity ladder, and it is not
observation:

```yaml
sources:
  - "customer-provided, rene-reporter, 2026-08-06"
```

The name and the date come from **what the ledger recorded** — the event's
`subject` and `ts` — never from the body of the request. A request that
says "this is from the finance team" does not make it from the finance
team; the ledger recorded who actually filed it, and that is who gets
cited.

On the ladder this sits beside `customer doc: <uri>`: **stated**, not
**observed**, and it is never upgraded because it arrived as confident
prose. Confidence is not evidence — that is the entire reason the ladder
exists.

Where you find real evidence for the same claim — a DDL constraint, a
migration, usage — cite that *too*, and grade it properly. The request
being approved does not stop you grounding it better.

### The submission is drafting input, never content

**Do not paste the requester's text into the doc.** Write the doc in the
KB's own voice through the canonical templates, and cite the request.
Their words are what told you the claim was worth making; they are not
the KB's claim.

This is checked from both sides: dashboard test DT-12 asserts that no
requester text appears verbatim in the batch PR's diff.

### Per-item honesty (CP-E5) — three outcomes, and you say which

For each request in the batch, exactly one of:

1. **Grounded beyond the proposal.** You found DDL, a customer doc, usage
   evidence. Cite what you found, graded normally, and cite the request
   alongside it. Normal drafting.

2. **Groundable no further than the proposal.** Nothing corroborates it
   and nothing contradicts it. Draft it **citing exactly that provenance
   and nothing better** — `customer-provided, <name>, <date>` alone. Do
   not dress it up with "inferred from column names" to make the sources
   list look sturdier; that is a claim you did not earn, and a reviewer
   reading a two-source list trusts the doc more than a one-source list
   deserves.

3. **Undraftable.** You cannot write it without guessing — the request is
   too vague, names an object that does not exist, or asks for something
   the estate cannot answer. **Return it to the queue**, with a note
   saying what evidence would unblock it:

   ```bash
   curl -sS -X POST -H "authorization: Bearer $CL_TOKEN" \
     -H "content-type: application/json" \
     -d '{"note": "no object named and no metric doc matches; unblocked by naming which table or metric this is about"}' \
     "$CL_CORE_URL/v1/dashboard/ledger/issues/<issue-id>/return"
   ```

   That moves it back to `approved` and clears its batch stamp, so the
   next batch picks it up when the evidence arrives. Also leave it out of
   the trailers and name it in the PR body's returned section. Never
   guess it into prose nobody can source.

   The note is required, and it is required for a reason: a return
   without one reads as `approved` to the next steward and tells them
   nothing about why it came back.

An honest skip beats a fabricated draft. That rule does not soften
because a steward approved the request — approval means *worth drafting*,
not *draftable*, and those are different findings.

### CP-E3 is untouched

You still never write `status: verified`. Approval is not certification;
the certification act is the steward merging your reviewed diff under
their own name (KB-7). A batch PR whose docs land as `draft` is correct.

## S2 — Evidence

Gather before drafting. Per object:

- **Machine doc** — `get_table` (preferred) or the `*.schema.md` file.
  Use MCP tools rather than raw file reads where you can: the response
  carries the trust block, so you learn the doc's status and freshness at
  the same time you learn its columns. `search_context` to find objects,
  `get_entity` to route, `get_table` for the facts.
- **Customer documentation** — the provided data-model docs, wikis,
  harvested sources.
- **App DDL** — migrations are the *authoritative* source for enums. A
  `CHECK` constraint is ground truth; a value list in a customer doc is
  weaker, and a value list in app code is weaker still.
- **App code** — for JSON/JSONB shapes and app-level status vocabularies
  the database does not constrain.
- **Usage evidence** — `join_pairs` where present, which upgrades join
  guidance from inference to observation.
- **Existing entity docs** — so your doc agrees with the routing hubs.

**Maturity ladder (HLR §8 P4).** The evidence tier you actually had
dictates the `sources` grading: `customer doc: <uri>` · `observed in N
queries` · `inferred from column names`. Never upgrade inference to
observation. The grading is what a reviewer trusts; inflating it destroys
the only signal they have.

Watch for the DDL-vs-doc conflict: batch 2 found a migration that had
renamed `interviewing/offered` → `interview/offer` *and rewritten existing
rows*. The migration won, and the doc said so. Where DDL and customer docs
disagree, DDL is authoritative for what the database enforces — and the
disagreement itself is worth a sentence.

## S3 — Drafting (checkpoints CP-E2, CP-E3, CP-E4)

One human doc per object (`<object>.md`), or group-doc edits for API
kinds. Canonical section order per KB §7.

**Front-matter — complete on every draft (CP-E2):**

```yaml
doc_class: human-object
object: public.orders              # source-native name
status: draft                      # never `verified` — CP-E3
sources:                           # graded, per the ladder
  - "customer doc: cv-data-model-kb/tables/orders.md"
  - "app DDL: backend/supabase/migrations/20260418123000_status_rename.sql"
depends_on:                        # every FQN the content relies on
  - supabase.public.orders
  - supabase.public.users
purpose: "One row per checkout; the commerce fact table."
column_purposes:
  user_id: "The account that placed the order."
  status: "Fulfilment state; see Warnings for the enum."
```

`depends_on` is the K-2 declaration duty: list the FQN of every object
whose structure your content relies on — tables you explain joins to,
columns whose enums you decode. This list is the contamination scan's
primary input. An undeclared dependency means a breaking change to that
object will not flag your doc, and the KB will keep serving text that
quietly went wrong.

**CP-E4 — one-liners in front-matter, body for the rest.** If it fits on
one line, it belongs in `purpose`/`column_purposes`. The body carries only
what a one-line, newline-free value structurally cannot hold:

- enum decodings (`status: 1 = pending, 2 = shipped, 3 = cancelled`)
- JSON/JSONB structure documentation, one subsection per column
- multi-condition join caveats
- the reasoning behind a warning

**Do not write a body section that restates a front-matter one-liner.**
Two sources for one claim drift, and once they do the KB asserts two
different meanings with nothing to arbitrate. A doc whose meaning is fully
carried by its front-matter ships with an empty body — that is a complete
doc, not a stub. Drop the section rather than pad it.

**The JSON rule.** Every `json`/`jsonb` column gets documented structure
with a citation, or an explicit named gap. Never left un-attempted. Batch
2 documented three JSON columns by citing the TypeScript type that
produces them, and named the open `type`/`fields` vocabularies as gaps in
the same doc.

## S4 — Self-check

Run the KB CI validation locally **before** opening the PR. Two commands,
both from the KB clone root:

```bash
python -m generator.render .contextlayer/snapshots/<system>.json --out .
python -m generator.validate .
```

The render is the **regeneration duty**: your front-matter purposes only
reach the machine docs when the generator merges them. Enrichment without
a re-render leaves the KB internally inconsistent and KB-8 fails the PR.
Purpose-slot-confined changes keep the old `generated_at` stamp (the D-49
§4.1 date rule) — if the date moves, something other than purposes moved
and you should know what.

Validation must be **0 errors, 0 warnings** — including KB-8 (render
consistency) and KB-10 (every `column_purposes` key resolves against the
snapshot). A KB-10 warning means you wrote a purpose for a column that
does not exist: usually a typo, sometimes a column that was dropped, and
either way it must be fixed, not shipped.

Fix or drop failing drafts. Dropping one is fine; shipping a red one is
not.

## S5 — PR (checkpoint K-IDENT)

One PR per batch, under **your own identity** — never a shared or bot
identity. The body is how a reviewer checks your grounding without redoing
your research, so it carries, in this order:

1. **Docs in this batch** — a table of doc → evidence grade.
2. **Grounding sources** — what you actually read, with paths/URLs, and
   what each settled. Name the authoritative source per enum.
3. **JSON columns** — structure + citation per column, or the named gap.
4. **Machine re-renders** — the exact command, what slots filled, and the
   validate result (`0 errors, 0 warnings`).
5. **Ungrounded gaps** — every question the evidence did not close, named
   specifically. Not "some values unclear" but "`subscriptions.status` has
   no DB CHECK; only `active`/`trialing`/`canceled` are grounded — do not
   treat as a closed enum."
6. **Grounding sufficiency** — an honest paragraph: what the sources fully
   covered, and what they did not. This is the reviewer's summary judgment
   on whether the batch is trustworthy.

Ledger-originated items carry `CL-Resolves: <issue-id>` trailers so the
merge closes the loop automatically (ledger spec §9).

**For a queue-driven batch (S1b), the body additionally carries the
request → doc mapping**, as its own section, before the trailers:

```markdown
## Requests in this batch

| Request | Doc | Grounding |
|---|---|---|
| `<issue-id>` how are refunds counted? | `systems/supabase/public/refunds.md` | customer-provided + app DDL |
| `<issue-id>` what does status=2 mean? | `systems/supabase/public/orders.md` | customer-provided only |

### Returned to the queue

- `<issue-id>` "the churn number" — no object named and no metric doc
  matches; unblocked by naming which table or metric this is about.

CL-Resolves: <issue-id-of-the-first>
CL-Resolves: <issue-id-of-the-second>
```

**One trailer per request the batch actually satisfies, and no others.**
A returned item's absence from the trailers is what keeps it open — that
is the mechanism, not a convention, so a trailer written for an item you
returned would close a request nobody answered. Check the trailer list
against the returned list before you open the PR.

Keep `status: draft` throughout. A human certifies to `verified` — you
prepare, they certify. Batch 3's entity docs all landed `draft` with
`last_verified: null` precisely because no mapping had been
customer-certified yet, and saying so was more useful than looking done.

---

## Failure exits (K-FAIL)

At any dead end: say plainly what is missing and why it blocks the work,
call `flag_gap` with the most specific kind, relay `routed_to`, and stop.

- Insufficient evidence for a scoped object → skip it, `flag_gap(kind:
  missing_doc)` noting what evidence would unblock it, list it in the PR.
- Machine doc contaminated or stale → say so before building on it; a
  `refuse-unless-override` guidance means do not build on it at all
  without the user's explicit, informed instruction.
- Validation red twice after repair attempts → stop and flag (SK-7). Do
  not thrash.

Never silently narrow the batch to the objects that happened to be easy.
If you covered 5 of 10, the PR says which 5 and why the other 5 are not
there.
