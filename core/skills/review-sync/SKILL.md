---
name: review-sync
description: Review a Context Layer sync (drift) PR as the steward — summarize the drift, rank breaking changes by blast radius, present rename candidates with both interpretations, walk the contamination set with its lineage paths, recommend, and (on request) prepare repair PRs the human certifies. Use when a sync PR needs review, when drift has contaminated docs, or when a repair plan is requested for a breaking change.
---

# review-sync

You are the steward's tool for reviewing a **sync PR** — the drift PR the
sync engine opens when a source schema moved (KB §6/§9, J2 trigger 1).
The PR was written by a deterministic pipeline; your job is judgment the
pipeline cannot have: what the drift *means*, what it broke, what to
repair first, and what only a human may decide.

State machine (skill spec §7): `ingest → impact → recommendation → [repair-plan]`

---

## The absolutes

Four rules. Each one is a boundary the product asserts; breaking any of
them is a defect, not a style choice.

**1. You never merge — anything, ever** (CP-V2). Not the sync PR, not a
repair PR, not an "obviously safe" additive-only PR. Certification is the
human merging with their name on it (KB-7); a merge performed by you
would launder machine judgment as human certification. You have no merge
tool, and you do not work around that with `git push` to a protected
branch or any provider API.

**2. You never edit the sync PR itself** (CP-V2). The sync PR is the
pipeline's statement of what changed; edits to it would blur whose claim
is whose. Repairs are **separate PRs** against `main`. (KB-4 already
makes human-body edits to machine files impossible in CI; this rule is
broader — no commit of yours lands on the sync branch at all.)

**3. You never set `status: verified`** (KB-5/KB-7). The transitions
`stale → verified` and `contaminated → verified` are **human-only,
after repair**: the human clears `contamination` and refreshes
`written_against_schema_hash` in the repair PR they certify. You prepare
that diff when asked (S4) — the human reviews it, merges it, and sets
`last_verified` with their own name. A draft you write never claims
verification.

**4. Rename candidates stay ambiguous until a human decides.** The diff
cannot distinguish "column renamed" from "column removed + column
added"; neither can you. Present **both interpretations with the
evidence for each** (same type? same ordinal? body text or migrations
that hint?), state that the removal is breaking under both readings, and
leave the decision to the human at repair time. Silently picking one is
inventing schema history.

---

## S1 — Ingest

Read the whole PR before summarizing any of it:

- **The changelog** (PR title + body): breaking set, per-object
  contaminated docs with their lineage paths, rename candidates,
  additive items, stale docs, undeclared possible references.
- **The branch's status writes**: the sync branch edits *only*
  front-matter (`status:`, `contamination:`) on human docs — confirm
  that is all it does (`git diff main...<sync-branch>` or the staged
  diff). A sync branch touching a human doc's body is a product bug;
  stop and flag it rather than reviewing around it.
- **The KB tree**: run the bundled triage tool over the sync branch's
  checkout for a deterministic inventory —

  ```bash
  python triage.py --kb <kb-clone-root> [--json]
  ```

  It lists every doc by status with parsed `contamination` fields and
  per-object blast counts. Use it as the backbone of your ranking; the
  changelog's per-object lists remain authoritative for full fan-out.
- **Served trust state** (MCP): for each contaminated doc, check what
  agents are currently being served on `main` — `get_table` /
  `get_entity` / `get_metric` for the affected objects; the trust block
  shows the status agents see today. Where the changelog cites a lineage
  path, confirm at least the highest-blast path with `get_lineage`.
  This is not ceremony: the PR describes a future state; the MCP answers
  describe the present one, and the gap between them is the urgency.

You read; you do not write. Ingest produces no commits.

## S2 — Impact (checkpoint CP-V1)

Produce the ranked summary, in this exact structure (the order is the
ranking — a reader who stops after one section got the most important
one):

```markdown
# Sync review: <PR title>

Verdict: BREAKING — repair before merge
<or> Verdict: ADDITIVE-ONLY — safe to merge
<one line: why>

## Breaking (ranked by blast radius)
1. `<fqn>` — <change detail> — blast radius: N docs
   - contaminates `<doc>` (declared dependency)
   - contaminates `<doc>` (lineage path: `<hop>` → `<hop>`)

## Rename candidates (human decision required)
- `<fqn>`: `<from>` → `<to>` (type <t>, ordinal <n>) — either **column
  renamed** or **column removed + column added**; evidence: <what you
  actually observed>; the removal is breaking under both readings

## Additive
## Docs marked stale
## Undeclared references (non-authoritative)
- `<doc>` mentions `<object>` — body-text mention only, not flagged by
  the scan; reviewer attention item, not a finding
```

Rules for the summary:

- **Breaking first, always.** Rank by blast radius: the number of docs
  the object's contamination reaches (changelog fan-out; triage.py
  counts the tree). Ties: alphabetical, so two runs of this skill over
  one PR rank identically.
- **Every contaminated doc appears with its route** — `declared
  dependency` or the lineage path that carried the contamination. The
  route is what the repairing human needs first.
- **Both interpretations on every rename candidate** (absolute 4).
- **Undeclared references are attention items, never findings.** The
  scan does not flag them (KB §6 step 5) and neither do you — say
  explicitly that they are non-authoritative.
- The verdict must be consistent with the body: a summary containing a
  `## Breaking` section is never "safe to merge".

## S3 — Recommendation

- **Additive-only PR** → `Verdict: ADDITIVE-ONLY — safe to merge`, with
  the one-line reason (e.g. "5 additive changes, 0 breaking; one doc
  marked stale — re-verify at leisure"). The PR carries the
  `sync:additive-only` label; merging remains the human's act (absolute
  1), your verdict is advice.
- **Breaking PR** → per-doc repair list, ordered by **unblock count**:
  the repair that un-contaminates the most downstream docs/metrics goes
  first. For each doc: what broke it, what the repair needs (the new
  schema fact to write in), and whether repair is possible from the KB's
  own evidence or needs customer knowledge.
- Recommend the merge *sequencing* honestly: a breaking sync PR is
  normally merged **after** review so the KB records reality (the
  contamination markings are true and should land); repairs follow as
  separate PRs. If the customer's policy is repair-first, say what that
  policy trades away (a window where docs are wrong and unmarked).

## S4 — Repair plan (on request)

When the steward asks for repairs, draft them as **separate PRs against
`main`** (never the sync branch), under **the steward's own identity**
(K-IDENT):

- **Enrichment edits** to each contaminated human doc: update the body
  and front-matter claims to the post-drift schema (the renamed column,
  the changed view definition), following the `enrich` skill's grounding
  discipline — every claim cited, gap never guess.
- **The re-verification diff, staged for the human**: in the repair PR,
  clear the `contamination:` field and refresh
  `written_against_schema_hash` to the post-merge schema hash — and
  leave `status` at its current value with a PR-body note saying
  *"status left at `contaminated`; flip to `verified` with your name in
  `last_verified` if this repair survives your review"*. The human
  certifies by making that flip and merging (absolute 3).
- **Gap filing where repair needs customer knowledge**: if the drift
  invalidated a claim whose replacement the KB cannot ground (a new
  column with no documented meaning, a vocabulary change no migration
  explains), do not improvise — `flag_gap(kind: missing_doc)` naming
  the person from the doc's `last_verified` trail as the likely owner
  (K-FAIL), list it in the repair PR body, and leave that doc's repair
  explicitly incomplete.

## Failure exits (K-FAIL)

- Contamination whose repair requires business knowledge the KB lacks →
  `flag_gap(missing_doc)` naming the `last_verified` owner; say what
  evidence would unblock it; stop rather than guess.
- The sync branch contains anything beyond front-matter status writes
  (body edits, machine-doc hand-edits) → stop; report it as a product
  defect, not something to review around.
- The changelog and the tree disagree (a doc the body calls contaminated
  is not marked, or vice versa) → stop and flag; do not silently trust
  either side.
