# Core service — job API + queue (CP-3a) + sync orchestrator (CP-3b)

The TypeScript core (platform-architecture §3/§4): the job-protocol
server runners speak to, the queue behind it, the ops schema (accepted
snapshots, runs, health events), and — since CP-3b — the sync
orchestrator (sync-orchestrator spec): triggers (scheduler tick §4.1,
webhook §4.2, admin-CLI manual §4.3), the §5 drift-run state machine,
single-flight + coalescing (§7), freshness monitoring (§8), and the §10
vendored-wheel carry.

**What it never does:** parse, re-serialize, or reason about snapshot
or KB content. Deliveries go byte-for-byte to the Python delivery gate
(`python -m snapshot.accept`, ruling C1), and every deterministic sync
artifact — diff, severity finalization, lineage re-derivation,
contamination scan, renders, front-matter status writes — is produced by
the Python package's CLIs (`snapshot.diff`, `lineage`,
`lineage.severity`, `lineage.scan`, `generator.render`,
`generator.statuses` — ruling C2). The TS side is orchestration only:
pinning, sequencing, git/PR mechanics (shell git + provider REST behind
push-branch / open+close-PR, ruling D2), supersede, run records, health.
Scope fence: no MCP server, no SSO (CP-4), no dashboard UI, no
auto-merge of any PR (SO-B: label only).

## Layout

- `src/` — service (`index.ts`), job API + webhook (`server.ts`), queue
  SQL (`queue.ts`), §4.2 type registry, migrations runner, delivery gate
  bridge (`validator.ts`), sync: triggers/policy/scheduler/freshness,
  run pipeline (`pipeline.ts`), git+PR (`gitkb.ts`), changelog, wheel
  carry, ops+admin CLI (`cli.ts`)
- `migrations/` — versioned ops schema: jobs, accepted_snapshots, runs,
  health_events, sync registry/hooks/pending/freshness (0005)
- `test/` — protocol conformance (JC table), queue property tests
  (fast-check), e2e with real runner processes, sync conformance
  (SO-1..SO-12; the drill fixture runs the real pipeline against a
  local scratch KB repo)

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

Sync (all `SYNC_*`; off unless `SYNC_ENABLED`): `SYNC_GIT_REMOTE`,
`SYNC_GIT_TOKEN` (fine-grained PAT for the `contextlayer-sync` machine
account, D2), `SYNC_GIT_PROVIDER` (`github`|`local`),
`SYNC_GIT_BASE_BRANCH`, `SYNC_PYTHON`, `SYNC_WORKDIR`, `SYNC_TICK_S`
(3600), `SYNC_ACQUISITION_BUDGET_S` (7200; sync-policy.yaml
`acquisition_budget` overrides, SO-D), `SYNC_PR_RETRIES` (3),
`SYNC_HOOK_BODY_MAX` (64 KiB), `SYNC_WHEEL_PATH` (file or a directory
holding one wheel), `SYNC_PLATFORM_COMMIT`, `SYNC_WHEEL_BUILT`.

Admin CLI (ruling E2 — the Connections-UI stand-in):
`cli.js sync systems set FILE · hook set SYSTEM · now [SYSTEM…] ·
freshness · runs [N]`. Hook secrets are printed once and stored as
sha256; rotation takes effect without restart.

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
