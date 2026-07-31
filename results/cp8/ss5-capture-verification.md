# SS-5 capture — verification against the example estate

Ruling **D-96.3d**. Run 2026-07-31, after the connector/registry/generator
change landed. Everything below is a command that was run and an output
that was read, not a design claim.

## Conformance, container-backed

`.venv/bin/python -m pytest tests/test_postgres_connector.py` →
**25 passed**, including the task-1.2 exit criteria re-run against the
changed connector:

| Test | Result |
|---|---|
| **C-1** — emitted snapshots validate (`check_hashes=True`) | pass, ddl-file + live |
| **C-2** — two ddl-file runs byte-identical | pass |
| **C-2** — two live runs byte-identical | pass |
| **C-3** — ddl-file vs live canonical bodies identical | pass |
| **C-4** — stored hashes reproducible | pass |
| **C-8** — stats carry only registered fields | pass |

Five new SS-5 tests, all green:

- `checks` captured verbatim and sorted — `CHECK (total_cents >= 0)`.
- omitted where the kind has none: absent (not `[]`) on a table without
  CHECKs, and never present on `view` / `materialized_view`.
- NOT NULL is not a check — carried once, as `columns[].nullable`.
- **hash-included, executed**: widening `orders_total_cents_check` moves
  **exactly one** schema hash, the table's. This is the polarity
  argument run rather than asserted — it is what lets a widened
  constraint reach the contamination scan and mark the doc that
  explains it.
- multiple checks sort lexicographically, with constraint names
  (`aa_`/`zz_`) deliberately anti-correlated with the expression text so
  a sort-by-name regression fails here.

Full suite: **732 passed / 14 skipped**.

## C-1 and C-2 on the live example estate

Two consecutive live pulls through the product path (job API →
runner → delivery gate), using the registered `supabase` connection:

| Snapshot | `canonical_body_sha256` | Objects |
|---|---|---|
| `01KYW11JPQ…` 12:05:35Z | `bef2fa14c60a3520…` | 38 |
| `01KYW11YNC…` 12:05:47Z | `bef2fa14c60a3520…` | 38 |

**Byte-identical — C-2 holds on the example estate with `checks` in the
body.** Both jobs `succeeded`, which means both passed the delivery
gate's validation (C-1). *C-3 is not re-verifiable here and is not
claimed:* mode invariance needs the same source state through both
`ddl-file` and `live`, and a hosted Supabase offers only `live`. C-3's
evidence is the container suite above.

Note the estate itself has moved since the last accepted snapshot:
**34 → 38 objects**, so the pending drift is not only this capture.

## What the capture actually found

**15 of 17 tables** carry CHECK constraints — roughly 40 constraints the
snapshot boundary has been dropping since task 1.2. Most are enum-like
vocabularies (`status`, `flow_type`, `format`, `locale`,
`progress_stage`, `change_source`, `file_type`) — exactly the facts a
report's semantics rest on.

**And the finding that started SS-5, closing on itself.** `public.ai_runs`
now carries:

```
CHECK (status = ANY (ARRAY['pending'::text, 'completed'::text, 'failed'::text]))
CHECK (status = 'pending'::text AND completed_at IS NULL
       OR (status = ANY (ARRAY['completed'::text, 'failed'::text]))
          AND completed_at IS NOT NULL)
```

`deploy/reporting-views.sql` and D-81's rationale both said this column
was "free text with no CHECK constraint" whose "vocabulary is
ungrounded". Both constraints existed the whole time. A careful session
read our boundary's silence as the source's permissiveness (D-86.3b) —
and a reader working only from the KB would have kept doing so. The
rendered doc now shows the constraint; nothing has to be inferred.

## The KB diff this produces (rendered preview, not yet a PR)

Rendering the new snapshot over `origin/main`:

```
19 files changed, 145 insertions(+), 56 deletions(-)
```

`systems/supabase/public/ai_runs.schema.md` gains a **Check
constraints** section with the four constraints above, alongside the
expected `schema_hash` and `row_estimate` movement.

## STOP — and a required ordering

**The drift PR was deliberately NOT opened, because it would arrive
red.** This is an ordering constraint, not a defect:

1. The 0.6.0 wheel carry deletes `contextlayer_snapshot-0.5.0-…whl` and
   adds the 0.6.0 file (sync spec §10).
2. `origin/main`'s `kb-ci.yml` still hardcodes the **0.5.0** filename.
3. Since R-6(b), the carry no longer edits workflow files — that is the
   entire point of the change.

So a drift PR opened against today's `main` would install a wheel that
its own branch deleted, and fail loudly. **Merging [PR #32](https://github.com/AlperCamli/DataAnalyticsTool/pull/32)
first removes the collision** — after it, `kb-ci.yml` reads the wheel
filename from the manifest the carry rewrites.

**Sequence for the operator:**

```bash
# 1. Merge the KB PRs (R2). #32 must precede the drift run; #30 and #31
#    are independent and can merge in any order.
#      #32  ci: wheel pin → VENDOR-MANIFEST.yaml     (CI green)
#      #30  sync: F-4 report nodes → lineage/graph.json (CI green)
#      #31  docs(index): public-by-choice note        (CI green)

# 2. Then trigger the drift run. It leads with the 0.6.0 wheel commit
#    and carries the re-rendered machine docs in the same PR, so the
#    PR's own CI validates with the wheel that will govern after merge.
docker compose exec core node dist/cli.js sync now supabase

# 3. Review the resulting PR as R2. Expect: wheel commit first, then a
#    content commit carrying Check-constraints sections across ~15
#    tables plus the estate's own 34 → 38 object drift.
```

The drift PR is R2's to review and merge. The session opens PRs; it
never merges (SO-B).
