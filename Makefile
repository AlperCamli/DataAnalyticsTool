# CP-3a core stack (core + Postgres + runner; see core/README.md).
# CP-4 adds the MCP surface: `make stack-mcp` arms /mcp + the dev IdP.

stack-up:    ## build + start the local job-protocol stack
	docker compose up -d --build

stack-mcp:   ## stack with the MCP server + dev OIDC provider armed (CP-4)
	CORE_MCP_ENABLED=1 docker compose up -d --build

stack-demo:  ## enqueue the no-credentials demo jobs and await results
	docker compose exec core sh -c 'node dist/cli.js enqueue --wait jobs/demo/*.json'

stack-live:  ## live overlay stack up + enqueue the example estate's three systems
	docker compose -f docker-compose.yml -f deploy/compose.live.yml up -d --build
	docker compose exec core sh -c 'node dist/cli.js enqueue --wait jobs/live/*.json'

stack-down:  ## stop the stack (keeps the pgdata volume; add -v yourself to wipe)
	docker compose down

drill:       ## staged drift drill (sync §9 / SO-4) through the real pipeline
	cd core && npx vitest run test/sync-drill.test.ts

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

.PHONY: stack-up stack-mcp stack-demo stack-live stack-down drill \
        conditions preflight ingest status score
