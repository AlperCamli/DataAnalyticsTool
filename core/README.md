# Core service — job API + Postgres-backed queue (CP-3a)

The TypeScript core (platform-architecture §3/§4): the job-protocol
server runners speak to, the queue behind it, and the ops schema
(accepted snapshots, runs, health events). Implements the job protocol
spec v1 — claim/lease/heartbeat/deliver (§5–§6), dedupe (§8), J-5
deferrals, J-6 delivery validation, dead-lettering into `health_events`.

**What it never does:** parse, re-serialize, or reason about snapshot
content. Deliveries go byte-for-byte to the Python delivery gate
(`python -m snapshot.accept` — validation + §6 canonicalization from the
1.1 library, ruling C1), and the returned canonical bytes are what
`accepted_snapshots.body` stores. Scope fence: no orchestrator pipeline,
no webhook endpoint, no scheduler, no diff/scan/PR logic (CP-3b), no
auth beyond per-runner bearer tokens (SSO is CP-4).

## Layout

- `src/` — service (`index.ts`), job API (`server.ts`), queue SQL
  (`queue.ts`), §4.2 type registry, migrations runner, Python delivery
  gate bridge (`validator.ts`), ops CLI (`cli.ts`)
- `migrations/` — versioned ops schema: jobs, accepted_snapshots, runs
  (sync spec §5.11 shape, written from CP-3b), health_events
- `test/` — protocol conformance (JC table), queue property tests
  (fast-check), e2e against real Python runner processes

## Run it

```sh
docker compose up -d --build          # core + Postgres + runner
make stack-demo                       # enqueue demo jobs, await results
```

Live mode (this machine only; env-gated): populate `.secrets/runner.env`
and `.secrets/core-live/*.json` (shapes in `deploy/jobs/live-example/`),
then `make stack-live`.

## Configuration (env)

`CORE_DATABASE_URL`, `CORE_RUNNER_TOKENS` (`runner-id=token,…`),
`CORE_VALIDATOR_CMD`, `CORE_PORT` (8100), `CORE_MIGRATE_ON_START`, plus
§5 tunables (`CORE_LEASE_TTL_S`, `CORE_RETRY_BASE_S`, `CORE_RETRY_CAP_S`,
`CORE_MAX_DEFERRALS`, `CORE_RESULT_MAX_BYTES`, `CORE_SNAPSHOT_RETENTION`).

## Tests

```sh
npm ci && npm test    # spins its own postgres:16 container (or set
                      # CORE_TEST_DATABASE_URL); the delivery gate and
                      # e2e runner use the repo venv, or CORE_TEST_PYTHON
```

Conformance status (job spec §10): JC-1..JC-9 implemented (JC-4/JC-8 in
`test/e2e.test.ts` with real runner processes and a canary secret).
**JC-10 deferred** — interactive-result relay to a blocked producer has
no producer until the execution gateway (CP-6); the queue machinery it
rides on (interactive class, priority lane) is in place and tested.
Interactive per-system concurrency limits (§8) are likewise deferred to
the gateway's execution policy.
