"""Deliverable 5 — the deterministic suite-integrity check (R7, CI).

The only benchmark check wired into CI — KB CI, since D-119.2a, where the
golden suite lives (KB §3, `.contextlayer/benchmark/suite.yaml`) and the
snapshots it resolves against are the KB's own accepted ones. Zero model
calls, no live access:

1. **Schema + resolution** (via ``benchmark.validate``) — the packet is
   well-formed, every ``expected_object`` resolves, and every object a
   golden references resolves against the snapshots.
2. **Column existence** — every column a SQL golden references on a base
   relation exists in that relation's snapshot columns. Resolution is
   conservative: a column is checked only where it binds unambiguously to
   one base table (qualified by an alias/name that resolves, or unqualified
   in a scope with a single base source). Ambiguous or CTE/subquery-
   projected references are skipped, never guessed — so the check never
   false-fails, and a *dropped column a golden depends on* fails it.
   (API "columns" are dimensions/metrics — the object check already covers
   them at the finest grain.)
3. **Contamination flag** — any case whose ``expected_objects`` map to a KB
   doc with ``status: contaminated`` is flagged (a warning: the case rests
   on context under drift; surfaced, not silently trusted).

Resolution and column failures are errors (CI fails). Contamination is a
flag. Accuracy runs are a separate manual command, never in CI.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Sequence

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import Scope, build_scope

from generator import frontmatter
from benchmark.fqn import SnapshotInventory
from benchmark.suite import Suite, load_suite
from benchmark.validate import (
    DEFAULT_KB,
    DEFAULT_SNAPSHOTS,
    DEFAULT_SUITE,
    ERROR,
    WARN,
    Finding,
    SUITE_REL,
    ValidationReport,
    kb_snapshot_paths,
    kb_suite_path,
    load_snapshots,
    validate_suite,
)


def _walk_scopes(scope: Scope):
    yield scope
    for child in (
        scope.cte_scopes
        + scope.derived_table_scopes
        + scope.subquery_scopes
        + scope.union_scopes
    ):
        yield from _walk_scopes(child)


def _sql_column_issues(system: str, statement: str, inv: SnapshotInventory) -> list[str]:
    """Base-relation columns a SQL golden references that are not in the snapshot."""
    try:
        statements = sqlglot.parse(statement, read="postgres")
    except ParseError as exc:
        return [f"unparseable SQL: {exc}"]
    issues: list[str] = []
    for stmt in statements:
        if stmt is None or not stmt.find(exp.Select):
            continue  # SET and other non-select statements bind no base columns
        scope = build_scope(stmt)
        if scope is None:
            continue
        for sc in _walk_scopes(scope):
            resolved: dict[str, tuple[str, frozenset[str]]] = {}
            has_scope_source = False
            for alias, source in sc.sources.items():
                if isinstance(source, Scope):
                    has_scope_source = True
                    continue
                fqn, cols = inv.sql_relation_columns(system, source.db or None, source.name)
                if cols is not None:
                    resolved[alias] = (fqn, cols)
            single = next(iter(resolved.values())) if len(resolved) == 1 else None
            for column in sc.columns:
                qualifier = column.table or None
                name = column.name
                if qualifier:
                    target = resolved.get(qualifier)
                elif single is not None and not has_scope_source:
                    target = single
                else:
                    target = None  # ambiguous / projected — skip, never guess
                if target is not None and name not in target[1]:
                    issues.append(f"{target[0]}.{name} referenced but not in snapshot")
    return sorted(set(issues))


def check_columns(suite: Suite, inv: SnapshotInventory, report: ValidationReport) -> None:
    for case in suite.cases:
        for leg in case.golden:
            if leg.dialect != "sql":
                continue
            for issue in _sql_column_issues(leg.system, leg.request.get("statement", ""), inv):
                report.add(ERROR, "golden-column", f"{leg.system}: {issue}", case.id)


def scan_contamination(kb_root: Path) -> dict[str, str]:
    """{object FQN: doc path} for KB docs whose front-matter status is contaminated."""
    contaminated: dict[str, str] = {}
    if not kb_root.is_dir():
        return contaminated
    for path in sorted(kb_root.rglob("*.md")):
        fm, _ = frontmatter.split(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(fm, dict) or fm.get("status") != "contaminated":
            continue
        obj = fm.get("object")
        rel = path.relative_to(kb_root).as_posix()
        if isinstance(obj, str):
            contaminated[obj] = rel
        # entity/group docs without a single `object` still register their
        # depends_on targets so a case touching them is flagged.
        for dep in fm.get("depends_on", []) or []:
            if isinstance(dep, str):
                contaminated.setdefault(dep, rel)
    return contaminated


def check_contamination(suite: Suite, contaminated: dict[str, str], report: ValidationReport) -> None:
    for case in suite.cases:
        for fqn in case.expected_objects:
            if fqn in contaminated:
                report.add(
                    WARN, "contaminated-context",
                    f"expected object {fqn} maps to contaminated doc {contaminated[fqn]}",
                    case.id,
                )


def integrity_report(
    suite: Suite,
    inventory: SnapshotInventory,
    kb_root: Path | None = None,
) -> ValidationReport:
    report = validate_suite(suite, inventory)
    check_columns(suite, inventory, report)
    if kb_root is not None:
        check_contamination(suite, scan_contamination(kb_root), report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic benchmark suite-integrity check (R7, CI). Zero model calls."
    )
    parser.add_argument("--kb", type=Path, default=None,
                        help="KB root: discovers the suite (KB §3), the accepted snapshots, "
                             "and the docs the contamination flag scans")
    parser.add_argument("--suite", type=Path, default=None, help="override the KB's suite path")
    parser.add_argument("--snapshot", type=Path, action="append", dest="snapshots",
                        help="override the KB's accepted snapshots")
    args = parser.parse_args(argv)

    kb = args.kb
    suite_path = args.suite or (kb_suite_path(kb) if kb else DEFAULT_SUITE)
    snapshot_paths = args.snapshots or (
        list(kb_snapshot_paths(kb)) if kb else list(DEFAULT_SNAPSHOTS))

    # A KB with no golden suite is a KB that has not reached playbook step
    # 8 yet, which is a stage of onboarding and not a defect. The check
    # says so and passes; what it must never do is pass *silently*, which
    # would read the same as a suite that was checked.
    if not suite_path.is_file():
        print(f"integrity: no golden suite at {suite_path} — nothing to check (KB §10.1). "
              f"Add one at {SUITE_REL.as_posix()} to arm this check.")
        return 0
    if not snapshot_paths:
        print(f"[ERROR] no accepted snapshots to resolve goldens against "
              f"(looked in {(kb or DEFAULT_KB)}/.contextlayer/snapshots)")
        return 1

    suite = load_suite(suite_path)
    inventory = SnapshotInventory(load_snapshots(snapshot_paths))
    report = integrity_report(suite, inventory, kb)

    for f in report.findings:
        if f.level in (ERROR, WARN):
            where = f" {f.case_id}" if f.case_id else ""
            print(f"[{f.level.upper()}]{where} {f.kind}: {f.message}")
    print(f"integrity: {suite.customer} suite v{suite.suite_version}, {len(suite.cases)} case(s) "
          f"against {len(snapshot_paths)} snapshot(s) — "
          f"{len(report.errors)} error(s), {len(report.warnings)} flag(s) — "
          f"{'GREEN' if report.ok else 'FAILED'}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
