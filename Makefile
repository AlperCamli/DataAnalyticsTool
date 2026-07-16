# CP-2 manual-baseline kit (dev tooling; see OPERATOR.md).
#
# RUNS defaults to a directory OUTSIDE this repo on purpose: interactive
# Claude Code auto-loads CLAUDE.md from the cwd's directory ancestry, so a
# runs/ dir inside the repo would inject this repo's CLAUDE.md into every
# journey session (condition contamination). `conditions` preflights this.

PY   := .venv/bin/python
RUNS ?= $(HOME)/Desktop/cp2-runs

conditions:  ## build the three condition working dirs + manifest
	$(PY) -m benchmark.manual conditions --root $(RUNS)

preflight:   ## re-check isolation + no-stray-files invariants
	$(PY) -m benchmark.manual preflight --root $(RUNS)

ingest:      ## assemble R3 records from the executor JSONL logs
	$(PY) -m benchmark.manual ingest --root $(RUNS)

status:      ## coverage of the cases x conditions x reps grid
	$(PY) -m benchmark.manual status --root $(RUNS)

score:       ## validate + score records -> results/<run-id>/ (R8 + report)
	$(PY) -m benchmark.manual score --root $(RUNS) --out results

.PHONY: conditions preflight ingest status score
