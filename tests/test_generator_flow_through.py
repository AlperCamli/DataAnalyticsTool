"""S-2 flow-through: description edits reach machine docs without touching
hashes or neighbours; structural changes move exactly one object's file.

Estate-level version runs on `fixtures/drift-pair/` (one instance of every
§7 classification) and pins D-33 Rule B across its differing capture dates.
"""

from generator.render import render_tree
from tests.conftest import changed_paths, load_fixture, mutate, tree_bytes

ORDERS = "systems/supabase/public/orders.schema.md"


def test_comment_only_change_touches_one_file_hash_unchanged(tmp_path):
    snap = load_fixture("supabase-ddl.json")
    render_tree([snap], tmp_path)
    before = tree_bytes(tmp_path)

    def edit(obj):
        col = next(c for c in obj["columns"] if c["name"] == "notes")
        col["description"] = "Free-form gift note, shown on the packing slip."

    edited = mutate(snap, "orders", edit)  # rehash: no-op — descriptions are S-2-excluded
    render_tree([edited], tmp_path)
    after = tree_bytes(tmp_path)

    assert changed_paths(before, after) == {ORDERS}
    old_hash_line = next(
        line for line in before[ORDERS].splitlines() if line.startswith(b"schema_hash:")
    )
    assert old_hash_line in after[ORDERS]  # front-matter hash unchanged
    assert b"Free-form gift note, shown on the packing slip." in after[ORDERS]


def test_comment_only_change_with_new_capture_date_still_touches_one_file(tmp_path):
    """Rule B is what makes this hold: unaffected files keep their stamps
    even though the regenerating snapshot is a day newer."""
    snap = load_fixture("supabase-ddl.json")
    render_tree([snap], tmp_path)
    before = tree_bytes(tmp_path)

    def edit(obj):
        obj["description"] = "One row per checkout; append-only after payment."

    edited = mutate(snap, "orders", edit)
    edited["captured_at"] = "2026-07-12T02:00:00Z"
    render_tree([edited], tmp_path)
    after = tree_bytes(tmp_path)

    assert changed_paths(before, after) == {ORDERS}
    assert b"generated_at: 2026-07-12" in after[ORDERS]  # the changed file restamps
    assert b"generated_at: 2026-07-11" in after["systems/supabase/public/users.schema.md"]


def test_structural_change_touches_one_file_and_its_hash(tmp_path):
    snap = load_fixture("supabase-ddl.json")
    render_tree([snap], tmp_path)
    before = tree_bytes(tmp_path)

    def edit(obj):
        col = next(c for c in obj["columns"] if c["name"] == "total_cents")
        col["type"] = "bigint"

    render_tree([mutate(snap, "orders", edit)], tmp_path)
    after = tree_bytes(tmp_path)

    assert changed_paths(before, after) == {ORDERS}
    old_hash = next(
        line for line in before[ORDERS].splitlines() if line.startswith(b"schema_hash:")
    )
    new_hash = next(
        line for line in after[ORDERS].splitlines() if line.startswith(b"schema_hash:")
    )
    assert old_hash != new_hash
    assert b"| 4 | `total_cents` | `bigint` |" in after[ORDERS]


def test_drift_pair_estate_flow_through(tmp_path):
    base = "systems/supabase/public"
    render_tree([load_fixture("drift-pair/before.json")], tmp_path)
    before = tree_bytes(tmp_path)
    result = render_tree([load_fixture("drift-pair/after.json")], tmp_path)
    after = tree_bytes(tmp_path)

    # unchanged object: byte-identical file, 07-10 stamp retained (Rule B)
    assert after[f"{base}/users.schema.md"] == before[f"{base}/users.schema.md"]
    assert b"generated_at: 2026-07-10" in after[f"{base}/users.schema.md"]

    # metadata-only: file changed, hash line unchanged, restamped
    prod_before, prod_after = before[f"{base}/products.schema.md"], after[f"{base}/products.schema.md"]
    assert prod_before != prod_after
    hash_line = next(l for l in prod_before.splitlines() if l.startswith(b"schema_hash:"))
    assert hash_line in prod_after
    assert b"Price in cents, VAT included." in prod_after
    assert b"Row estimate: 355" in prod_after
    assert b"generated_at: 2026-07-11" in prod_after

    # structural: file + hash line changed
    for name in ("orders", "v_daily_revenue"):
        old = next(l for l in before[f"{base}/{name}.schema.md"].splitlines() if l.startswith(b"schema_hash:"))
        new = next(l for l in after[f"{base}/{name}.schema.md"].splitlines() if l.startswith(b"schema_hash:"))
        assert old != new, name

    # removed / added
    assert f"{base}/legacy_sessions.schema.md" not in after
    assert f"{base}/legacy_sessions.schema.md" in result.deleted
    assert f"{base}/coupons.schema.md" in after
    assert f"{base}/coupons.schema.md" in result.written

    # nothing outside the supabase subtree moved
    assert all(rel.startswith("systems/supabase/") or before.get(rel) == after.get(rel)
               for rel in set(before) | set(after))
