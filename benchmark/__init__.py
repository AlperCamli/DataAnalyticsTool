"""CVBuilder golden-benchmark harness (CP-2).

Ingests the customer-verified suite (``benchmark-seed-v0.yaml``), builds
the three context conditions (R1), runs journeys through a guardrailed
Anthropic tool loop (R2/R3), and scores selection + correctness + first-try
executable rate (R4-R6) into versioned results artifacts (R8).

The suite YAML is a read-only input (schema as authored); this package
never mutates it. Determinism is a contract everywhere it can be one:
same suite + same snapshots -> same validation verdict and same scored
object sets.
"""

__all__ = ["SUITE_VERSION_KEY"]

SUITE_VERSION_KEY = "suite_version"
