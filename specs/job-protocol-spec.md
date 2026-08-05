# Contract Specification — Connector Job Protocol (v1)

Status: v1 draft for implementation. Companion to `snapshot-schema-spec.md`; implements the "job protocol" boundary named in `platform-architecture.md` §1–§3 ("a connector is any process that emits valid snapshot JSON and speaks the job protocol") and the sync-trigger policies of `high-level-requirements-and-user-journeys.md` §8 P1. The reliability requirements it enforces (idempotent, resumable, dead-lettering, health-surfaced) are those of platform-architecture §2.2.

The job protocol is the *second* half of the connector contract: the snapshot spec defines *what* a connector produces; this spec defines *how* work reaches a connector and how results, progress, and failures travel back.

---

## 1. Scope

**In scope:** the actors and trust boundaries; the job model (types, classes, states, leases); the HTTP wire protocol; error taxonomy and retry/dead-letter semantics; credential handling; dedup/concurrency rules; protocol versioning; conformance tests.

**Out of scope:** the snapshot document format (snapshot spec), capability interface *signatures* (capability spec — this spec treats capability invocations as opaque payloads/results), MCP tool semantics, and the internal SQL of the Postgres queue (implementation detail; observable behavior only is normative).

## 2. Design rulings

| # | Ruling | Rationale |
|---|---|---|
| J-1 | The Postgres queue is core-internal; connectors speak only HTTP+JSON to the core's **job API** | Language-agnostic contract; no DB coupling or DB credentials in connector containers; queue schema can evolve freely |
| J-2 | Runners **poll** (long-poll claim); the core never connects inbound to a runner | Outbound-only networking from runners; identical under Compose and K8s; no Docker-socket orchestration; firewall-friendly |
| J-3 | One protocol, two **job classes** — `batch` and `interactive` — differing only in priority lane and deadline defaults | Sync jobs and gateway-driven execute/publish share one machinery to specify, test, and security-review; internal `LISTEN/NOTIFY` gives interactive claims sub-second latency without a broker |
| J-4 | Job payloads carry **credential references only**; the runner resolves them against the customer vault at execution time under its own vault identity | Secrets never transit the core, the queue, or job logs (platform principle: references, never raw secrets) |
| J-5 | Quota exhaustion is a **deferral**, not a failure: `retry_after` reschedules without consuming a retry attempt | GA4 quotas make this distinction load-bearing from day one; conflating it with failure would dead-letter healthy syncs |
| J-6 | The core validates delivered results **on receipt** (snapshots against the snapshot JSON Schema); invalid delivery fails the job non-retryably | Contract enforcement is server-side, like everything else in the platform |
| J-7 | Jobs are **idempotent by contract**; every job may be re-executed after a lost lease with no side effects beyond re-delivery | Resumability without distributed transactions: at-least-once execution + idempotent work + last-delivery-wins |
| J-8 | Runner ↔ core authentication uses per-runner bearer tokens (vault-referenced), rotatable without redeploying the core | Simple, auditable; mTLS is a deployment option on top, not a protocol requirement |

## 3. Actors and trust boundaries

```
┌── core (TypeScript) ──────────────────────────────┐
│ producers: sync orchestrator (schedule/webhook),  │
│   execution gateway, dashboard (test-connection)  │
│ job API  ◄── HTTPS, bearer token ──┐              │
│ Postgres queue (internal)          │              │
└────────────────────────────────────┼──────────────┘
                                     │ outbound only
                     ┌───────────────┴───────────────┐
                     │ runner (Python SDK container)  │
                     │  - declares connectors+classes │
                     │  - claims, heartbeats, works,  │
                     │    delivers / fails            │
                     │  - resolves credential refs ───┼──► customer vault
                     └────────────────┬───────────────┘
                                      └──► sources (Supabase, GA4, GSC, …)
```

**Producers** are core-internal components that enqueue jobs; they never speak this protocol. **Runners** are the only protocol clients. A runner is a long-running process built on the connector SDK (or any conformant implementation) that hosts one or more connector plugins and declares, at claim time, which `(connector, version)` pairs and which job classes it can execute. Multiple runner replicas may run concurrently; the lease mechanism (§5) makes this safe.

## 4. Job model

### 4.1 Job record (as visible through the protocol)

```json
{
  "job_id": "01J9…",
  "type": "snapshot",
  "class": "batch",
  "system": "supabase",
  "connector": { "name": "postgres", "version_constraint": ">=0.3 <0.4" },
  "payload": { "config": { }, "credentials": [ {"ref": "vault://…"} ] },
  "priority": 50,
  "attempt": 1,
  "max_attempts": 5,
  "deadline_s": 3600,
  "created_at": "2026-07-11T02:00:00Z",
  "trigger": { "kind": "schedule", "detail": "nightly" }
}
```

`trigger.kind` ∈ `schedule | webhook | manual | gateway | dashboard` — recorded for audit and surfaced in health feeds, so every KB change and every execution remains attributable to its cause (HLR §5 J2).

### 4.2 Job type registry (v1)

| Type | Class | Capability invoked | Result delivered |
|---|---|---|---|
| `snapshot` | batch | `MetadataProvider.snapshot` | Snapshot document (validated per J-6) |
| `harvest` | batch | `KnowledgeProvider.harvest` | `SourceDocument[]` + provenance |
| `lineage` | batch | `LineageProvider.lineage` | Lineage edge set (lineage-format spec) |
| `usage` | batch | `UsageProvider.usage` | `UsageStats` |
| `test_connection` | interactive | connector-defined probe | Health verdict + diagnostics |
| `execute` | interactive | `QueryExecutor.execute` | Result set (capped) or error |
| `publish` | interactive | `Publisher.publish` | `PublishResult` |

Registry growth is additive; runners skip claim-offers for types they don't declare. Whether the core short-circuits `execute` natively for engines it can drive directly is an implementation optimization behind the same contract (see JP-1, §11).

**Class defaults:** batch — `priority 50`, `deadline_s 3600`, `max_attempts 5`; interactive — `priority 10` (lower = sooner), `deadline_s` derived from the gateway guardrail (statement timeout + margin), `max_attempts 1` (the waiting caller retries, not the queue).

### 4.3 State machine

```
            ┌────────────────────────── retry (backoff) ───────────────┐
            ▼                                                          │
 queued ─ claim ─► leased ─ start ─► running ─┬─ complete ─► succeeded │
   ▲                 │                        ├─ fail(retryable) ──────┤
   │                 │ lease expiry           ├─ fail(non-retryable) ─► dead-lettered
   │                 └────────────────────────┤ (also: attempts exhausted)
   │ defer(retry_after)                       ├─ defer ─► queued (attempt NOT incremented)
   └──────────────────────────────────────────┴─ cancelled
```

One additive terminal state joins the diagram by the D-106.2 amendment (§5): `leased/running ─ defer ─► coalesced`, taken **only** when a duplicate for the same `(system, type)` is already queued — the deferring instance ends there and the queued job carries the work forward.

Transitions are effected only via the wire calls in §6 plus two core-side events: **lease expiry** (missed heartbeats → job returns to `queued`, `attempt+1`) and **cancellation** (producer sets `cancel_requested`; the runner learns of it in its next heartbeat response and must stop and acknowledge within one heartbeat interval).

## 5. Leases, heartbeats, retries

- **Lease:** a successful claim grants an exclusive lease of `lease_ttl_s` (default 60). Only the lease holder may call `start/heartbeat/complete/fail/defer` for that job; calls with a stale lease token are rejected `409 lease_lost`, and the runner must abandon the work (J-7 makes the subsequent re-execution safe).
- **Heartbeat:** required at least every `lease_ttl_s / 2`; each extends the lease by `lease_ttl_s` and may carry progress `{phase, percent?, message?}`, surfaced live in the Connections module.
- **Retry backoff:** on retryable failure or lease expiry, requeue delay = `min(base * 2^(attempt-1), cap)` with ±20% jitter; defaults `base 30s`, `cap 30m`.
- **Deferral (J-5):** `defer` requeues with `not_before = now + retry_after_s`, attempt unchanged. A job may defer at most `max_deferrals` (default 20) before the core converts further deferrals into retryable failures — a stuck quota shows up in health rather than deferring forever.
- **Dead-letter:** non-retryable failure or exhausted attempts. Dead-lettered jobs are visible in the dashboard health feed with full error detail and are manually re-enqueueable (new job, `attempt 1`, same payload, `trigger.kind = manual`).

**Amendment (D-106.2, 2026-08-05) — deferral into a queued duplicate: coalesce.** A leased batch job that defers while a duplicate for its `(system, type)` is already queued cannot return to `queued` — §8 permits exactly one queued batch job per key. Nothing about the deferring job failed (J-5: quota exhaustion is a deferral, not a failure), so it is neither dead-lettered nor charged a retry. It **coalesces**: the deferred instance terminates in the additive terminal state `coalesced` — no result delivered, no `error` recorded, `finished_at` set, and the survivor named in its `result_meta` — and the queued job survives, adopting **the later `not_before` of the two**. Adopting the later time is the load-bearing half: the deferral's `retry_after_s` is a statement about the source ("the quota resets in an hour"), and a survivor released at its own earlier time would walk straight back into the same wall. Trigger history merges into the survivor exactly as a requeue's absorb does (§8), so no accepted trigger loses its record. Deferral accounting is unchanged: the terminating instance does not increment `deferrals`, the survivor keeps its own count, and a deferral *past* the §5 cap converts to a retryable failure before this rule is reached (that path already absorbs the follower). Interactive jobs are never deduped and therefore never coalesce. Additive: `coalesced` is a new terminal state and a new `status` value in the §6.6 response; a client that does not know it treats it as terminal (§9).

## 6. Wire protocol

HTTP/1.1+ over TLS. All requests carry `Authorization: Bearer <runner-token>` and `X-CL-Protocol-Version: 1`. Bodies are JSON (`Content-Type: application/json`). Unknown response fields must be ignored (additive evolution, mirrors snapshot S-7).

**Amendment (D-66.1 / security review #1 P-A, 2026-07-17) — authentication split.** Runner bearer tokens authorize **only** the runner protocol: `claim` (§6.1), `start` (§6.2), `heartbeat` (§6.3), `complete` (§6.4), `fail` (§6.5), `defer` (§6.6). The producer/ops/read surface — job enqueue and cancellation, job reads, `/v1/snapshots*`, `/v1/health-events`, `/v1/runs`, and every other operational read — requires a **platform identity**: an OIDC identity resolved per call against the customer IdP (MCP spec §3) carrying an operator role, or a statically configured service identity distinct from the runner token set. A runner token presented to any producer/ops/read endpoint is denied. Rationale: a leaked runner token's blast radius is bounded to job claims within its declared connectors — it can no longer enqueue or cancel work, nor read stored snapshot bodies, run records, or health events (review finding F1). The J-8 rotation property applies to both token sets. Additive: the runner-protocol surface and its semantics are unchanged.

### 6.1 `POST /v1/jobs/claim` — long-poll claim

```json
{
  "runner_id": "runner-a1",
  "connectors": [ {"name": "postgres", "version": "0.3.1"},
                  {"name": "ga4", "version": "0.2.0"} ],
  "classes": ["batch", "interactive"],
  "wait_s": 25
}
```

The core holds the request up to `wait_s` (max 30) until a matching job exists, then responds `200` with the job record (§4.1) **plus** `lease: {token, expires_at}` — or `204` if nothing matched. Matching: job's `connector.name` declared by the runner **and** declared version satisfies `version_constraint` **and** class declared. Priority order: lower `priority` first, then `created_at`. Internally the claim is `SELECT … FOR UPDATE SKIP LOCKED` woken by `LISTEN/NOTIFY` — normative only in its effect: at most one live lease per job, sub-second interactive claims.

A runner should keep exactly one outstanding claim call per worker slot; slot count is the runner's own concurrency configuration.

### 6.2 `POST /v1/jobs/{job_id}/start`

Body: `{ "lease_token": "…" }`. Marks `running`; the point after which the runner must have resolved credentials (J-4) and begun work. Response echoes `cancel_requested`.

### 6.3 `POST /v1/jobs/{job_id}/heartbeat`

```json
{ "lease_token": "…", "progress": {"phase": "introspecting", "percent": 40, "message": "42/105 tables"} }
```

Response: `{ "lease": {"token": "…", "expires_at": "…"}, "cancel_requested": false }`. On `cancel_requested: true` the runner stops, then calls `fail` with code `cancelled`.

### 6.4 `POST /v1/jobs/{job_id}/complete`

```json
{ "lease_token": "…", "result": { /* type-specific */ } }
```

For `snapshot`: `result` is the snapshot document itself, inline. The core validates it against the snapshot JSON Schema **and** recomputes a sample of `schema_hash`es before acking (J-6; snapshot C-4 server-side). Validation failure → `422`, job transitions to `dead-lettered` with `validation_error` — the runner treats `422` as final, not retryable. Result size cap: 64 MB (metadata, not data; see JP-3). Success → `200 {"status":"succeeded"}`. Delivery is **last-write-wins**: if a lease was lost and two attempts both complete, the later validated delivery replaces the earlier (safe under J-7 because both describe the same source state or a newer one).

For `execute`/`publish`/`test_connection`: `result` is the capability's result envelope (capability spec); the core relays it to the blocked producer (gateway) via internal notification.

### 6.5 `POST /v1/jobs/{job_id}/fail`

```json
{ "lease_token": "…",
  "error": { "code": "source_unavailable", "message": "connection refused",
             "retryable": true, "detail": { } } }
```

### 6.6 `POST /v1/jobs/{job_id}/defer`

```json
{ "lease_token": "…", "retry_after_s": 3600,
  "reason": {"code": "quota", "message": "GA4 tokens/day exhausted"} }
```

### 6.7 Error taxonomy (normative `error.code` values)

| Code | Retryable | Typical cause | Health surfacing |
|---|---|---|---|
| `config_error` | no | Invalid source config, unsupported mode | Connection marked misconfigured |
| `auth_error` | no | Credential invalid/expired at source or vault | Connection prompts re-auth (maps to the dashboard/`suggest re-auth` flow) |
| `source_unavailable` | yes | Network, source down, replica lag | Retry silently until threshold, then health warning |
| `quota` | — (use `defer`) | API quota/rate ceiling | Shown as deferred, not failing |
| `validation_error` | no | Core rejected delivered result (J-6) | Dead-letter, connector-bug flag |
| `guardrail` | no | Interactive job hit timeout/row cap | Returned to caller as the guardrail verdict, not a system fault |
| `cancelled` | no | Producer cancellation | Informational |
| `internal` | yes | Unhandled connector exception | Retry; dead-letter carries stack detail |

The SDK maps exceptions to this taxonomy; a bare crash without a `fail` call is observed as lease expiry and treated as `internal`.

## 7. Credential handling (J-4)

The `payload.credentials` array contains vault **references** (`vault://…` or the customer vault's native URI scheme). The runner resolves them at `start` time using its own vault identity, holds secrets in memory only for the job's duration, and must never write them to logs, progress messages, error details, or delivered results. The core redacts any string matching a resolved-reference pattern from stored error detail as defense in depth. Vault resolution failure is `auth_error` (non-retryable → re-auth flow), distinguishing it from the source rejecting valid credentials only via `error.detail.stage: vault | source`.

## 8. Deduplication and concurrency

- **Dedupe key** = `(system, type)` for batch jobs. Enqueueing while a job with the same key is `queued` merges into it (the later trigger is recorded in the existing job's `trigger` history). While one is `leased/running`, at most **one** additional job may queue behind it; further enqueues merge into that queued one. Net effect: a webhook storm during a nightly sync yields exactly one follow-up snapshot, never a pile-up.
- Interactive jobs are never deduped (each caller awaits its own result) but are bounded by per-system concurrency limits from `.contextlayer/` execution policy — the queue enforces the gateway's concurrency guardrail, not just the runner's politeness.
- Ordering guarantee: per dedupe key, at most one job is running at a time. No global ordering guarantees exist or are needed (snapshots are absolute states, not deltas).

## 9. Protocol versioning

`X-CL-Protocol-Version` is a single integer. Within a version, evolution is additive only (new optional request fields, new response fields, new job types, new error codes); clients ignore unknowns. Removing or re-typing anything bumps the version; the core serves N and N−1 during a deprecation window stated in release notes. The SDK pins the protocol version per release.

## 10. Conformance tests (runner/SDK harness)

| # | Test | Implements |
|---|---|---|
| JC-1 | Claim honors connector name, version constraint, and class declarations | §6.1 |
| JC-2 | Two runners racing a claim: exactly one obtains the lease | §5, §6.1 |
| JC-3 | Missed heartbeats → lease expiry → re-claimable with `attempt+1`; stale-lease calls rejected `409` | §5, J-7 |
| JC-4 | Runner killed mid-job → re-execution delivers an identical canonical result (pairs with snapshot C-2) | J-7 |
| JC-5 | `defer` requeues honoring `not_before` without incrementing `attempt`; deferral cap converts to failure | J-5, §5 |
| JC-6 | Invalid snapshot delivery → `422`, job dead-lettered, runner does not retry | J-6 |
| JC-7 | `cancel_requested` in heartbeat → runner stops and reports `cancelled` within one interval | §4.3, §6.3 |
| JC-8 | No secret material appears in any protocol message, log line, or stored error detail (canary-secret test) | J-4, §7 |
| JC-9 | Dedupe: N rapid enqueues of same `(system,type)` while one runs → exactly one queued follower | §8 |
| JC-11 | Defer of a leased batch job while a duplicate is queued → the deferring instance ends `coalesced`, the queued job survives with the later `not_before`, no index violation and no dead-letter | §5 amendment (D-106.2), §8, J-5 |
| JC-10 | Interactive job result reaches a blocked producer within the latency budget (JP-2) under a warm runner | J-3 |

## 11. Open decisions (spec-local register)

| # | Item | Provisional default | Revisit when |
|---|---|---|---|
| JP-1 | Core-native short-circuit for `execute` on engines the core can drive directly (node-pg for Postgres) vs. always routing through runners | Route through runners in v1 — one path, one audit shape; measure latency | If JC-10 latency misses budget in pilot |
| JP-2 | Interactive latency budget (claim-to-start overhead, excluding query time) | ≤ 500 ms p95 with a warm runner | M2 measurement |
| JP-3 | Result size cap & storage: inline delivery into Postgres, retain last N=10 snapshots per system | 64 MB cap; Postgres storage (no object store — minimal moving parts) | First estate whose snapshot approaches the cap |
| JP-4 | Webhook ingestion (CI → enqueue) endpoint shape and authentication | Core exposes `/v1/hooks/{system}` with per-hook shared secret; normatively out of this spec, owned by the sync orchestrator spec | When sync-engine spec is written |
| JP-5 | Runner autoscaling semantics under K8s (HPA on queue depth) | Manual replica count in v1 | Enterprise deployment sizing |
| JP-6 | Runner-token scope vs producer/ops surface (review #1 P-A) | **Closed** — D-66.1: runner tokens authorize the runner protocol only; producer/ops/read surface behind platform identity (§6 amendment) | — |
