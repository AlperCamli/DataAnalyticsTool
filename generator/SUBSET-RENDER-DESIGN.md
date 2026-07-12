# Design note — subset-scoped render (KB-C), not implemented in 1.5

Status: design only. Task 1.5 ships and tests **full render**; the CP-3
sync engine consumes this note when it builds the drift-run pipeline
(KB-C default: regenerate changed objects only). No code here is
implemented, deliberately — the diff-driven regeneration pipeline is
CP-3 scope.

## Why full render already converges

Under D-33 (Rule B), a file whose candidate render is unchanged modulo
`generated_at` is left byte-untouched. Full render is therefore already
byte-identical to an ideal incremental render: subset scoping is purely a
**cost** optimization (skip rendering unaffected files at all), never a
correctness mechanism. KB-8 (regenerate-from-same-snapshot → no-op diff)
stays the correctness backstop for both paths, exactly as KB-C states.

## Proposed API

```python
render_tree(snapshots, out_dir, *, only: set[Identity] | None = None)
# Identity = (kind, schema, name), per S-1 within one system's snapshot
```

`only=None` (the tested default) renders everything. With `only` given,
the renderer restricts writes **and pruning** to the affected-file
closure below.

## Affected-file closure

For each identity in `only`, within its system:

| Changed thing | Files in closure |
|---|---|
| SQL object | its `<object>.schema.md`; the `.schema.md` of every object whose Referenced-by section names it (reverse-FK neighbours — both directions of the FK edge); its schema's `index.md`; the system `index.md` |
| API object | its kind-group `<group>.schema.md` (roster + member section live in one file); the system `index.md` |
| added / removed object | as above, plus (SQL) the schema `index.md` gains/loses a row and an emptied schema dir's `index.md` is pruned; group files appear/disappear when a kind's roster becomes non-empty/empty |

Notes:

- Reverse-FK neighbours are required because Referenced-by is computed
  across the snapshot (D-36.2): dropping `orders` must regenerate
  `users.schema.md` even though `users` itself did not change. The
  closure is computable from the *new* snapshot plus the removed
  identities named by the diff — no old snapshot needed beyond what the
  diff already carries.
- Index files are in every closure because hot/stub counts and object
  rows are estate-shaped; they are cheap (one file per schema + one per
  system).
- The root `index.md`/`conventions.md` are never in any closure (K-7:
  bootstrapped once, human-owned).
- Pruning under `only` deletes exactly the machine files of removed
  identities (and emptied schema dirs), instead of the full
  set-difference sweep — this is what makes a scoped run safe to execute
  concurrently with human edits elsewhere in the tree.

## Contract with the sync engine

The drift run feeds `only` from the §7 diff classifications: `added` ∪
`removed` ∪ `changed (structural)` ∪ `changed (metadata-only)` identities.
`unchanged` objects stay out; Rule B would leave their files untouched
anyway (belt and braces). A template change ships as a generator version
bump and requires a full render (`only=None`) — the KB-C register item's
`regen-all` escape hatch.
