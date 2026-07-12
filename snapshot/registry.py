"""Kind registry (spec §4.2) and the stats-field registry (§4.5).

The registry is open (S-5): consumers skip unknown kinds with a logged
warning. Each registered stats field declares whether it is hash-included
(structural) or hash-excluded (volatile); undeclared fields are forbidden
in emitted snapshots (S-7, verified by conformance test C-8).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class KindSpec:
    system_class: str
    hash_included_stats: frozenset[str] = field(default_factory=frozenset)
    hash_excluded_stats: frozenset[str] = field(default_factory=frozenset)


KIND_REGISTRY: dict[str, KindSpec] = {
    "table": KindSpec("sql", hash_excluded_stats=frozenset({"row_estimate"})),
    "view": KindSpec("sql", hash_included_stats=frozenset({"definition"})),
    "materialized_view": KindSpec("sql", hash_included_stats=frozenset({"definition"})),
    "api_dimension": KindSpec("api", hash_included_stats=frozenset({"data_type"})),
    "api_metric": KindSpec(
        "api", hash_included_stats=frozenset({"data_type", "scope", "formula"})
    ),
    "api_event": KindSpec("api", hash_included_stats=frozenset({"is_key_event"})),
}


def registered_stats_fields(kind: str) -> frozenset[str]:
    """All declared stats fields for a kind (hash-included + excluded)."""
    spec = KIND_REGISTRY[kind]
    return spec.hash_included_stats | spec.hash_excluded_stats
