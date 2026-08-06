# CP-3a core stack (core + Postgres + runner; see core/README.md).
# CP-4 adds the MCP surface: `make stack-mcp` arms /mcp + the dev IdP.

stack-up:    ## build + start the local job-protocol stack
	@sh deploy/check-toggle-env.sh
	docker compose up -d --build

stack-mcp:   ## stack with the MCP server + dev OIDC provider armed (CP-4)
	@sh deploy/check-toggle-env.sh
	docker compose -f docker-compose.yml -f deploy/compose.mcp.yml up -d --build

stack-demo:  ## enqueue the no-credentials demo jobs and await results
	docker compose exec core sh -c 'node dist/cli.js enqueue --wait jobs/demo/*.json'

# No `set -a; . .secrets/sync.env` any more. That line existed because
# docker-compose.yml declared the toggles and SYNC_* under `environment:`
# as ${VAR:-default}, and compose ranks `environment:` above `env_file:` —
# so an unexported .secrets/sync.env yielded SYNC_ENABLED=0 and a stack
# that looked healthy and never synced (D-84.2; the pilot ran two days that
# way, and D-109.8 repeated it with the dashboard). Since D-110.2 those
# values live in env files and the overlay's file simply wins, so the
# overlay says what it means. SYNC_PLATFORM_COMMIT stays interpolated —
# only the shell knows the commit — and feeds §10 wheel provenance.
stack-live:  ## live overlay stack up + enqueue the example estate's three systems
	@sh deploy/check-toggle-env.sh
	SYNC_PLATFORM_COMMIT=$$(git rev-parse HEAD) \
	  docker compose -f docker-compose.yml -f deploy/compose.live.yml up -d --build
	docker compose exec core sh -c 'node dist/cli.js enqueue --wait jobs/live/*.json'

# Same as stack-live, on the PERSISTENT vault (A-4). Use this one once the
# pilot's secrets are in vault: `stack-live` starts the base stack's
# dev-mode vault, which is in-memory and therefore empty, and the core
# would refuse to boot naming the first reference it could not resolve.
# That failure is loud by design — but a target that cannot produce it is
# better than a loud failure you have to diagnose at 09:00. Vault seals on
# restart; unseal it before this, or `/healthz` will say `sealed: true`.
stack-pilot: ## live stack on the persistent vault (A-4; unseal vault first)
	@sh deploy/check-toggle-env.sh
	SYNC_PLATFORM_COMMIT=$$(git rev-parse HEAD) \
	  docker compose -f docker-compose.yml \
	                 -f deploy/compose.vault-file.yml \
	                 -f deploy/compose.live.yml up -d --build

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

# CP-5 skill conformance scenarios (D-78 layer (b), the AS-9/10/12 gate
# evidence). Re-run on any skill edit — the fixture deployment needs no
# example estate. Requires a postgres admin URL (a throwaway container is
# fine) and the `claude` CLI on PATH.
#
#   ADMIN_DB defaults to the local compose postgres; override for a
#   throwaway container. FIXTURE is the connection file the launcher writes.
ADMIN_DB ?= postgres://postgres:contextlayer@127.0.0.1:5433/postgres
FIXTURE  ?= /tmp/cl-fixture.json
SCEN_MODEL ?= claude-opus-4-8

fixture-up:  ## stand up the fixture deployment (keeps running; Ctrl-C to stop)
	cd core && CORE_TEST_DATABASE_URL="$(ADMIN_DB)" CORE_TEST_PYTHON="$(abspath $(PY))" \
	  node_modules/.bin/vite-node test/fixture-deployment.ts -- --out "$(FIXTURE)" --with-execution

scenarios:   ## run AS-9/10/12 against a running fixture -> results/cp5-scenarios/
	$(PY) -m tools.skill_scenarios --connection "$(FIXTURE)" \
	  --model $(SCEN_MODEL) --out results/cp5-scenarios

powerbi-preflight:  ## verify the D-91.7 Power BI SP provisioning (STOP-A gate)
	$(PY) -m connectors.powerbi.preflight

.PHONY: stack-up stack-mcp stack-demo stack-live stack-down drill \
        conditions preflight ingest status score fixture-up scenarios \
        powerbi-preflight
