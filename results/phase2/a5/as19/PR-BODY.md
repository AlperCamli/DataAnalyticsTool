# Contamination triage — `triage.shop`, batch 1 of 1 (3 docs)

Work-list mode (S1c). The batch is the KB's own state, not a scoped pick:
every doc sync marked `status: contaminated`. Assembled with the skill's tool,

```bash
python3 .claude/skills/enrich/worklist.py --kb kb --batches
# contaminated: 3 doc(s) in kb
# batch 1 (3): systems/triage/shop/orders.md, systems/triage/shop/exports.md,
#              systems/triage/shop/imports.md
```

which put all three in one batch. That is the whole work list — no doc was
deferred to a later batch, and none was dropped for being awkward. Two causes,
one story: a `CHECK` constraint appearing on two sibling tables, and one removed
object. Two docs are repaired here; the third is deliberately left
`contaminated` and needs a decision, not a repair.

## Docs in this batch

| Doc | Class | What moved | What this PR changes |
|---|---|---|---|
| `systems/triage/shop/exports.md` | **confirms-prose** | `CHECK (status IN ('processing','completed','failed'))` and `CHECK (format IN ('pdf','csv'))` — the doc's enum decoding already lists exactly these, in both cases | front-matter only: `status: contaminated → draft`, `contamination: null`, hash refreshed to `sha256:11f0e6ca…6e5f`. **Body untouched.** |
| `systems/triage/shop/imports.md` | **needs-re-grounding** | `CHECK (status IN (…))` admits **six** values; the doc said four were "the whole vocabulary" and that nothing sits between `parsed` and the data being live | enum decoding rewritten from the constraint, the contradiction recorded in Warnings, `reviewed`/`converted` named as an open gap, DDL cited; front-matter marker cleared and hash refreshed to `sha256:22a1b7db…7a6e` |
| `systems/triage/shop/orders.md` | **depends-on-missing-object** | `depends_on` names `triage.shop.legacy_carts`, absent from the snapshot (`object_removed`) | **nothing — left `contaminated`**, decision needed (drop the dependency and the join guidance, or restore the object). See below. |

### Why `exports.md` is a front-matter-only diff

Because the class says so, and the diff is the evidence of it. The constraint
that contaminated this doc turned out to say exactly what the doc already said,
value for value, on both columns. There was nothing to re-ground, so nothing in
the body moved — not one word. Reviewing this doc is reading three front-matter
lines and agreeing that the prose still holds.

One thing I deliberately did **not** do: `exports.md` carries
`sources: ["customer doc: …", "inferred from column names"]`, and the new
`CHECK` constraint would be a stronger citation for the enum than either. Adding
it would be an improvement — and it would also be drafting under cover of a
repair, which is exactly what makes a twenty-doc "no-change" batch unreviewable.
It is left for a batch that says it is doing that. Worth knowing while you read:
the enum in that doc is now corroborated by ground truth, and its `sources` list
understates it.

### `orders.md` — left contaminated, on purpose

`triage.shop.legacy_carts` is gone from the snapshot, and the doc's Join
guidance is *about* reading pre-cutover baskets through it. Deleting the
`depends_on` line would turn the doc green in one keystroke and would remove the
only tripwire pointing at the fact that this join no longer has a table to land
on. That is not a repair.

The decision is a person's, and it is one of two:

- **the object is gone for good** — then the Join guidance section goes with it,
  and someone should say what pre-cutover orders read through now (or that they
  cannot be read at all, which reports need to know); or
- **the object is coming back** (renamed, moved schema, or dropped from the
  snapshot by mistake) — then the doc is fine and the snapshot is the thing to
  fix.

Nothing I read settles which. It needs whoever ran the cutover.

**Not filed as a `flag_gap`.** This run was scoped to repairing the docs and
writing this body, so this section is the only record of it — if you want it in
the fault ledger too, it still needs filing, and I have not done it.

## Grounding sources

Everything below was read this session. Nothing else was consulted — no
application source, no repository outside this working copy.

| Source | What it settled |
|---|---|
| `kb/.contextlayer/snapshots/triage.json` (system `triage`, `source_mode: live`, captured 2026-08-06) | the authoritative `CHECK` constraints for all three tables; the current `schema_hash` per object; the absence of `shop.legacy_carts`; every column name and type |
| `worklist.py --kb kb --json` | per-doc contamination marker, cause object, changed columns, dependency resolution, prior-certification status |
| `kb/systems/triage/shop/{exports,imports,orders}.md` | what each doc actually claims, which is what a marker cannot tell you |

**Authoritative source per enum:**

- `shop.exports.status` and `shop.exports.format` — the DB `CHECK` constraints.
  Both agree with the customer doc the file already cites; no conflict.
- `shop.imports.status` — the DB `CHECK` constraint, which **outranks** the
  customer doc `shop-data-model/imports.md` where they disagree, and they do.
  The constraint is what the database enforces; the customer doc described a
  four-state lifecycle that the database has since outgrown. Both are cited in
  the repaired doc, and the disagreement is written down rather than smoothed
  over — the next reader would otherwise be left wondering which was wrong.

The constraint is cited as `app DDL` grade (a DB `CHECK` is ground truth) and
names the artifact it was read from, so it can be checked. No migration file
was available in this working copy, so no migration path is claimed.

## JSON columns

**None in this batch.** All eleven columns across the three objects were checked
against the snapshot's declared types: `uuid`, `text`, `integer`, `timestamptz`.
No `json` or `jsonb` column exists, so the JSON rule has nothing to bite on
here — this is a confirmed absence, not an unattempted check.

## Machine re-renders

**Not run, and this batch is therefore not validated. Read this section before
you trust the two repaired docs.**

S4 asks for a re-render and a `0 errors, 0 warnings` validation using the wheel
vendored in the KB clone. Neither is possible here, for two reasons that are
properties of this KB rather than of the repair:

- **`kb/.github/vendor/` does not exist.** There is no vendored wheel, so the
  venv S0 provisions cannot be built and the validation library KB CI would
  judge this diff by cannot be run.
- **This KB has no machine layer.** No `*.schema.md`, no `index.md` — the whole
  KB is a snapshot and three human docs. There are no Purpose slots for
  front-matter to merge into, so a render has nothing to fill; running one would
  *create* a machine layer this KB has never had, which is well outside a triage
  repair's scope.

What I ran instead, and exactly what came back:

```
$ .venv/bin/python -m generator.validate <kb>          # platform repo's validator, read-only
<snapshot>: [provenance] invalid snapshot for 'triage': <root>: 'system_class' is a required property
1 error, 0 warnings
```

That error is about **the snapshot, not the docs** — it is a reduced fixture
that does not satisfy the v1.0 snapshot schema, so the validator stops at
provenance and never reaches the documents. It is pre-existing and untouched by
this batch (the snapshot was read, never written).

So I verified by hand what the validator would have covered, against the
snapshot:

- **Front-matter parses** on all three docs; `status` and `contamination` are
  what the table above claims.
- **Both refreshed hashes match the snapshot's `schema_hash`** for their object,
  exactly: `exports` → `sha256:11f0e6ca…6e5f`, `imports` → `sha256:22a1b7db…7a6e`.
  `orders.md`'s hash was already current and was not touched.
- **KB-10 equivalent:** every `column_purposes` key on all three docs resolves
  to a real column of its object. 7 of 7.
- **`depends_on` resolution:** 4 of 5 resolve. The one that does not is
  `orders.md → triage.shop.legacy_carts`, which is the point of the third row
  and is left in place on purpose.
- **The `exports.md` body is byte-identical** to its pre-repair state; both
  edits were confined to front-matter lines.

Hand-checking is weaker than the CI gate and does not substitute for it. If this
KB is meant to be CI-validated, it needs `.github/vendor/` and a snapshot
carrying `system_class` before any triage batch can honestly claim green.

## Ungrounded gaps

- **`shop.imports.status`: `reviewed` and `converted` are undecoded.** The
  `CHECK` constraint proves both are legal values; nothing read this session
  says what either means or where it falls in the lifecycle. Their names suggest
  readings, and names are not evidence — the repaired doc names them as a gap
  rather than decoding them. Unblocked by the migration that added them, or by
  the import worker's own code. **Do not treat the four-state lifecycle in the
  customer doc as complete**, and do not treat `parsed` as terminal.
- **`shop.imports.status` transition order is grounded only for four values.**
  The `uploaded → parsing → parsed` / `failed` ordering comes from the customer
  doc; the constraint proves membership, not sequence, and says nothing about
  where the two new states sit.
- **`triage.shop.legacy_carts`: gone, and nobody has said why.** Whether it was
  dropped, renamed, or is missing from the snapshot in error is unsettled, and
  it determines whether `orders.md`'s Join guidance is stale or correct. See the
  `orders.md` section above.
- **How pre-cutover orders are read now** — open, and downstream of that
  decision. Any report joining orders to baskets across the cutover is affected.
- **`shop.exports.status = 'completed'` without a file.** The doc calls this "a
  bug, not a state." That claim predates this batch, is not sourced in the doc,
  and nothing here confirms or refutes it — flagged as inherited, not
  introduced.

## Grounding sufficiency

**Honest read: two of three docs are properly settled; the third is correctly
refused; the batch is unvalidated.**

The evidence fully covered the two repairs. `CHECK` constraints are the
strongest source there is for a value set — they are what the database actually
enforces — and for `exports.md` they confirmed the existing prose exactly, while
for `imports.md` they falsified it precisely enough to rewrite from. Neither
repair rests on inference. The snapshot is `source_mode: live` and one day old
relative to this run, so it is describing the estate as it is, not as it was.

What the evidence did **not** cover is meaning, in two places, and both are
named above rather than papered over. The constraint gave me `reviewed` and
`converted` as legal values and nothing more; decoding them from their names
would have produced a fluent, plausible, unsourced paragraph, which is the
failure this procedure exists to prevent. Likewise `legacy_carts`: the snapshot
tells me it is absent and cannot tell me whether that is intended.

Two limits on how far to trust this batch:

1. **It is not CI-validated** — see Machine re-renders. The hand checks are real
   but narrower than the gate.
2. **The `imports.md` rewrite is grounded in the constraint, not in the
   business.** It is now accurate about what the database permits and honest
   about what it does not know. A reader who knows the import pipeline should
   look at it, because the two undecoded states are exactly the kind of thing
   they would recognise on sight.

`exports.md` I would certify on this evidence. `imports.md` is accurate but
knowingly incomplete, and the incompleteness is in the doc where a reader will
see it. `orders.md` should stay contaminated until someone answers the cutover
question.

### Certification — yours, on this branch, before merge

For each doc you accept, set in its front-matter:

    status: verified
    last_verified: "2026-08-07 (your-name)"

Commit that under your own identity. Docs you are not ready to certify: leave
them `draft` and say why in the merge comment — a draft repair is still better
than a contaminated one, and it does not pretend.

`orders.md` is **not** a candidate: it is still `contaminated` and must stay
that way until the `legacy_carts` decision is made. Certifying it would assert
that a join whose table does not exist is verified knowledge.

No `CL-Resolves` trailers: this batch came from the KB's own contamination
state, not from the fault ledger, so there is no issue for a merge to close.
