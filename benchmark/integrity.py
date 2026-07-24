"""Deliverable 5 — the deterministic suite-integrity check (R7, CI).

The only benchmark check wired into CI. Zero model calls, no live access:

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
    DEFAULT_SNAPSHOTS,
    DEFAULT_SUITE,
    ERROR,
    WARN,
    Finding,
    ValidationReport,
    load_snapshots,
    validate_suite,
)

DEFAULT_KB = Path.home() / "Desktop" / "kb"


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
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--snapshot", type=Path, action="append", dest="snapshots")
    parser.add_argument("--kb", type=Path, default=None, help="KB root for the contamination scan")
    args = parser.parse_args(argv)

    suite = load_suite(args.suite)
    inventory = SnapshotInventory(load_snapshots(args.snapshots or list(DEFAULT_SNAPSHOTS)))
    report = integrity_report(suite, inventory, args.kb)

    for f in report.findings:
        if f.level in (ERROR, WARN):
            where = f" {f.case_id}" if f.case_id else ""
            print(f"[{f.level.upper()}]{where} {f.kind}: {f.message}")
    print(f"integrity: {len(report.errors)} error(s), {len(report.warnings)} flag(s) — "
          f"{'GREEN' if report.ok else 'FAILED'}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
