"""Deliverable 1 — suite ingestion + validation.

Validates the customer's golden suite on three axes:

1. **Schema** — the packet matches ``schema/seed.schema.json`` as authored
   (Draft 2020-12, the repo's validator stack).
2. **FQN resolution** — every ``expected_object`` resolves against the
   pinned snapshots, and every object a golden *references* (tables for
   SQL, dimensions/metrics for API) resolves too. Golden legs are
   cross-checked against the case's declared systems.
3. **Checksum reproduction** — for any case carrying an executed
   ``verified_result`` (inline rows + checksum), the packet-canonical CSV
   checksum is recomputed and must match. The seed ships
   execution-deferred (every ``verified_result`` a stub), so this reports
   *deferred* per case rather than reproducing — the machinery is proven
   by unit test and runs for real the moment goldens execute.

The validator is pure and deterministic (no model calls, no live access);
the CI integrity check (R7) composes it with column- and contamination-
level checks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import jsonschema

from benchmark import canonical
from benchmark.fqn import SnapshotInventory
from benchmark.suite import Case, Suite, load_suite

_PKG = Path(__file__).resolve().parent
SCHEMA_PATH = _PKG / "schema" / "seed.schema.json"

# The golden suite is the customer's, and its home is the customer's KB
# (D-119.2a): requests they wrote, SQL their analyst verified, results
# they confirmed. It used to ship inside this package — which meant every
# customer's KB-CI wheel carried the pilot's suite and a frozen copy of
# the pilot's snapshots. The paths below are the KB-spec §3 locations,
# and the snapshots the goldens resolve against are the KB's own accepted
# ones, so a golden is checked against what the estate looks like *now*
# rather than against a pin that quietly ages.
SUITE_REL = Path(".contextlayer") / "benchmark" / "suite.yaml"
SNAPSHOTS_REL = Path(".contextlayer") / "snapshots"
DEFAULT_KB = Path(os.environ.get("CTXLAYER_KB") or Path.home() / "Desktop" / "kb")


def kb_suite_path(kb_root: str | Path) -> Path:
    """The KB-spec §3 home of the golden suite (may not exist — see §10.1)."""
    return Path(kb_root) / SUITE_REL


def kb_snapshot_paths(kb_root: str | Path) -> tuple[Path, ...]:
    """The KB's accepted snapshots — the facts goldens resolve against."""
    return tuple(sorted((Path(kb_root) / SNAPSHOTS_REL).glob("*.json")))


DEFAULT_SUITE = kb_suite_path(DEFAULT_KB)
DEFAULT_SNAPSHOTS = kb_snapshot_paths(DEFAULT_KB)

ERROR, WARN, INFO = "error", "warn", "info"


@dataclass(frozen=True)
class Finding:
    level: str
    kind: str
    message: str
    case_id: str | None = None


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, kind: str, message: str, case_id: str | None = None) -> None:
        self.findings.append(Finding(level, kind, message, case_id))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == WARN]

    @property
    def ok(self) -> bool:
        return not self.errors


def _load_schema() -> Mapping[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_schema(raw: Mapping[str, Any], report: ValidationReport) -> None:
    """Draft 2020-12 schema check; every violation is a finding."""
    validator = jsonschema.Draft202012Validator(_load_schema())
    for err in sorted(validator.iter_errors(raw), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "<root>"
        report.add(ERROR, "schema", f"{loc}: {err.message}")


def _reproduce_checksum(case: Case, report: ValidationReport) -> None:
    """Recompute a case's stored checksum from its inline rows (R5).

    Supports the executed shape we will write on resume: ``rows`` as a
    list of column->value mappings (columns taken in first-row order), or
    a ``columns`` list plus ``rows`` as lists. Deferred stubs report
    deferred.
    """
    vr = case.verified_result
    if case.is_execution_deferred or vr.get("rows") is None or vr.get("checksum") is None:
        report.add(
            INFO, "checksum-deferred",
            f"verified_result is {case.verified_status!r} — no inline rows to reproduce",
            case.id,
        )
        return
    rows = vr["rows"]
    if rows and isinstance(rows[0], Mapping):
        columns: Sequence[str] = list(rows[0].keys())
        matrix = [[r.get(c) for c in columns] for r in rows]
    else:
        columns = vr.get("columns", [])
        matrix = rows
    if not columns:
        report.add(ERROR, "checksum", "cannot reproduce: no columns for inline rows", case.id)
        return
    recomputed = canonical.csv_checksum(columns, matrix)
    if recomputed != vr["checksum"]:
        report.add(
            ERROR, "checksum",
            f"stored checksum {vr['checksum']} != recomputed {recomputed}",
            case.id,
        )
    else:
        report.add(INFO, "checksum", f"reproduced {recomputed}", case.id)


def _validate_case(case: Case, inv: SnapshotInventory, report: ValidationReport) -> None:
    # expected_objects must all resolve.
    for miss in inv.unresolved(case.expected_objects):
        report.add(ERROR, "expected-object", f"does not resolve: {miss}", case.id)

    # Golden legs: system membership + the objects they reference resolve.
    leg_systems = [g.system for g in case.golden]
    for sysname in leg_systems:
        if sysname not in case.systems:
            report.add(
                ERROR, "golden-system",
                f"golden leg system {sysname!r} not in case.systems {list(case.systems)}",
                case.id,
            )
    missing_legs = set(case.systems) - set(leg_systems)
    if missing_legs:
        report.add(
            ERROR, "golden-system",
            f"case declares systems {sorted(missing_legs)} with no golden leg",
            case.id,
        )

    for leg in case.golden:
        extracted = inv.extract(leg.system, leg.request)
        if not extracted.parse_ok:
            report.add(ERROR, "golden-parse", f"{leg.system}: {extracted.note}", case.id)
            continue
        for miss in inv.unresolved(extracted.fqns):
            report.add(
                ERROR, "golden-object",
                f"{leg.system} golden references unresolved object: {miss}",
                case.id,
            )

    _reproduce_checksum(case, report)


def validate_suite(suite: Suite, inventory: SnapshotInventory) -> ValidationReport:
    """Validate a loaded suite against snapshots (schema is checked on raw)."""
    report = ValidationReport()
    validate_schema(suite.raw, report)
    ids = [c.id for c in suite.cases]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        report.add(ERROR, "duplicate-id", f"duplicate case ids: {dupes}")
    for case in suite.cases:
        _validate_case(case, inventory, report)
    return report


def load_snapshots(paths: Iterable[Path]) -> list[Mapping[str, Any]]:
    snaps = []
    for p in paths:
        with Path(p).open("r", encoding="utf-8") as fh:
            snaps.append(json.load(fh))
    return snaps


def _print_report(suite: Suite, report: ValidationReport) -> None:
    print(f"suite: {suite.customer} v{suite.suite_version} "
          f"({len(suite.cases)} cases, execution_status={suite.execution_status})")
    by_level = {ERROR: [], WARN: [], INFO: []}
    for f in report.findings:
        by_level[f.level].append(f)
    for level in (ERROR, WARN, INFO):
        for f in by_level[level]:
            tag = f"[{level.upper()}]"
            where = f" {f.case_id}" if f.case_id else ""
            print(f"  {tag}{where} {f.kind}: {f.message}")
    print(f"summary: {len(report.errors)} error(s), {len(report.warnings)} warning(s), "
          f"{'OK' if report.ok else 'FAILED'}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the benchmark suite (deliverable 1).")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--snapshot", type=Path, action="append", dest="snapshots")
    parser.add_argument("--quiet", action="store_true", help="only print the summary line")
    args = parser.parse_args(argv)

    snapshot_paths = args.snapshots or list(DEFAULT_SNAPSHOTS)
    suite = load_suite(args.suite)
    inventory = SnapshotInventory(load_snapshots(snapshot_paths))
    report = validate_suite(suite, inventory)

    if args.quiet:
        print(f"{'OK' if report.ok else 'FAILED'}: {len(report.errors)} error(s)")
    else:
        _print_report(suite, report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
