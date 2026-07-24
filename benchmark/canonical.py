"""Canonical CSV, checksum, and numeric-tolerant result comparison (R5).

Packet rules for the canonical CSV of a result table: a header line of
column names, then the data rows sorted lexicographically, UTF-8 encoded
with ``\\n`` line terminators (one after every line, including the last).
The result checksum is ``sha256:<hex>`` over those bytes — the same
``sha256:`` shape the snapshot layer uses for hashes.

Two correctness modes, per R5:

* **byte-stable** cases (closed windows over immutable rows) reproduce a
  stable canonical CSV; correctness is checksum identity. Only integer /
  date / string values ever reach this path, so the byte form is exact.
* **time-unstable** cases (source mutates in place, or matures
  retroactively) are never byte-compared to a frozen result. They are
  compared value-wise against a *same-run* golden re-execution: shapes
  must match and values agree within tolerance — exact for integers,
  ``1e-9`` relative for floats. Small between-execution integer drift on a
  live-mutating source is reported as drift, not silently absorbed.

Comparison here is header-independent for the value path: an agent that
aliases a column differently still produces the same value rows. The
strict packet checksum (which includes the header) is reported alongside.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Sequence

FLOAT_REL_TOL = 1e-9


def _render_cell(value: Any) -> str:
    """Render one cell to its canonical CSV string.

    ``None`` -> empty field; booleans -> ``true``/``false``; integers and
    floats -> their literal form; ``Decimal`` -> normalized digits;
    dates/datetimes -> ISO 8601; everything else -> ``str`` then escaped.
    Floats never reach the byte-stable checksum path (those results are
    integer/date/string), but they still need a deterministic rendering
    for the value path's canonical ordering.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, Decimal):
        # Normalize so 12.30 and 12.3 render identically; avoid exponent
        # form for the small magnitudes report metrics produce.
        normalized = value.normalize()
        return format(normalized, "f")
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    return _csv_escape(str(value))


def _csv_escape(text: str) -> str:
    """RFC-4180 minimal quoting: quote iff the field needs it."""
    if any(ch in text for ch in (",", '"', "\n", "\r")):
        return '"' + text.replace('"', '""') + '"'
    return text


def canonical_csv(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """Render a result table to its packet-canonical CSV string.

    Header first (never sorted); data rows sorted lexicographically on the
    rendered line so API tie-order among equal-rank rows is neutralized
    (RB-03's note). Trailing newline after every line.
    """
    header = ",".join(_csv_escape(str(c)) for c in columns)
    data_lines = [
        ",".join(_render_cell(cell) for cell in row) for row in rows
    ]
    data_lines.sort()
    return "".join(line + "\n" for line in (header, *data_lines))


def csv_checksum(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """``sha256:<hex>`` over the packet-canonical CSV bytes."""
    text = canonical_csv(columns, rows)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def values_equal(a: Any, b: Any, *, float_rel_tol: float = FLOAT_REL_TOL) -> bool:
    """R5 value equality: integers exact, floats ``1e-9`` relative.

    Two integers must match exactly. If either side is a float/Decimal the
    pair is numeric and compared with relative tolerance (absolute near
    zero). Non-numeric values compare by their canonical rendering, so a
    date and its ISO string are equal.
    """
    if a is None or b is None:
        return a is None and b is None
    if _is_number(a) and _is_number(b):
        a_int = isinstance(a, int)
        b_int = isinstance(b, int)
        if a_int and b_int:
            return a == b
        fa, fb = float(a), float(b)
        if fa == fb:
            return True
        scale = max(abs(fa), abs(fb))
        return abs(fa - fb) <= float_rel_tol * scale if scale else abs(fa - fb) <= float_rel_tol
    return _render_cell(a) == _render_cell(b)


def _row_key(row: Sequence[Any]) -> str:
    return ",".join(_render_cell(c) for c in row)


@dataclass(frozen=True)
class ResultComparison:
    """Verdict of comparing an agent result against a golden result.

    ``correct`` is the mode-appropriate pass signal: checksum identity for
    byte-stable cases, shape + tolerant value agreement for structural
    ones. The finer fields are recorded so the artifact shows *why*.
    """

    mode: str  # "checksum" | "structural"
    correct: bool
    shape_match: bool
    golden_shape: tuple[int, int]  # (n_columns, n_rows)
    agent_shape: tuple[int, int]
    checksum_match: bool
    golden_checksum: str
    agent_checksum: str
    values_match: bool  # header-independent value-multiset agreement (tolerant)
    drift: bool = False  # unstable ints differed between golden/agent executions
    notes: tuple[str, ...] = field(default_factory=tuple)


def _values_multiset_match(
    columns_g: Sequence[str],
    rows_g: Sequence[Sequence[Any]],
    rows_a: Sequence[Sequence[Any]],
) -> tuple[bool, bool]:
    """Header-independent, order-independent value agreement.

    Returns ``(values_match, integer_drift)``. Rows are aligned by sorted
    canonical key; each aligned pair is compared cell-wise with R5
    tolerance. ``integer_drift`` flags the specific case where the only
    disagreements are between integers (the live-mutation signature),
    distinguishing benign drift from a structural error.
    """
    if len(rows_g) != len(rows_a):
        return False, False
    if any(len(r) != len(columns_g) for r in rows_g):
        return False, False
    if rows_a and any(len(r) != len(columns_g) for r in rows_a):
        return False, False
    sorted_g = sorted(rows_g, key=_row_key)
    sorted_a = sorted(rows_a, key=_row_key)
    all_match = True
    only_int_diffs = True
    for rg, ra in zip(sorted_g, sorted_a):
        for cg, ca in zip(rg, ra):
            if not values_equal(cg, ca):
                all_match = False
                both_int = (
                    isinstance(cg, int) and not isinstance(cg, bool)
                    and isinstance(ca, int) and not isinstance(ca, bool)
                )
                if not both_int:
                    only_int_diffs = False
    return all_match, (not all_match and only_int_diffs)


def compare_results(
    *,
    byte_stable: bool,
    golden_columns: Sequence[str],
    golden_rows: Sequence[Sequence[Any]],
    agent_columns: Sequence[str],
    agent_rows: Sequence[Sequence[Any]],
) -> ResultComparison:
    """Compare an agent result against a golden result under R5.

    ``byte_stable`` selects the mode: checksum identity (packet-canonical
    CSV, header included) for byte-stable cases; shape + tolerant value
    agreement for structural (time-unstable) cases, where the golden is a
    same-run re-execution.
    """
    golden_shape = (len(golden_columns), len(golden_rows))
    agent_shape = (len(agent_columns), len(agent_rows))
    shape_match = golden_shape == agent_shape

    golden_checksum = csv_checksum(golden_columns, golden_rows)
    agent_checksum = csv_checksum(agent_columns, agent_rows)
    checksum_match = golden_checksum == agent_checksum

    values_match, drift = _values_multiset_match(
        golden_columns, golden_rows, agent_rows
    )

    notes: list[str] = []
    if byte_stable:
        correct = checksum_match
        mode = "checksum"
        if not checksum_match and values_match:
            notes.append(
                "values agree but packet checksum differs (column aliasing "
                "or ordering) — data correct, byte form not identical"
            )
    else:
        mode = "structural"
        correct = shape_match and values_match
        if shape_match and not values_match and drift:
            notes.append(
                "integer counts differ between same-run golden and agent "
                "executions on a live-mutating source — drift, not error"
            )
    return ResultComparison(
        mode=mode,
        correct=correct,
        shape_match=shape_match,
        golden_shape=golden_shape,
        agent_shape=agent_shape,
        checksum_match=checksum_match,
        golden_checksum=golden_checksum,
        agent_checksum=agent_checksum,
        values_match=values_match,
        drift=drift,
        notes=tuple(notes),
    )
