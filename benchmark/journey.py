"""Journey record — the per-case-per-rep run artifact (R3, skill-spec §8).

One record per journey, emitted by the runner and consumed by the scorer.
The shape is forward-compatible with the skill-spec §8 hand-off (resolved
refs, drafted statement, validation verdicts, execution result ref) and
carries the R3 fields the harness scores and keys on: case_id, condition,
rep, context reads, the agent's self-declared object set (recorded, never
scored — R4), the drafted request(s) with execution outcomes, token /
tool-call counts, model id, timestamps.

``Draft.validation`` is reserved for the ``validate_sql`` verdict that
lands with CP-4 (R6); until then it is ``None`` and the first-try
executable metric keys off execution success, not validation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


@dataclass
class ExecutionOutcome:
    ok: bool
    error: str | None = None
    row_count: int | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    result_ref: str | None = None  # checksum/pointer to the stored result
    elapsed_ms: float | None = None


@dataclass
class Draft:
    """One drafted request and what happened when (or if) it ran."""

    seq: int
    system: str
    request: Mapping[str, Any]  # {dialect, statement} | {dialect, operation, property, body}
    complete: bool = True       # a complete, executable request (vs an abandoned partial)
    final: bool = False         # part of the agent's answer set (scored for R4/R5)
    validation: Mapping[str, Any] | None = None  # reserved for validate_sql (CP-4)
    executed: bool = False
    outcome: ExecutionOutcome | None = None


@dataclass
class JourneyRecord:
    case_id: str
    condition: str
    rep: int
    model_id: str
    backend: str = "api"        # "api" (Backend A) | "claude-code" (Backend B); joins R8 key
    cost_usd: float | None = None  # total_cost_usd from the CLI (Backend B)
    session_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    context_reads: list[str] = field(default_factory=list)   # resolved refs (files / discovery)
    declared_objects: list[str] = field(default_factory=list)  # agent self-report; never scored
    drafts: list[Draft] = field(default_factory=list)
    tokens: dict[str, int] = field(default_factory=dict)
    tool_calls: int = 0
    notes: str = ""

    # -- helpers the scorer relies on --------------------------------------

    def final_drafts(self) -> list[Draft]:
        return [d for d in self.drafts if d.final]

    def first_complete_draft(self) -> Draft | None:
        for d in sorted(self.drafts, key=lambda d: d.seq):
            if d.complete:
                return d
        return None

    def final_result_for(self, system: str) -> ExecutionOutcome | None:
        """The agent's last successful final result for a system (its answer)."""
        chosen: ExecutionOutcome | None = None
        for d in sorted(self.drafts, key=lambda d: d.seq):
            if d.final and d.system == system and d.executed and d.outcome and d.outcome.ok:
                chosen = d.outcome
        return chosen

    # -- serialization (R8 artifact) --------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "JourneyRecord":
        drafts = [
            Draft(
                seq=d["seq"],
                system=d["system"],
                request=d["request"],
                complete=d.get("complete", True),
                final=d.get("final", False),
                validation=d.get("validation"),
                executed=d.get("executed", False),
                outcome=(
                    ExecutionOutcome(**d["outcome"]) if d.get("outcome") else None
                ),
            )
            for d in data.get("drafts", [])
        ]
        return cls(
            case_id=data["case_id"],
            condition=data["condition"],
            rep=data["rep"],
            model_id=data["model_id"],
            backend=data.get("backend", "api"),
            cost_usd=data.get("cost_usd"),
            session_id=data.get("session_id", ""),
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at", ""),
            context_reads=list(data.get("context_reads", [])),
            declared_objects=list(data.get("declared_objects", [])),
            drafts=drafts,
            tokens=dict(data.get("tokens", {})),
            tool_calls=data.get("tool_calls", 0),
            notes=data.get("notes", ""),
        )
