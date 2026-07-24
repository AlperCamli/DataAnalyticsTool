# TRANSPORT-PROOF ONLY — NOT BASELINE NUMBERS

Per ruling D-62 (2026-07-16, CP-2 gate amendment) and D-61:

- The five journeys in this artifact are recorded as **transport-proof** —
  evidence that the harness runs end-to-end (file-ingested records, R4–R6
  scoring, both correctness paths, ≥1 journey per condition). They ran
  **headless** (`claude -p`), one rep, on the manual journey-prompt variant.
- They are **not comparable with future runs** (different journey-prompt
  variant, n too small) and **must never be cited as with/without-KB
  evidence** or as any quantitative KB-value claim.
- Baseline v1 is CP-5's added exit criterion: the benchmark skill's first
  complete three-condition run (10 × 3 × ≥1 rep). MC-1's recall table and
  the enriched-vs-machine-vs-none comparison land there.
- Known inaccuracy in `results.json`: `run.notes` describes the interactive
  transport; these five ran headless (authoritative correction in D-61).
