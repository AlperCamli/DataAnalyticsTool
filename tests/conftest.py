import copy
import json
from pathlib import Path

import pytest

from snapshot.hashing import schema_hash

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

FIXTURE_FILES = [
    "supabase-ddl.json",
    "supabase-live.json",
    "ga4.json",
    "gsc.json",
    "drift-pair/before.json",
    "drift-pair/after.json",
]


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def supabase() -> dict:
    return load_fixture("supabase-ddl.json")


@pytest.fixture
def ga4() -> dict:
    return load_fixture("ga4.json")


def find_object(snapshot: dict, name: str) -> dict:
    return next(o for o in snapshot["objects"] if o["name"] == name)


def mutate(snapshot: dict, name: str, fn, *, rehash: bool = True) -> dict:
    """Deep-copy a snapshot, apply fn to the named object, and (like an
    honest producer) recompute that object's schema_hash."""
    out = copy.deepcopy(snapshot)
    obj = find_object(out, name)
    fn(obj)
    if rehash:
        obj["schema_hash"] = schema_hash(obj)
    return out
