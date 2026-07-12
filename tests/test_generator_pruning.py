"""Pruning-safety pair (D-36.3): a vanished object's machine file is
deleted; human-owned files and the entities/ lineage/ .contextlayer/
subtrees are provably untouched — the K-1 fence as an assertion."""

import copy

from generator.render import render_tree
from tests.conftest import human_object_doc, load_fixture, tree_bytes

BASE = "systems/supabase/public"


def test_removed_object_pruned_everything_human_untouched(tmp_path):
    snaps = [load_fixture(n) for n in ("supabase-ddl.json", "ga4.json", "gsc.json")]
    render_tree(snaps, tmp_path)

    # plant human-owned files and non-generator subtrees
    orders_hash = next(
        o["schema_hash"] for o in snaps[0]["objects"] if o["name"] == "orders"
    )
    planted = {
        f"{BASE}/orders.md": human_object_doc("supabase.public.orders", orders_hash),
        "systems/supabase/_notes.md": "# Ops notes\n\nNightly refresh at 02:00.\n",
        "systems/ga4/dimensions.md": "---\ndoc_class: human-group\n---\n\nGroup notes.\n",
        "entities/user.md": "---\ndoc_class: entity\n---\n\nThe user entity.\n",
        "metrics/revenue.md": "# Revenue\n",
        "lineage/graph.json": '{"graph_version": "1", "edges": []}\n',
        ".contextlayer/sources.yaml": "supabase: {connector: postgres}\n",
    }
    for rel, content in planted.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    # re-render so indexes absorb the planted human docs, then baseline
    render_tree(snaps, tmp_path)
    before = tree_bytes(tmp_path)

    without_products = copy.deepcopy(snaps[0])
    without_products["objects"] = [
        o for o in without_products["objects"] if o["name"] != "products"
    ]
    result = render_tree([without_products, snaps[1], snaps[2]], tmp_path)
    after = tree_bytes(tmp_path)

    # the vanished object's machine file is gone — and only pruned there
    assert f"{BASE}/products.schema.md" not in after
    assert result.deleted == [f"{BASE}/products.schema.md"]

    # every planted file is byte-identical
    for rel in planted:
        assert after[rel] == before[rel], rel

    # human docs never counted as machine files: orders.md survives and
    # the index still marks it hot
    assert b"[orders.md](orders.md)" in after[f"{BASE}/index.md"]

    # order_items still renders; its FK to the vanished products de-links
    oi = after[f"{BASE}/order_items.schema.md"]
    assert b"(products.schema.md)" not in oi
    assert b"`public.products`" in oi


def test_untouched_system_subtree_is_never_pruned(tmp_path):
    snaps = [load_fixture(n) for n in ("supabase-ddl.json", "ga4.json")]
    render_tree(snaps, tmp_path)
    before = tree_bytes(tmp_path)

    # a run scoped to ga4 only must not touch the supabase subtree (§7:
    # system removal is administrative, never inferred from absence)
    result = render_tree([snaps[1]], tmp_path)
    after = tree_bytes(tmp_path)
    assert result.deleted == []
    supabase = {rel for rel in before if rel.startswith("systems/supabase/")}
    assert supabase and all(after[rel] == before[rel] for rel in supabase)
