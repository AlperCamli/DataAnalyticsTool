"""Typed model + loader for the benchmark suite (KB `.contextlayer/benchmark/suite.yaml`).

The YAML is a read-only, customer-verified input; this loader mirrors it
into typed objects without mutating or reshaping it. Structural
*validation* (schema, FQN resolution, checksum reproduction) lives in
``benchmark.validate``; this module only parses.

Byte-stability is not a per-case field in the seed — it is declared once
in ``handoff.time_unstable_cases.byte_stable_cases``. That list is the
authority for which correctness mode (R5) a case takes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class Golden:
    """One execution leg of a case's golden (one per system)."""

    system: str
    request: Mapping[str, Any]
    note: str | None = None

    @property
    def dialect(self) -> str:
        return self.request.get("dialect", "")


@dataclass(frozen=True)
class Case:
    id: str
    request: str
    systems: tuple[str, ...]
    expected_objects: tuple[str, ...]
    visual_kind: str
    recurring: bool
    golden: tuple[Golden, ...]
    window: Mapping[str, Any]
    blend: Mapping[str, Any] | None
    verified_result: Mapping[str, Any]
    resolution_notes: str
    notes: str
    origin: str
    verified_by: str
    byte_stable: bool = False  # set from handoff.byte_stable_cases at load

    @property
    def is_byte_stable(self) -> bool:
        return self.byte_stable

    @property
    def verified_status(self) -> str:
        return self.verified_result.get("status", "")

    @property
    def is_execution_deferred(self) -> bool:
        return self.verified_status == "pending-execution-deferred"


@dataclass(frozen=True)
class Suite:
    suite_version: str
    customer: str
    authored_at: str
    execution_status: str
    cases: tuple[Case, ...]
    handoff: Mapping[str, Any]
    byte_stable_ids: frozenset[str]
    source_path: Path | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def case(self, case_id: str) -> Case:
        for c in self.cases:
            if c.id == case_id:
                return c
        raise KeyError(case_id)

    def is_byte_stable(self, case_id: str) -> bool:
        return case_id in self.byte_stable_ids

    @property
    def systems(self) -> frozenset[str]:
        return frozenset(s for c in self.cases for s in c.systems)


def _golden(entry: Mapping[str, Any]) -> Golden:
    return Golden(
        system=entry["system"],
        request=entry["request"],
        note=entry.get("note"),
    )


def _case(entry: Mapping[str, Any], byte_stable_ids: frozenset[str]) -> Case:
    return Case(
        byte_stable=entry["id"] in byte_stable_ids,
        id=entry["id"],
        request=entry["request"],
        systems=tuple(entry.get("systems", [])),
        expected_objects=tuple(entry.get("expected_objects", [])),
        visual_kind=entry.get("visual_kind", ""),
        recurring=bool(entry.get("recurring", False)),
        golden=tuple(_golden(g) for g in entry.get("golden", [])),
        window=entry.get("window", {}) or {},
        blend=entry.get("blend"),
        verified_result=entry.get("verified_result", {}) or {},
        resolution_notes=entry.get("resolution_notes", ""),
        notes=entry.get("notes", ""),
        origin=entry.get("origin", ""),
        verified_by=entry.get("verified_by", ""),
    )


def load_suite(path: str | Path) -> Suite:
    """Parse the suite YAML into the typed model (no validation)."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return _suite_from_raw(raw, source_path=path)


def suite_from_mapping(raw: Mapping[str, Any]) -> Suite:
    """Build a Suite from an already-parsed mapping (tests, doctored copies)."""
    return _suite_from_raw(raw, source_path=None)


def _suite_from_raw(raw: Mapping[str, Any], *, source_path: Path | None) -> Suite:
    handoff = raw.get("handoff", {}) or {}
    byte_stable = (
        handoff.get("time_unstable_cases", {}).get("byte_stable_cases", [])
        if isinstance(handoff, Mapping)
        else []
    )
    byte_stable_ids = frozenset(byte_stable)
    return Suite(
        suite_version=str(raw.get("suite_version", "")),
        customer=raw.get("customer", ""),
        authored_at=str(raw.get("authored_at", "")),
        execution_status=raw.get("execution_status", ""),
        cases=tuple(_case(c, byte_stable_ids) for c in raw.get("cases", [])),
        handoff=handoff,
        byte_stable_ids=byte_stable_ids,
        source_path=source_path,
        raw=raw,
    )
