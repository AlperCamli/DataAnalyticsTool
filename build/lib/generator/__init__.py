"""Generator (task 1.5): snapshots in → machine-owned KB tree out.

Deterministic, idempotent, zero model calls, zero network (KB-8, S-8).
Public surface:

- ``generator.render.render_tree(snapshots, out_dir) -> RenderResult``
- ``python -m generator.render`` — the render CLI (task 1.6 runs this)
- ``generator.validate.validate_tree(kb_dir, snapshots=None) -> [Finding]``
- ``python -m generator.validate`` — CLI over the validation library

Spec basis: kb-repository-spec.md §3/§4/§7 (incl. the task-1.5 §4.1 and
§4.6 amendments), snapshot spec §4–§6; rulings DECISIONS.md D-33..D-37.
"""
