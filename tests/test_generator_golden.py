"""Golden-tree test: the three real snapshots render byte-for-byte to the
checked-in tree at tests/golden/kb (fresh dir → pure function of the
snapshots, D-33). Regenerate the golden with:

    python -m generator.render fixtures/supabase-ddl.json \
        fixtures/ga4.json fixtures/gsc.json --out tests/golden/kb
"""

from pathlib import Path

from generator.render import render_tree
from tests.conftest import load_fixture, tree_bytes

GOLDEN = Path(__file__).resolve().parent / "golden" / "kb"


def test_three_real_snapshots_match_golden_tree(tmp_path):
    render_tree(
        [load_fixture(n) for n in ("supabase-ddl.json", "ga4.json", "gsc.json")],
        tmp_path,
    )
    golden, actual = tree_bytes(GOLDEN), tree_bytes(tmp_path)
    assert set(actual) == set(golden)
    for rel in sorted(golden):
        assert actual[rel] == golden[rel], f"{rel} drifted from the golden tree"
