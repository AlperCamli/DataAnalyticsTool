"""Canonical graph serialization and the §3.1 byte-no-op write rule.

Serialization (D-39): object keys sorted at every level, nodes and edges
pre-sorted by id by the builder, `indent=2`, trailing newline — pretty,
because graph diffs must be PR-reviewable. Writes are atomic (temp +
rename): a failed build can never leave a partial file (formats §3.6).

The write-skip is the D-33 mechanism ported (formats §3.1): if the
candidate equals the existing file modulo the `generated_at` member, the
existing bytes stand — `generated_at` remains the capture timestamp of
the snapshot set whose build last *changed* the file.
"""

import json
import os
import tempfile
from pathlib import Path


def render_graph(graph: dict) -> str:
    return json.dumps(graph, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_graph(graph: dict, path: str | os.PathLike) -> bool:
    """Write the graph at `path`; returns True iff bytes changed."""
    path = Path(path)
    candidate = render_graph(graph)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if _equal_modulo_generated_at(existing, candidate):
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".graph-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(candidate)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    return True


def _equal_modulo_generated_at(existing: str, candidate: str) -> bool:
    if existing == candidate:
        return True
    try:
        old = json.loads(existing)
    except ValueError:
        return False  # unreadable prior file: rewrite it
    new = json.loads(candidate)
    old.pop("generated_at", None)
    new.pop("generated_at", None)
    return old == new
