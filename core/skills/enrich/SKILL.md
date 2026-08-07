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

## S0 — Your working copy (do this first)

You write documents into a git clone of the KB and open a pull request
from it. **You provision that clone yourself**, at one fixed path:

```bash
# The remote is named in your CLAUDE.md ("Knowledge base"). It is also
# available from the core: curl -s $CL_CORE_URL/healthz | grep kb_remote
KB=~/cl-steward/kb
[ -d "$KB/.git" ] || git clone "$KB_REMOTE" "$KB"
git -C "$KB" checkout main && git -C "$KB" pull --ff-only
git -C "$KB" status --porcelain          # must be empty before you start
```

Four things about this, each of which has cost somebody an hour:

- **`~/cl-steward/kb`, not somewhere under `~/Desktop` or `~/Documents`.**
  Those directories are OS-protected on macOS: a session reaching into
  them stalls on a consent dialog nobody is watching. One fixed path also
  means the next session finds the clone rather than making a second one.
- **Authentication is yours, not the bundle's.** Your setup bundle carries
  no credential and never will (PA-1). The clone uses your own git
  credential helper — the same one your `git push` already uses. If the
  clone asks for a password, that is a git configuration problem to fix
  in the open, not something to route around.
- **A dirty or diverged working copy stops you.** Say what is uncommitted
  and let the person decide. Never `reset --hard` somebody's work to make
  a batch run.
- **Pull before every batch.** Drafting against a stale main is how you
  produce a PR whose re-render conflicts with a merge from yesterday.

**And the toolchain, which lives in the clone too.** S4 asks you to
re-render and validate before opening the PR, and the library that does
both is vendored in the KB itself — the same wheel KB CI installs, so
what you run locally is what the pull request will be judged by:

```bash
python3 -m venv "$KB/.venv" && "$KB/.venv/bin/pip" -q install "$KB"/.github/vendor/*.whl
"$KB/.venv/bin/python" -m generator.validate "$KB"      # sanity: 0 errors before you start
```

If `.github/vendor/` is missing or its wheel will not install, **say so
and stop before drafting**: a batch you cannot validate is a batch you
cannot honestly open a PR for, and discovering that after writing ten
documents wastes the run.

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

**One call, over the channel you are already authenticated on:**

```
list_gaps(status: "batched", kind: "enrichment_request")
```

Each issue comes back with the filing behind it:

```
filing: { by, at, description, proposal, value_flags }
```

- `by` and `at` are **what the ledger recorded** — the server set them at
  filing time and no client can supply them. They are the name and date
  your citation uses.
- `description` and `proposal` are the person's own words, stored as they
  wrote them.
- `value_flags` says what detection found in that submission (`number`,
  `email`, `quoted`, `truncated`, …). It is a **warning, not a verdict**:
  the values are all there. Where a flag says `truncated`, the submission
  hit a length bound — say so in the PR body rather than drafting from
  half a sentence as if it were whole.

All requests sharing one `batch_id` are one batch. At most ten
(SP-3 unchanged). If the queue hands you more, you were given more than
one batch — do one.

**There is no other way in, and this is deliberate.** An earlier version
of this page told you to `curl` the dashboard's ledger API with a bearer
token. **You do not have one**: your setup bundle carries no credential,
and the token your MCP connection uses is held by the client, not by your
shell. If `list_gaps` is not in your tool list, your profile does not
grant it — say so and stop. Do not go looking for a token; there isn't
one to find, and inventing one is a governance bypass rather than a
workaround.

**State the batch first, as in S1**: which requests, what each asks for,
and what you expect to be able to ground. That is still CP-E1.

### Where the evidence comes from in this mode — and where it does not

**Read the request and the estate. Nothing else.** This is the one place
the skill's usual instinct is wrong, so it is stated before the drafting
rules rather than after them (owner ruling D-117):

| Allowed | Not allowed |
|---|---|
| the request's own words (`filing.description`, `filing.proposal`) | the customer's **application source**, or any repository |
| the snapshot and machine sibling (`get_table`) | files elsewhere on the machine |
| existing KB docs, entity docs, conventions | searching for a second source to corroborate or contradict |

S2's evidence list below is for batches **you** scoped, where tracking a
migration down is the whole job. A request-driven item is different: the
person asking *is* the source, and a doc grounded in something the estate
cannot see is a claim no drift check will ever re-examine.

**If the request is not specific enough to draft from, ask.** If there is a
human in this session, ask them — plainly, in one question. If there is
not, hand the item back with the question as its note. **A question is a
legitimate outcome of a batch.** Guessing is not, and neither is going
looking.

### If the doc that should carry it cannot be written, wait

A request usually points at one obvious doc. When that doc is
**`contaminated`** (or otherwise refuses to be built on), **do not put the
content somewhere else that happens to be writable.** Redirecting looks
helpful and quietly splits the estate's meaning across two docs, one of
which nobody asked about.

Return it instead, naming the doc it is waiting for:

```
return_request(
  issue_id: "<issue-id>",
  note: "belongs on systems/supabase/public/subscriptions.md, which is
         status: contaminated (refuse-unless-override). Waiting for that
         doc to be repaired to draft; the content goes in then."
)
```

The request stays open, which is the truth: nobody has answered it yet.
`return_request` moves it back to the approved worklist — it does **not**
resolve it, and it does not reject it.

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

1. **Draftable from the request against the estate's own facts.** The
   request says what a column means or what a value is, the snapshot
   confirms the column exists and the machine sibling agrees, and the doc
   can be written. This is the normal case in this mode, and the citation
   is the request — plus the estate's own facts where they carry part of
   the claim. **Not** a hunt for a stronger source: see the scope rule
   above.

2. **Groundable no further than the proposal.** Which, in this mode, is
   most of the time and is **fine**. Draft it **citing exactly that
   provenance and nothing better** — `customer-provided, <name>, <date>`
   alone. Do
   not dress it up with "inferred from column names" to make the sources
   list look sturdier; that is a claim you did not earn, and a reviewer
   reading a two-source list trusts the doc more than a one-source list
   deserves.

3. **Undraftable — or blocked.** You cannot write it without guessing (the
   request is too vague, names an object that does not exist, asks
   something the estate cannot answer), **or** the doc it belongs on
   refuses to be written (contaminated). **Return it**, explicitly, and
   in all three places:

   ```
   return_request(issue_id: "<issue-id>", note: "<what would unblock it>")
   ```

   - the **note** says *what evidence would unblock it*, specifically
     enough that the person who asked can supply it. It is required, and
     for a reason: a request that comes back without one reads as
     `approved` to the next steward and tells them nothing about why;
   - name it in the PR body's **Returned to the queue** section too. The
     ledger note is for the next steward; the PR section is for the
     reviewer reading this diff. Neither substitutes for the other — and
     the PR body is the one that is not scrubbed, so if the tool tells you
     `note_altered`, the full version goes there;
   - leave it out of the `CL-Resolves` trailers. That absence is what
     keeps the request open.

   Never guess it into prose nobody can source.

   **Match the claim to the act.** With `return_request` in your tool
   list, you moved the row and *"returned to the queue"* is true. **If it
   is not in your tool list**, your profile does not grant it — then say
   *"handed back"*, name the issue id and the note to the steward in
   words, and let them move it. Claiming a state change you did not make
   is the same class of error as claiming a doc entered the KB when you
   only opened a PR. Do not go looking for another way to perform the
   write; there isn't one, for the same reason there is no token to find.

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
both from the KB clone root, using the venv S0 provisioned from the
clone's own vendored wheel:

```bash
.venv/bin/python -m generator.render .contextlayer/snapshots/<system>.json --out .
.venv/bin/python -m generator.validate .
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

### Handed back — needs returning to the queue

- `<issue-id>` "the churn number" — no object named and no metric doc
  matches; unblocked by naming which table or metric this is about.
  **Still `batched`: the steward has to return it** (no session-side
  inlet — see the honesty rule above).

CL-Resolves: <issue-id-of-the-first>
CL-Resolves: <issue-id-of-the-second>
```

### Then check that CI actually reported

**A pull request with no check is not a pull request that passed.** After
opening it, from the working copy:

```bash
python3 .claude/skills/enrich/ci_gate.py <pr-number>
```

It waits for a check run on the PR's head commit, and if none appears it
causes one (close + reopen — the same lever a person would pull) and
waits again. Read its exit code before you say a word about the PR being
ready:

| Exit | Means | What you say |
|---|---|---|
| 0 | a check ran and passed | the PR is ready to review, with the run URL |
| 1 | a check ran and failed | the diff is wrong; fix it, do not hand it over |
| 2 | **no check ever reported** | say exactly that, and that it must not be merged on this evidence |

Exit 2 is not a failure of your work and must not be reported as one —
nor as a success. It happened on this project's own KB (PR #40, D-116.4):
the run was simply absent at open time, and the absence looked precisely
like a pass. Relay the run URL when there is one; a bare "CI is green" is
a claim the reader cannot check.

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
