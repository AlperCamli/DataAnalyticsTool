"""Deliverable 4 — journey scoring (R4-R6).

Three scores per journey, computed from the journey record and the golden:

* **R4 selection** — the scored object set is the FQNs extracted from the
  agent's *final executed* statement(s) (``fqn.SnapshotInventory.extract``),
  compared to the case's ``expected_objects`` for precision and recall. The
  agent's self-declared set is carried through and reported but never
  scored (agents misreport; parsed statements do not).
* **R5 correctness** — per golden leg (one per system), the agent's final
  result is compared to a golden result executed in the *same run*.
  Byte-stable cases take the checksum mode; time-unstable cases take the
  structural mode (shape + tolerant values), per ``canonical.compare_results``.
  A case is correct iff every scored leg is correct.
* **R6 executable** — first-try executable = the first *complete* drafted
  request executed without error. ``validate_sql`` does not exist yet; when
  CP-4 lands this refines to validate-pass (noted on the score, not
  silently assumed).

Precision is ``None`` (undefined, not 0) when the agent executed nothing to
score — distinguishing "selected the wrong objects" from "selected none".
The aggregator excludes undefined precision from means and counts it.

Correctness needs a same-run golden. When none is supplied (the
execution-deferred state, or CI's zero-execution path) the correctness
score is marked *unscored* rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from benchmark.canonical import ResultComparison, compare_results
from benchmark.fqn import SnapshotInventory
from benchmark.journey import JourneyRecord
from benchmark.suite import Case


@dataclass(frozen=True)
class LegResult:
    """A golden leg's result table, executed in-run for correctness (R5)."""

    columns: list[str]
    rows: list[list]


@dataclass(frozen=True)
class SelectionScore:
    expected: list[str]
    scored: list[str]        # FQNs from the final executed statement(s)
    declared: list[str]      # agent self-report — recorded, NEVER scored
    true_positives: list[str]
    false_positives: list[str]
    false_negatives: list[str]
    precision: float | None  # None when nothing was executed to score
    recall: float
    parse_failures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutableScore:
    first_try_executable: bool
    first_seq: int | None = None
    executed: bool = False
    error: str | None = None
    reason: str | None = None
    validation_note: str = (
        "validate_sql unavailable (CP-4); first-try executable keys off "
        "execution success per R6"
    )


@dataclass(frozen=True)
class LegCorrectness:
    system: str
    scored: bool
    correct: bool | None
    comparison: ResultComparison | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CorrectnessScore:
    scored: bool
    correct: bool | None
    legs: list[LegCorrectness] = field(default_factory=list)
    mode: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ScoredJourney:
    case_id: str
    condition: str
    rep: int
    selection: SelectionScore
    executable: ExecutableScore
    correctness: CorrectnessScore


def score_selection(
    record: JourneyRecord, case: Case, inventory: SnapshotInventory
) -> SelectionScore:
    scored: set[str] = set()
    parse_failures: list[str] = []
    for draft in record.final_drafts():
        extracted = inventory.extract(draft.system, draft.request)
        if not extracted.parse_ok:
            parse_failures.append(draft.system)
        scored |= set(extracted.fqns)
    expected = set(case.expected_objects)
    tp = scored & expected
    precision = (len(tp) / len(scored)) if scored else None
    recall = (len(tp) / len(expected)) if expected else 1.0
    return SelectionScore(
        expected=sorted(expected),
        scored=sorted(scored),
        declared=sorted(set(record.declared_objects)),
        true_positives=sorted(tp),
        false_positives=sorted(scored - expected),
        false_negatives=sorted(expected - scored),
        precision=precision,
        recall=recall,
        parse_failures=parse_failures,
    )


def score_executable(record: JourneyRecord) -> ExecutableScore:
    first = record.first_complete_draft()
    if first is None:
        return ExecutableScore(False, reason="no complete drafted request")
    ok = first.executed and first.outcome is not None and first.outcome.ok
    return ExecutableScore(
        first_try_executable=ok,
        first_seq=first.seq,
        executed=first.executed,
        error=first.outcome.error if first.outcome else None,
    )


def score_correctness(
    record: JourneyRecord,
    case: Case,
    golden_results: Mapping[str, LegResult] | None,
) -> CorrectnessScore:
    if golden_results is None:
        return CorrectnessScore(False, None, reason="no same-run golden executed")
    legs: list[LegCorrectness] = []
    for leg in case.golden:
        system = leg.system
        golden = golden_results.get(system)
        agent = record.final_result_for(system)
        if golden is None:
            legs.append(LegCorrectness(system, False, None, reason="no golden result for system"))
            continue
        if agent is None:
            legs.append(LegCorrectness(system, True, False, reason="agent produced no result"))
            continue
        comparison = compare_results(
            byte_stable=case.is_byte_stable,
            golden_columns=golden.columns,
            golden_rows=golden.rows,
            agent_columns=agent.columns,
            agent_rows=agent.rows,
        )
        legs.append(LegCorrectness(system, True, comparison.correct, comparison))
    scored_legs = [leg for leg in legs if leg.scored]
    if not scored_legs:
        return CorrectnessScore(False, None, legs=legs, reason="no leg had a golden result")
    correct = all(leg.correct for leg in scored_legs)
    return CorrectnessScore(
        scored=True,
        correct=correct,
        legs=legs,
        mode="checksum" if case.is_byte_stable else "structural",
    )


def score_journey(
    record: JourneyRecord,
    case: Case,
    inventory: SnapshotInventory,
    golden_results: Mapping[str, LegResult] | None = None,
) -> ScoredJourney:
    return ScoredJourney(
        case_id=record.case_id,
        condition=record.condition,
        rep=record.rep,
        selection=score_selection(record, case, inventory),
        executable=score_executable(record),
        correctness=score_correctness(record, case, golden_results),
    )
