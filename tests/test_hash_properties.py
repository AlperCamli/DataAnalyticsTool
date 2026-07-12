"""Property tests for canonicalization and hashing.

Required by task 1.1 deliverable 2: hashing is stable under key
reordering, and captured_at is excluded from the canonical body (S-3).
Also covers the S-2 exclusions (descriptions, hash-excluded stats) and
§6 array-ordering invariance as properties.
"""

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from snapshot.canonical import canonical_body_bytes, canonical_object_bytes
from snapshot.hashing import schema_hash
from snapshot.registry import KIND_REGISTRY

# ---------------------------------------------------------------- strategies

_name = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=0x2FF), min_size=1, max_size=12
)
_description = st.one_of(st.none(), st.text(max_size=40))

_STAT_VALUES = {
    "definition": st.text(min_size=1, max_size=60),
    "data_type": st.sampled_from(["string", "integer", "double", "TYPE_CURRENCY"]),
    "scope": st.sampled_from(["EVENT", "USER"]),
    "formula": st.text(min_size=1, max_size=30),
    "is_key_event": st.booleans(),
    "row_estimate": st.integers(min_value=0, max_value=10**9),
    # registered form is lexicographically sorted (§4.5, task 1.2 amendment)
    "indexes": st.lists(st.text(min_size=1, max_size=60), max_size=3, unique=True).map(sorted),
}


@st.composite
def columns_strategy(draw):
    names = draw(st.lists(_name, min_size=0, max_size=6, unique=True))
    ordinals = random.Random(draw(st.integers(0, 2**16))).sample(
        range(1, len(names) + 1), len(names)
    )
    return [
        {
            "name": name,
            "type": draw(st.sampled_from(["text", "integer", "uuid", "bigint"])),
            "nullable": draw(st.booleans()),
            "default": draw(st.one_of(st.none(), st.text(max_size=10))),
            "ordinal": ordinal,
            "description": draw(_description),
        }
        for name, ordinal in zip(names, ordinals)
    ]


@st.composite
def object_strategy(draw):
    kind = draw(st.sampled_from(sorted(KIND_REGISTRY)))
    spec = KIND_REGISTRY[kind]
    columns = draw(columns_strategy())
    col_names = [c["name"] for c in columns]

    keys = {}
    if col_names and draw(st.booleans()):
        keys["primary"] = [col_names[0]]
    if len(col_names) > 1 and draw(st.booleans()):
        keys["foreign"] = [
            {"columns": [col_names[1]], "ref": "public.other", "ref_columns": ["id"]}
        ]
    if col_names and draw(st.booleans()):
        keys["unique"] = draw(
            st.lists(
                st.lists(st.sampled_from(col_names), min_size=1, max_size=2),
                max_size=2,
            )
        )

    stats = {
        field: draw(_STAT_VALUES[field])
        for field in sorted(spec.hash_included_stats | spec.hash_excluded_stats)
        if draw(st.booleans())
    }
    return {
        "kind": kind,
        "schema": draw(_name),
        "name": draw(_name),
        "description": draw(_description),
        "schema_hash": "sha256:" + "0" * 64,
        "columns": columns,
        "keys": keys,
        "stats": stats,
    }


@st.composite
def snapshot_strategy(draw):
    objects = draw(st.lists(object_strategy(), min_size=1, max_size=4))
    seen = set()
    objects = [
        o for o in objects
        if (identity := (o["kind"], o["schema"], o["name"])) not in seen
        and not seen.add(identity)
    ]
    for obj in objects:
        obj["schema_hash"] = schema_hash(obj)
    return {
        "snapshot_version": "1",
        "system": "propcheck",
        "system_class": "sql",
        "source_mode": draw(st.sampled_from(["ddl-file", "live", "api"])),
        "captured_at": draw(
            st.sampled_from(["2026-07-10T00:00:00Z", "2026-07-11T13:37:00Z"])
        ),
        "connector": {"name": draw(_name), "version": "0.1.0"},
        "source_properties": {"server_version": draw(_name)},
        "objects": objects,
    }


def reorder_keys(value, rng: random.Random):
    """Rebuild dicts with shuffled key insertion order; list order kept."""
    if isinstance(value, dict):
        items = list(value.items())
        rng.shuffle(items)
        return {k: reorder_keys(v, rng) for k, v in items}
    if isinstance(value, list):
        return [reorder_keys(v, rng) for v in value]
    return value


# --------------------------------------------------------------- properties


@settings(max_examples=200)
@given(obj=object_strategy(), seed=st.integers(0, 2**32))
def test_schema_hash_stable_under_key_reordering(obj, seed):
    reordered = reorder_keys(obj, random.Random(seed))
    assert schema_hash(reordered) == schema_hash(obj)


@settings(max_examples=200)
@given(obj=object_strategy(), seed=st.integers(0, 2**32))
def test_object_bytes_stable_under_column_and_key_order(obj, seed):
    rng = random.Random(seed)
    shuffled = dict(obj)
    shuffled["columns"] = obj["columns"][:]
    rng.shuffle(shuffled["columns"])
    shuffled["keys"] = dict(obj["keys"])
    if "foreign" in shuffled["keys"]:
        shuffled["keys"]["foreign"] = shuffled["keys"]["foreign"][:]
        rng.shuffle(shuffled["keys"]["foreign"])
    if "unique" in shuffled["keys"]:
        shuffled["keys"]["unique"] = shuffled["keys"]["unique"][:]
        rng.shuffle(shuffled["keys"]["unique"])
    assert canonical_object_bytes(shuffled) == canonical_object_bytes(obj)
    assert schema_hash(shuffled) == schema_hash(obj)


@settings(max_examples=100)
@given(snap=snapshot_strategy(), seed=st.integers(0, 2**32))
def test_captured_at_and_provenance_excluded_from_canonical_body(snap, seed):
    """S-3 (+ D-1): captured_at, connector, and source_mode never affect
    the canonical body."""
    other = dict(snap)
    other["captured_at"] = "2031-01-01T00:00:00Z"
    other["connector"] = {"name": "different", "version": "9.9.9"}
    other["source_mode"] = "live" if snap["source_mode"] != "live" else "api"
    other = reorder_keys(other, random.Random(seed))
    assert canonical_body_bytes(other) == canonical_body_bytes(snap)


@settings(max_examples=100)
@given(snap=snapshot_strategy(), seed=st.integers(0, 2**32))
def test_canonical_body_stable_under_object_order(snap, seed):
    shuffled = dict(snap)
    shuffled["objects"] = snap["objects"][:]
    random.Random(seed).shuffle(shuffled["objects"])
    assert canonical_body_bytes(shuffled) == canonical_body_bytes(snap)


@settings(max_examples=200)
@given(obj=object_strategy(), text=st.text(max_size=20))
def test_hash_excludes_descriptions_and_volatile_stats(obj, text):
    """S-2: descriptions and hash-excluded stats never move the hash."""
    noisy = dict(obj)
    noisy["description"] = text
    noisy["columns"] = [dict(c, description=text) for c in obj["columns"]]
    excluded = KIND_REGISTRY[obj["kind"]].hash_excluded_stats
    noisy["stats"] = dict(obj["stats"], **{f: 424242 for f in excluded})
    assert schema_hash(noisy) == schema_hash(obj)


@settings(max_examples=200)
@given(obj=object_strategy())
def test_hash_sensitive_to_structural_change(obj):
    """Adding a column always moves the hash."""
    changed = dict(obj)
    changed["columns"] = obj["columns"] + [{
        "name": "zz_new_column", "type": "text", "nullable": True,
        "default": None, "ordinal": max(
            (c["ordinal"] for c in obj["columns"]), default=0) + 1,
        "description": None,
    }]
    assert schema_hash(changed) != schema_hash(obj)
