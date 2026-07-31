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
    # `indexes` + matview `row_estimate` registered by the task 1.2
    # amendment (§4.5 registration record): hash-excluded — an index
    # cannot break a dependent or contradict a documented meaning;
    # semantic uniqueness belongs in a UNIQUE constraint (keys.unique,
    # hash-included), not in a bare unique index.
    # `checks` registered by the SS-5 capture (spec §4.5 registration
    # record, ruling D-96.3d): hash-INCLUDED, unlike `indexes`. The S-2
    # test is "can this contradict a documented meaning?" — an index
    # cannot; a CHECK *is* a documented meaning, so dropping or widening
    # one must be able to contaminate the doc that explains it.
    "table": KindSpec(
        "sql",
        hash_included_stats=frozenset({"checks"}),
        hash_excluded_stats=frozenset({"row_estimate", "indexes"}),
    ),
    "view": KindSpec("sql", hash_included_stats=frozenset({"definition"})),
    "materialized_view": KindSpec(
        "sql",
        hash_included_stats=frozenset({"definition"}),
        hash_excluded_stats=frozenset({"row_estimate", "indexes"}),
    ),
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
