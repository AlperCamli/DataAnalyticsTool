"""Naming rules (KB §3 path mangling, §8 FQNs, D-36.7 anchors)."""

import re

from hypothesis import given
from hypothesis import strategies as st

from generator.naming import anchor_id, fqn, mangle

_CHARSET = re.compile(r"[a-z0-9_-]*")


@given(st.text(min_size=1))
def test_mangle_output_stays_in_path_charset(name):
    assert _CHARSET.fullmatch(mangle(name))


@given(st.text(min_size=1))
def test_mangle_is_idempotent(name):
    assert mangle(mangle(name)) == mangle(name)


def test_mangle_examples():
    assert mangle("orders") == "orders"
    assert mangle("customEvent:plan_tier") == "customevent-plan_tier"
    assert mangle("Sales Data") == "sales-data"
    assert mangle("A/B Test") == "a-b-test"


def test_fqn_matches_kb8_grammar():
    assert fqn("supabase", "public", "orders") == "supabase.public.orders"
    assert fqn("ga4", "custom", "calcMetric:revenue_per_user") == (
        "ga4.custom.calcMetric:revenue_per_user"
    )


def test_anchor_id_is_schema_qualified_and_mangled():
    assert anchor_id("custom", "customEvent:plan_tier") == (
        "custom--customevent-plan_tier"
    )
    assert anchor_id("standard", "country") == "standard--country"
