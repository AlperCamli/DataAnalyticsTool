/**
 * The job API (job spec §6) plus the producer/ops surface (enqueue,
 * cancel, reads, health) and, since CP-4, the MCP server (/mcp).
 * HTTP+JSON only — runners never touch the queue's SQL (J-1).
 *
 * Auth split (P-A / D-66.1, job spec §6 amendment): per-runner bearer
 * tokens authorize ONLY the runner protocol (claim/start/heartbeat/
 * complete/fail/defer). The producer/ops/read surface requires a
 * platform identity — a static ops service token (CORE_OPS_TOKENS,
 * distinct set) or an OIDC identity carrying an ops role. A runner
 * token presented to the ops surface is denied. The MCP endpoints and
 * OAuth metadata authenticate per call in the MCP layer itself.
 *
 * JSON bodies are parsed from a retained raw buffer: snapshot deliveries
 * hand those exact bytes to the Python delivery gate, so the canonical
 * `result` bytes a runner sends are never re-serialized by JS on their
 * way to validation and storage (byte-fidelity across the wire).
 */

import Fastify, { type FastifyInstance, type FastifyReply, type FastifyRequest } from "fastify";
import { createHash, timingSafeEqual } from "node:crypto";
import pg from "pg";
import type { CoreConfig } from "./config.js";
import { JobsNotifier } from "./db.js";
import { listHealthEvents, recordHealthEvent } from "./health.js";
import {
  cancelJob,
  claimOnce,
  deferJob,
  enqueue,
  EnqueueError,
  failJob,
  getJob,
  heartbeatJob,
  listJobs,
  rejectDelivery,
  startJob,
  succeedInline,
  succeedSnapshot,
  sweepExpiredLeases,
  toWireRecord,
  type ClaimDeclaration,
  type ErrorEnvelope,
} from "./queue.js";
import { KbReader } from "./kbread.js";
import { registerMcp } from "./mcp.js";
import { OidcClient } from "./oidc.js";
import { RateLimiter } from "./ratelimit.js";
import { getSnapshotBody, listSnapshots } from "./snapshots.js";
import { getHookSecretHash, getSyncSystem, triggerSystem } from "./triggers.js";
import { acceptSnapshotDelivery, ValidatorUnavailable } from "./validator.js";

declare module "fastify" {
  interface FastifyRequest {
    rawBody?: Buffer;
    runnerBinding?: string | null;
  }
}

const PROTOCOL_VERSION = "1";

function sha256(data: string): Buffer {
  return createHash("sha256").update(data).digest();
}

export function buildServer(
  cfg: CoreConfig,
  pool: pg.Pool,
  notifier: JobsNotifier,
  logStream?: { write: (chunk: string) => void },
): FastifyInstance {
  const app = Fastify({
    logger: logStream
      ? { level: cfg.logLevel, stream: logStream }
      : { level: cfg.logLevel },
    bodyLimit: cfg.resultMaxBytes + 64 * 1024,
  });

  const isHookPath = (url: string) => url.startsWith("/v1/hooks/");

  // Parse JSON while retaining the raw bytes (see module docstring).
  // Webhook bodies are never parsed or retained (SY-2: the hook is a
  // trigger, not a data channel — the bytes are received and dropped).
  app.addContentTypeParser(
    "application/json",
    { parseAs: "buffer" },
    (req, body: Buffer, done) => {
      if (isHookPath(req.url)) return done(null, undefined);
      req.rawBody = body;
      if (body.length === 0) return done(null, {});
      try {
        done(null, JSON.parse(body.toString("utf-8")));
      } catch (err) {
        (err as { statusCode?: number }).statusCode = 400;
        done(err as Error, undefined);
      }
    },
  );

  // CI vendors post hook bodies with arbitrary content types; accept and
  // discard them on hook paths, keep the 415 contract everywhere else.
  app.addContentTypeParser("*", { parseAs: "buffer" }, (req, _body: Buffer, done) => {
    if (isHookPath(req.url)) return done(null, undefined);
    const err = new Error("unsupported media type") as Error & { statusCode?: number };
    err.statusCode = 415;
    done(err, undefined);
  });

  // Auth (P-A split, D-66.1). Runner tokens open exactly the runner
  // protocol; the ops/read surface takes a distinct service-token set or
  // an OIDC identity with an ops role; hooks and /mcp self-authenticate.
  const tokenHashes = [...cfg.runnerTokens.entries()].map(
    ([token, runnerId]) => ({ hash: sha256(token), runnerId }),
  );
  const opsTokenHashes = [...cfg.opsTokens.entries()].map(
    ([token, name]) => ({ hash: sha256(token), name }),
  );
  const oidc = cfg.mcp.oidcIssuer ? new OidcClient(cfg.mcp) : null;
  const RUNNER_PATH = /^\/v1\/jobs\/(?:claim|[^/]+\/(?:start|heartbeat|complete|fail|defer))$/;
  const isRunnerPath = (url: string, method: string) =>
    method === "POST" && RUNNER_PATH.test(url.split("?")[0]!);
  const isSelfAuthPath = (url: string) => {
    const path = url.split("?")[0]!;
    return path === "/mcp" || path.startsWith("/.well-known/");
  };

  app.addHook("onRequest", async (req, reply) => {
    if (req.url === "/healthz") return;
    if (isSelfAuthPath(req.url)) return;
    if (isHookPath(req.url)) {
      // §4.2: hooks authenticate with their own per-hook secret, and the
      // Content-Length cap guards the socket before the body is read.
      const length = Number(req.headers["content-length"] ?? 0);
      if (Number.isFinite(length) && length > cfg.sync.hookBodyMaxBytes) {
        await reply.code(413).send({ error: "payload_too_large" });
        return reply;
      }
      return;
    }
    const header = req.headers.authorization ?? "";
    const token = header.startsWith("Bearer ") ? header.slice(7) : "";
    const provided = sha256(token);

    if (isRunnerPath(req.url, req.method)) {
      let matched: { runnerId: string | null } | null = null;
      for (const entry of tokenHashes) {
        if (timingSafeEqual(provided, entry.hash)) matched = entry;
      }
      if (!token || !matched) {
        await reply.code(401).send({ error: "unauthorized" });
        return reply;
      }
      req.runnerBinding = matched.runnerId;
      return;
    }

    // Ops/read surface: static service token (full-set scan, no early
    // break) or OIDC identity with an ops role. A valid *runner* token
    // here is the P-A denial: authenticated, insufficient — 403.
    let opsMatched = false;
    for (const entry of opsTokenHashes) {
      if (timingSafeEqual(provided, entry.hash)) opsMatched = true;
    }
    if (token && opsMatched) return;
    if (token && oidc) {
      try {
        const identity = await oidc.resolveIdentity(token);
        if (identity && identity.roles.some((role) => cfg.opsRoles.includes(role))) return;
      } catch (err) {
        req.log.error({ err }, "ops-surface OIDC resolution failed");
      }
    }
    let isRunnerToken = false;
    for (const entry of tokenHashes) {
      if (timingSafeEqual(provided, entry.hash)) isRunnerToken = true;
    }
    if (isRunnerToken) {
      await reply.code(403).send({ error: "forbidden", detail: "runner tokens authorize the runner protocol only (P-A)" });
      return reply;
    }
    await reply.code(401).send({ error: "unauthorized" });
    return reply;
  });

  const leaseLost = (reply: FastifyReply) =>
    reply.code(409).send({ error: "lease_lost" });

  function leaseToken(req: FastifyRequest): string | null {
    const body = req.body as { lease_token?: unknown } | null;
    return typeof body?.lease_token === "string" && body.lease_token
      ? body.lease_token
      : null;
  }

  // -- producer/ops surface --------------------------------------------------

  app.post("/v1/jobs", async (req, reply) => {
    try {
      const { jobId, merged } = await enqueue(pool, cfg, req.body as never);
      return reply.code(merged ? 200 : 201).send({ job_id: jobId, merged });
    } catch (err) {
      if (err instanceof EnqueueError) {
        return reply.code(400).send({ error: "invalid_enqueue", errors: err.problems });
      }
      throw err;
    }
  });

  app.get("/v1/jobs", async (req) => {
    const q = req.query as { state?: string; system?: string; type?: string; limit?: string };
    const rows = await listJobs(pool, {
      state: q.state,
      system: q.system,
      type: q.type,
      limit: q.limit ? Number(q.limit) : undefined,
    });
    return { jobs: rows.map(toWireRecord) };
  });

  app.get("/v1/jobs/:jobId", async (req, reply) => {
    const { jobId } = req.params as { jobId: string };
    const row = await getJob(pool, jobId);
    if (!row) return reply.code(404).send({ error: "not_found" });
    return toWireRecord(row);
  });

  app.post("/v1/jobs/:jobId/cancel", async (req, reply) => {
    const { jobId } = req.params as { jobId: string };
    const result = await cancelJob(pool, jobId);
    if (!result) return reply.code(404).send({ error: "not_found" });
    return { state: result.state, cancel_requested: result.cancelRequested };
  });

  app.get("/v1/snapshots", async (req) => {
    const q = req.query as { system?: string; limit?: string };
    const rows = await listSnapshots(pool, {
      system: q.system,
      limit: q.limit ? Number(q.limit) : undefined,
    });
    return { snapshots: rows };
  });

  app.get("/v1/snapshots/:snapshotId/body", async (req, reply) => {
    const { snapshotId } = req.params as { snapshotId: string };
    const body = await getSnapshotBody(pool, snapshotId);
    if (!body) return reply.code(404).send({ error: "not_found" });
    return reply.type("application/json").send(body);
  });

  app.get("/v1/health-events", async (req) => {
    const q = req.query as { system?: string; job_id?: string; limit?: string };
    return {
      events: await listHealthEvents(pool, {
        system: q.system,
        jobId: q.job_id,
        limit: q.limit ? Number(q.limit) : undefined,
      }),
    };
  });

  // -- runner protocol (§6) ----------------------------------------------------

  app.post("/v1/jobs/claim", async (req, reply) => {
    const body = req.body as {
      runner_id?: unknown;
      connectors?: unknown;
      classes?: unknown;
      wait_s?: unknown;
    };
    const runnerId = typeof body.runner_id === "string" ? body.runner_id : "";
    if (!runnerId) {
      return reply.code(400).send({ error: "runner_id required" });
    }
    if (req.runnerBinding && req.runnerBinding !== runnerId) {
      return reply.code(403).send({ error: "token_not_valid_for_runner" });
    }
    const connectors = Array.isArray(body.connectors)
      ? (body.connectors as ClaimDeclaration[]).filter(
          (d) => typeof d?.name === "string" && typeof d?.version === "string",
        )
      : [];
    const classes = Array.isArray(body.classes)
      ? body.classes.filter((c): c is string => c === "batch" || c === "interactive")
      : [];
    if (connectors.length === 0 || classes.length === 0) {
      return reply.code(400).send({ error: "connectors and classes required" });
    }
    const waitS = Math.min(Math.max(Number(body.wait_s ?? 0) || 0, 0), 30);
    const deadline = Date.now() + waitS * 1000;
    for (;;) {
      const claimed = await claimOnce(pool, cfg, { runnerId, connectors, classes });
      if (claimed) {
        return reply.code(200).send({
          ...toWireRecord(claimed.row),
          lease: claimed.lease,
        });
      }
      const remaining = deadline - Date.now();
      if (remaining <= 0) return reply.code(204).send();
      await notifier.wait(Math.min(cfg.claimPollMs, remaining));
    }
  });

  app.post("/v1/jobs/:jobId/start", async (req, reply) => {
    const { jobId } = req.params as { jobId: string };
    const token = leaseToken(req);
    if (!token) return leaseLost(reply);
    const result = await startJob(pool, cfg, jobId, token);
    if (!result) return leaseLost(reply);
    return { status: "running", cancel_requested: result.cancelRequested };
  });

  app.post("/v1/jobs/:jobId/heartbeat", async (req, reply) => {
    const { jobId } = req.params as { jobId: string };
    const token = leaseToken(req);
    if (!token) return leaseLost(reply);
    const body = req.body as { progress?: Record<string, unknown> };
    const result = await heartbeatJob(pool, cfg, jobId, token, body.progress);
    if (!result) return leaseLost(reply);
    return { lease: result.lease, cancel_requested: result.cancelRequested };
  });

  app.post("/v1/jobs/:jobId/complete", async (req, reply) => {
    const { jobId } = req.params as { jobId: string };
    const token = leaseToken(req);
    if (!token) return leaseLost(reply);
    const row = await getJob(pool, jobId);
    if (!row || row.lease_token !== token || !["leased", "running"].includes(row.state)) {
      return leaseLost(reply);
    }
    const parsed = req.body as { result?: unknown };
    if (parsed.result === undefined) {
      return reply.code(400).send({ error: "result required" });
    }

    if (row.type !== "snapshot") {
      // Registered-but-unimplemented types (§4.2): result stored inline.
      const done = await succeedInline(pool, jobId, token, parsed.result);
      if (!done) return leaseLost(reply);
      return { status: "succeeded" };
    }

    let verdict, canonical;
    try {
      ({ verdict, canonical } = await acceptSnapshotDelivery(
        cfg.validatorCmd,
        req.rawBody!,
      ));
    } catch (err) {
      if (err instanceof ValidatorUnavailable) {
        req.log.error({ err }, "delivery gate unavailable");
        await recordHealthEvent(pool, {
          kind: "delivery_gate_error",
          severity: "error",
          system: row.system,
          jobId,
          detail: { message: err.message },
        });
        return reply.code(500).send({ error: "delivery_gate_unavailable" });
      }
      throw err;
    }

    if (verdict.valid && verdict.system !== row.system) {
      verdict = {
        valid: false,
        errors: [
          `delivered snapshot describes system ${JSON.stringify(verdict.system)} ` +
            `but the job is for system ${JSON.stringify(row.system)}`,
        ],
        warnings: verdict.warnings,
      };
    }
    if (!verdict.valid) {
      const errors = verdict.errors ?? ["invalid snapshot"];
      const done = await rejectDelivery(pool, jobId, token, errors);
      if (!done) return leaseLost(reply);
      // §6.4: 422 is final — the runner must not retry (JC-6).
      return reply.code(422).send({ status: "dead_lettered", errors });
    }
    const accepted = await succeedSnapshot(
      pool,
      cfg,
      jobId,
      token,
      verdict as Required<typeof verdict>,
      canonical!,
    );
    if (!accepted) return leaseLost(reply);
    for (const warning of verdict.warnings ?? []) {
      req.log.warn({ jobId, warning }, "snapshot accepted with warning");
    }
    return { status: "succeeded", snapshot_id: accepted.snapshotId };
  });

  app.post("/v1/jobs/:jobId/fail", async (req, reply) => {
    const { jobId } = req.params as { jobId: string };
    const token = leaseToken(req);
    if (!token) return leaseLost(reply);
    const body = req.body as { error?: Partial<ErrorEnvelope> };
    const error: ErrorEnvelope = {
      code: typeof body.error?.code === "string" ? body.error.code : "internal",
      message: typeof body.error?.message === "string" ? body.error.message : "",
      retryable: body.error?.retryable === true,
      ...(body.error?.detail !== undefined ? { detail: body.error.detail } : {}),
    };
    const outcome = await failJob(pool, cfg, jobId, token, error);
    if (!outcome) return leaseLost(reply);
    return { status: outcome };
  });

  app.post("/v1/jobs/:jobId/defer", async (req, reply) => {
    const { jobId } = req.params as { jobId: string };
    const token = leaseToken(req);
    if (!token) return leaseLost(reply);
    const body = req.body as { retry_after_s?: unknown; reason?: Record<string, unknown> };
    const retryAfterS = Number(body.retry_after_s);
    if (!Number.isFinite(retryAfterS) || retryAfterS < 0) {
      return reply.code(400).send({ error: "retry_after_s (non-negative number) required" });
    }
    const outcome = await deferJob(
      pool,
      cfg,
      jobId,
      token,
      retryAfterS,
      (body.reason ?? {}) as { code?: string; message?: string },
    );
    if (!outcome) return leaseLost(reply);
    return { status: outcome };
  });

  // -- webhook trigger ingestion (sync spec §4.2, JP-4 adopted) ---------------
  //
  // System identity from the URL path, per-hook shared secret in
  // X-CL-Hook-Secret compared constant-time, body ignored unread (SY-2).
  // 202 trigger accepted / 401 bad secret, nothing enqueued / 404 unknown
  // system — the body never distinguishes "unknown" from "not configured"
  // (M-4 spirit). Job-protocol dedupe absorbs CI storms (SO-A).

  // Route-level bodyLimit (F3 review / D-66 §2): Fastify enforces the cap
  // while reading the body, chunked or not, so an absent/understated
  // Content-Length can no longer stream past it into memory before the
  // (unauthenticated) secret check. The onRequest header pre-check above
  // stays as a fast reject for an honest oversized Content-Length.
  app.post("/v1/hooks/:system", { bodyLimit: cfg.sync.hookBodyMaxBytes }, async (req, reply) => {
    const { system } = req.params as { system: string };
    const header = req.headers["x-cl-hook-secret"];
    const provided = typeof header === "string" ? header : "";
    const storedHash = await getHookSecretHash(pool, system);
    if (storedHash === null) {
      return reply.code(404).send({ error: "not_found" });
    }
    const stored = Buffer.from(storedHash, "hex");
    const digest = sha256(provided);
    if (stored.length !== digest.length || !timingSafeEqual(digest, stored)) {
      return reply.code(401).send({ error: "unauthorized" });
    }
    const registered = await getSyncSystem(pool, system);
    if (!registered) {
      return reply.code(404).send({ error: "not_found" });
    }
    await triggerSystem(pool, cfg, registered, { kind: "webhook" });
    return reply.code(202).send({ status: "accepted" });
  });

  // -- sync ops reads ---------------------------------------------------------

  app.get("/v1/runs", async (req) => {
    const q = req.query as { limit?: string };
    const { rows } = await pool.query(
      `SELECT run_id, triggers, systems, kb_ref, snapshot_refs,
              classification_counts, contaminated_docs, outcome, pr_url,
              detail, started_at, finished_at, duration_ms
         FROM runs ORDER BY started_at DESC LIMIT $1`,
      [Math.min(Number(q.limit ?? 50) || 50, 200)],
    );
    return { runs: rows };
  });

  app.get("/v1/freshness-warnings", async () => {
    const { rows } = await pool.query(
      `SELECT system, raised_at, age_s, threshold_s, detail
         FROM freshness_warnings ORDER BY system`,
    );
    return { warnings: rows };
  });

  // -- MCP server (CP-4; self-authenticating per call) ------------------------

  if (cfg.mcp.enabled) {
    registerMcp(app, {
      cfg,
      pool,
      oidc: oidc ?? new OidcClient(cfg.mcp),
      kb: new KbReader(cfg, pool),
      limiter: new RateLimiter(cfg.mcp.limits),
      log: (msg, err) => (err ? app.log.error({ err }, msg) : app.log.info(msg)),
    });
  }

  // -- health probe (unauthenticated) -----------------------------------------

  app.get("/healthz", async (_req, reply) => {
    try {
      const { rows } = await pool.query<{ state: string; n: string }>(
        `SELECT state, count(*) AS n FROM jobs GROUP BY state`,
      );
      const jobs: Record<string, number> = {};
      for (const row of rows) jobs[row.state] = Number(row.n);
      return { status: "ok", protocol_version: PROTOCOL_VERSION, jobs };
    } catch (err) {
      _req.log.error({ err }, "healthz db check failed");
      return reply.code(503).send({ status: "degraded" });
    }
  });

  return app;
}

/** Periodic lease-expiry sweep (§4.3); returns a stop function. */
export function startSweeper(
  pool: pg.Pool,
  cfg: CoreConfig,
  log: (msg: string, err?: unknown) => void,
): () => void {
  const timer = setInterval(() => {
    sweepExpiredLeases(pool, cfg)
      .then((n) => {
        if (n > 0) log(`sweeper requeued/dead-lettered ${n} expired lease(s)`);
      })
      .catch((err) => log("sweeper pass failed", err));
  }, cfg.sweepIntervalMs);
  timer.unref();
  return () => clearInterval(timer);
}
