"""Naming rules: path mangling (KB §3), FQNs (KB §8), anchors (D-36.7).

The authoritative source-native name always lives in front-matter
(`object:`), so filename mangling never loses identity.
"""

import re

_MANGLE = re.compile(r"[^a-z0-9_-]")

# KB §3 M-owned index/doc names the generator may write besides *.schema.md.
KIND_GROUPS: dict[str, str] = {
    "api_dimension": "dimensions",
    "api_metric": "metrics",
    "api_event": "events",
}
SQL_KINDS = frozenset({"table", "view", "materialized_view"})


def mangle(name: str) -> str:
    """KB §3 path rule: lowercase, chars outside [a-z0-9_-] map to '-'."""
    return _MANGLE.sub("-", name.lower())


def fqn(system: str, schema: str, name: str) -> str:
    """KB §8 FQN grammar: system.schema.name (SQL) / system.group.name (API)."""
    return f"{system}.{schema}.{name}"


def anchor_id(schema: str, name: str) -> str:
    """Deterministic anchor id for a group-doc subsection (KB §8, D-36.7)."""
    return f"{mangle(schema)}--{mangle(name)}"
