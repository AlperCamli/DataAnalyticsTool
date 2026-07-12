"""Parser hard cases (task 1.9 reading-gate table), exact expected edges.

Each case asserts the merged graph shape (formats §3.2/§3.3) so the
assertions cover the deliverable format, not parser internals. Readings
under test are D-41 (failure semantics) and D-42 (canonical readings).
"""

import pytest

from lineage import LineageParseError, build_graph
from lineage.parser import definition_ref
from tests.conftest import graph_edge, graph_node, sql_object, sql_snapshot


def build(*objects, system="demo"):
    return build_graph([sql_snapshot(*objects, system=system)])


def view(schema, name, definition, columns):
    return sql_object("view", schema, name, columns, definition=definition)


# --- star expansion (D-42.3) -----------------------------------------------


def test_star_expansion_binds_to_snapshot_inventory():
    graph = build(
        sql_object("table", "public", "a", ["x", "y", "z"]),
        view("public", "v", "SELECT * FROM public.a", ["x", "y", "z"]),
    )
    edge = graph_edge(graph, "demo.public.a", "demo.public.v")
    assert edge["columns"] == [
        {"from": ["x"], "to": "x"},
        {"from": ["y"], "to": "y"},
        {"from": ["z"], "to": "z"},
    ]
    assert edge["operation"] == "rename"  # pure passthrough floor (D-42.1)


def test_qualified_star_expands_only_that_source():
    graph = build(
        sql_object("table", "public", "a", ["x"]),
        sql_object("table", "public", "b", ["u", "w"]),
        view(
            "public", "v",
            "SELECT t2.* FROM public.a AS t1 JOIN public.b AS t2 ON t1.x = t2.u",
            ["u", "w"],
        ),
    )
    edge_b = graph_edge(graph, "demo.public.b", "demo.public.v")
    assert edge_b["columns"] == [{"from": ["u"], "to": "u"}, {"from": ["w"], "to": "w"}]
    # a feeds only the ON clause: relation edge exists, no mappings (FM-6)
    edge_a = graph_edge(graph, "demo.public.a", "demo.public.v")
    assert "columns" not in edge_a
    assert edge_a["operation"] == edge_b["operation"] == "join"


# --- expression / derived columns and operation precedence (D-42.1/.2) ------


@pytest.mark.parametrize(
    ("definition", "operation"),
    [
        ("SELECT a, b FROM public.t", "rename"),  # passthrough floor
        ("SELECT a AS renamed FROM public.t", "rename"),
        ("SELECT CAST(a AS integer) AS a_int FROM public.t", "cast"),
        ("SELECT a || b AS joined FROM public.t", "derive"),
        ("SELECT a FROM public.t WHERE b = 'x'", "filter"),
        ("SELECT DISTINCT a FROM public.t", "dedupe"),
        ("SELECT sum(a) AS s FROM public.t", "aggregate"),
    ],
)
def test_operation_precedence(definition, operation):
    graph = build(
        sql_object("table", "public", "t", ["a", "b"]),
        view("public", "v", definition, ["a"]),
    )
    assert graph_edge(graph, "demo.public.t", "demo.public.v")["operation"] == operation


def test_derived_column_lists_every_contributing_source_column():
    graph = build(
        sql_object("table", "public", "t", ["a", "b", "c"]),
        view("public", "v", "SELECT a || b AS joined, c FROM public.t", ["joined", "c"]),
    )
    edge = graph_edge(graph, "demo.public.t", "demo.public.v")
    assert edge["columns"] == [
        {"from": ["c"], "to": "c"},               # passthrough rides the same edge
        {"from": ["a", "b"], "to": "joined"},     # derivation, all sources listed
    ]


def test_multi_source_derived_column_appears_on_each_edge():
    graph = build(
        sql_object("table", "public", "a", ["x", "k"]),
        sql_object("table", "public", "b", ["y", "k"]),
        view(
            "public", "v",
            "SELECT a1.x || b1.y AS s FROM public.a a1 JOIN public.b b1 ON a1.k = b1.k",
            ["s"],
        ),
    )
    # same `to` on both contributing edges, each listing only its own columns
    assert graph_edge(graph, "demo.public.a", "demo.public.v")["columns"] == [
        {"from": ["x"], "to": "s"}
    ]
    assert graph_edge(graph, "demo.public.b", "demo.public.v")["columns"] == [
        {"from": ["y"], "to": "s"}
    ]


# --- aggregates and GROUP BY (D-42.2) ----------------------------------------


def test_aggregate_group_by_mappings():
    graph = build(
        sql_object("table", "public", "t", ["ts", "v", "flag"]),
        view(
            "public", "v_agg",
            "SELECT date_trunc('day', ts) AS day, sum(v) AS total, count(*) AS n"
            " FROM public.t WHERE flag = 'on' GROUP BY 1",
            ["day", "total", "n"],
        ),
    )
    edge = graph_edge(graph, "demo.public.t", "demo.public.v_agg")
    assert edge["operation"] == "aggregate"
    assert edge["columns"] == [
        {"from": ["ts"], "to": "day"},   # GROUP BY key is an ordinary mapping
        {"from": [], "to": "n"},         # column-free derivation: from == []
        {"from": ["v"], "to": "total"},
    ]
    # `flag` feeds no output column: no mapping anywhere (FM-6),
    # the relation-level edge carries the dependency.
    assert not any(
        "flag" in m["from"] for m in edge["columns"]
    )


def test_where_only_relation_still_makes_an_edge():
    graph = build(
        sql_object("table", "public", "t", ["id", "a"]),
        sql_object("table", "public", "u", ["tid"]),
        view(
            "public", "v",
            "SELECT a FROM public.t WHERE EXISTS"
            " (SELECT 1 FROM public.u WHERE u.tid = t.id)",
            ["a"],
        ),
    )
    edge_u = graph_edge(graph, "demo.public.u", "demo.public.v")
    assert "columns" not in edge_u  # no output column derives from u
    assert graph_edge(graph, "demo.public.t", "demo.public.v")["columns"] == [
        {"from": ["a"], "to": "a"}
    ]


# --- CTEs and nested subqueries (D-42.5) --------------------------------------


def test_cte_is_a_scope_not_a_node():
    graph = build(
        sql_object("table", "public", "t", ["a"]),
        view(
            "public", "v",
            "WITH c AS (SELECT a AS x FROM public.t) SELECT x AS y FROM c",
            ["y"],
        ),
    )
    assert {n["id"] for n in graph["nodes"]} == {"demo.public.t", "demo.public.v"}
    assert graph_edge(graph, "demo.public.t", "demo.public.v")["columns"] == [
        {"from": ["a"], "to": "y"}
    ]


def test_cte_shadows_real_table():
    graph = build(
        sql_object("table", "public", "t", ["a"]),
        sql_object("table", "public", "c", ["q"]),  # real table named like the CTE
        view(
            "public", "v",
            "WITH c AS (SELECT a AS x FROM public.t) SELECT x FROM c",
            ["x"],
        ),
    )
    # Postgres scoping: the CTE wins inside the query; the real c is no edge
    assert {n["id"] for n in graph["nodes"]} == {"demo.public.t", "demo.public.v"}


def test_nested_subquery_traced_through():
    graph = build(
        sql_object("table", "public", "t", ["a"]),
        view(
            "public", "v",
            "SELECT s.x FROM (SELECT a AS x FROM public.t) AS s",
            ["x"],
        ),
    )
    assert graph_edge(graph, "demo.public.t", "demo.public.v")["columns"] == [
        {"from": ["a"], "to": "x"}
    ]


# --- views on views (D-42.4) --------------------------------------------------


def test_views_on_views_direct_upstream_only():
    graph = build(
        sql_object("table", "public", "t", ["a", "b"]),
        view("public", "v1", "SELECT a, b FROM public.t", ["a", "b"]),
        view("public", "v2", "SELECT * FROM public.v1", ["a", "b"]),
    )
    # v2's star binds to v1's snapshot-recorded columns, not to t's
    assert graph_edge(graph, "demo.public.v1", "demo.public.v2")["columns"] == [
        {"from": ["a"], "to": "a"},
        {"from": ["b"], "to": "b"},
    ]
    # no transitive collapse: t -> v2 must not exist
    assert not any(
        e["source"] == "demo.public.t" and e["target"] == "demo.public.v2"
        for e in graph["edges"]
    )


# --- self-joins and aliases (D-42.6) -------------------------------------------


def test_self_join_collapses_to_one_edge():
    graph = build(
        sql_object("table", "public", "t", ["id", "parent_id", "a"]),
        view(
            "public", "v",
            "SELECT o1.a AS child_a, o2.a AS parent_a"
            " FROM public.t o1 JOIN public.t o2 ON o1.parent_id = o2.id",
            ["child_a", "parent_a"],
        ),
    )
    edges = [e for e in graph["edges"] if e["target"] == "demo.public.v"]
    assert len(edges) == 1  # F-1 identity collapses the aliases
    assert edges[0]["columns"] == [
        {"from": ["a"], "to": "child_a"},
        {"from": ["a"], "to": "parent_a"},
    ]


# --- unqualified names (D-42.7, fallback path) ---------------------------------


def test_unqualified_relation_unique_match_resolves():
    graph = build(
        sql_object("table", "public", "t", ["a"]),
        view("public", "v", "SELECT a FROM t", ["a"]),
    )
    assert graph_edge(graph, "demo.public.t", "demo.public.v")["columns"] == [
        {"from": ["a"], "to": "a"}
    ]
    assert graph_node(graph, "demo.public.t")["resolved"] is True


def test_unqualified_ambiguous_is_never_guessed():
    graph = build(
        sql_object("table", "public", "t", ["a"]),
        sql_object("table", "archive", "t", ["a"]),
        view("public", "v", "SELECT a FROM t", ["a"]),
    )
    node = graph_node(graph, "demo.t")  # the reference as written, system-prefixed
    assert node["resolved"] is False
    assert node["node_kind"] == "external"
    assert "doc" not in node


# --- unresolved references (D-41, FG-3 shape) -----------------------------------


def test_dangling_reference_marker():
    graph = build(
        sql_object("table", "public", "t", ["a"]),
        view(
            "public", "v",
            "SELECT e.uid AS user_id, t.a FROM analytics.events e"
            " JOIN public.t t ON t.a = e.uid",
            ["user_id", "a"],
        ),
    )
    node = graph_node(graph, "demo.analytics.events")
    assert node == {
        "id": "demo.analytics.events",
        "node_kind": "external",  # unclassifiable from current snapshots
        "resolved": False,        # the load-bearing flag
    }
    # the edge is kept, and the text-attested column mapping rides it
    edge = graph_edge(graph, "demo.analytics.events", "demo.public.v")
    assert edge["columns"] == [{"from": ["uid"], "to": "user_id"}]


def test_star_over_dangling_relation_omits_columns():
    graph = build(
        sql_object("table", "public", "t", ["a"]),
        view("public", "v", "SELECT * FROM analytics.events", ["whatever"]),
    )
    edge = graph_edge(graph, "demo.analytics.events", "demo.public.v")
    assert "columns" not in edge  # no inventory to bind: never fabricated


# --- set operations --------------------------------------------------------------


def test_union_folds_both_branches_into_left_names():
    graph = build(
        sql_object("table", "public", "x", ["a"]),
        sql_object("table", "public", "y", ["b"]),
        view("public", "v", "SELECT a FROM public.x UNION SELECT b FROM public.y", ["a"]),
    )
    assert graph_edge(graph, "demo.public.x", "demo.public.v")["columns"] == [
        {"from": ["a"], "to": "a"}
    ]
    # right branch contributes positionally under the left branch's name
    assert graph_edge(graph, "demo.public.y", "demo.public.v")["columns"] == [
        {"from": ["b"], "to": "a"}
    ]
    assert graph_edge(graph, "demo.public.x", "demo.public.v")["operation"] == "dedupe"


# --- parse failure (formats §3.6, D-41): hard, loud, attributable ----------------


def test_unparseable_definition_fails_the_whole_build():
    bad = ")))) this is not sql (((("
    snapshot = sql_snapshot(
        sql_object("table", "public", "t", ["a"]),
        view("public", "good", "SELECT a FROM public.t", ["a"]),
        view("public", "broken", bad, ["a"]),
    )
    with pytest.raises(LineageParseError) as err:
        build_graph([snapshot])
    assert "demo.public.broken" in str(err.value)
    assert definition_ref(bad) in str(err.value)  # view-def sha256:... attributable


def test_non_select_definition_is_a_parse_failure():
    snapshot = sql_snapshot(
        sql_object("table", "public", "t", ["a"]),
        view("public", "v", "INSERT INTO t VALUES (1)", ["a"]),
    )
    with pytest.raises(LineageParseError):
        build_graph([snapshot])
