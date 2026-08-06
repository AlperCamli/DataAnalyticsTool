/**
 * The Ops module's server half (dashboard spec §3, checkpoint B-1):
 * run and job health with dead-letter re-enqueue (U-10), and webhook
 * secret lifecycle (U-11, write-only per UI-8).
 *
 * These facts already had an HTTP surface — `/v1/runs`, `/v1/jobs`,
 * `/v1/health-events` — but that surface is the **ops-token** one: a
 * shared bearer credential, not a person. Reading it from a browser
 * would mean either handing the SPA a service token (UI-2's exact
 * prohibition) or letting the dashboard act as somebody it is not. So
 * the module gets its own addresses on the session layer, and every act
 * carries the acting identity to the row it writes.
 *
 * Two rules are load-bearing here.
 *
 * **Re-enqueue does not repair (D-114.9).** A dead-lettered job stays
 * dead-lettered, with its error and its attempt count intact, because it
 * is the evidence that something failed — rewriting its state would
 * erase the fault the operator is looking at. The act enqueues a *new*
 * job carrying the dead one's payload, under the caller's identity, and
 * answers with the new job's id. The dead row gains a pointer to it and
 * nothing else.
 *
 * **A secret is shown once, from the creation response (UI-8/DT-5).**
 * The rotate route generates, stores only a sha256, and returns the
 * plaintext in that one reply. There is no route here that reads a
 * secret back, and there could not be — the store holds a hash.
 */

import { createHash, randomBytes } from "node:crypto";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import pg from "pg";
import { writeGovernanceAudit } from "./audit.js";
import { neutralize } from "./changelog.js";
import type { CoreConfig } from "./config.js";
import type { KbState } from "./kbread.js";
import type { Identity } from "./oidc.js";
import { profilesForRoles } from "./dashboard.js";
import { enqueue, EnqueueError, listJobs } from "./queue.js";
import { authenticate, type SessionDeps } from "./session.js";
import { getSyncSystem, setHookSecret } from "./triggers.js";

export const API_VERSION = "1";

/**
 * The job types re-enqueue is offered for: the ones whose payload is a
 * capture of the **connection registry** and can therefore be rebuilt
 * from it.
 *
 * The line is not "batch vs interactive" — a `test_connection` probe is
 * interactive and is perfectly safe to re-run. It is *whose request the
 * payload holds*. A snapshot or a probe asks the registry "read this
 * source"; an `execute` or a `publish` carries a person's statement,
 * their identity and the guardrails they were granted, and re-running
 * that means re-running somebody else's request with nobody waiting for
 * the answer — or, for publish, re-delivering a report to a BI tool
 * because an operator was clearing a queue.
 */
const REBUILDABLE_TYPES = new Set(["snapshot", "test_connection"]);

export interface OpsDeps extends SessionDeps {
  cfg: CoreConfig;
  pool: pg.Pool;
  kb: { current(): Promise<KbState> };
  log: (msg: string, err?: unknown) => void;
}

interface OpsViewer {
  identity: Identity;
  ws: KbState | null;
  canWrite: boolean;
  profile: string | null;
}

export function registerOps(app: FastifyInstance, deps: OpsDeps): void {
  /**
   * Same gate shape as Connections, and deliberately the same roles: an
   * ops identity writes, a steward reads. Re-enqueueing a job and
   * rotating a webhook secret are provisioning acts (UI-7), and the
   * steward's job is to see the estate, not to run it.
   */
  async function viewerFor(
    req: FastifyRequest,
    reply: FastifyReply,
    need: "read" | "write",
  ): Promise<OpsViewer | null> {
    const auth = await authenticate(deps, req, { write: need === "write" });
    if (!auth.ok) {
      await reply.code(auth.status).send({ error: auth.code, detail: auth.detail });
      return null;
    }
    const canWrite = auth.identity.roles.some((role) => deps.cfg.dashboard.adminRoles.includes(role));
    let ws: KbState | null = null;
    let profiles = new Set<string>();
    try {
      ws = await deps.kb.current();
      profiles = profilesForRoles(ws, auth.identity.roles);
    } catch (err) {
      deps.log("KB workspace unavailable while resolving ops access", err);
    }
    const profile = [...profiles].sort().join(",") || null;
    const refuse = async (detail: string): Promise<null> => {
      // The refusal is audited before it is sent (D-114.1): a denied
      // governance act is exactly the row an auditor came for.
      await writeGovernanceAudit(
        deps.pool,
        {
          subject: auth.identity.subject,
          roles: auth.identity.roles,
          profile,
          tool: `dashboard.ops.${need}`,
          args: { path: req.url, method: req.method },
          kbRef: ws?.headSha ?? null,
          decision: "denied",
          decisionReason: detail,
        },
        deps.log,
      );
      await reply.code(403).send({ error: "forbidden", detail });
      return null;
    };
    if (need === "write" && !canWrite) {
      return refuse(
        "re-enqueueing a job and rotating a webhook secret are ops acts; " +
          "this identity holds no ops role (dashboard spec §4, UI-7)",
      );
    }
    if (!canWrite && !profiles.has("steward")) {
      return refuse("run and job health is visible to ops and steward identities (dashboard spec §4)");
    }
    return { identity: auth.identity, ws, canWrite, profile };
  }

  const limitOf = (raw: unknown, fallback: number): number => {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed < 1) return fallback;
    return Math.min(parsed, deps.cfg.dashboard.pageMax);
  };

  // -- runs (U-10) -----------------------------------------------------------

  app.get("/v1/dashboard/ops/runs", async (req, reply) => {
    const viewer = await viewerFor(req, reply, "read");
    if (!viewer) return reply;
    const query = (req.query ?? {}) as Record<string, unknown>;
    const { rows } = await deps.pool.query<{
      run_id: string;
      triggers: unknown;
      systems: string[];
      kb_ref: string | null;
      outcome: string;
      pr_url: string | null;
      classification_counts: Record<string, unknown> | null;
      contaminated_docs: unknown[] | null;
      started_at: string;
      finished_at: string | null;
      duration_ms: number | null;
    }>(
      `SELECT run_id, triggers, systems, kb_ref, outcome, pr_url,
              classification_counts, contaminated_docs,
              to_jsonb(started_at)  #>> '{}' AS started_at,
              to_jsonb(finished_at) #>> '{}' AS finished_at, duration_ms
         FROM runs ORDER BY started_at DESC LIMIT $1`,
      [limitOf(query.limit, 25)],
    );
    return reply.send({
      api_version: API_VERSION,
      runs: rows.map((row) => ({
        run_id: row.run_id,
        systems: (row.systems ?? []).map((s) => neutralize(s)),
        kb_ref: row.kb_ref,
        outcome: neutralize(row.outcome),
        pr_url: row.pr_url,
        classification_counts: row.classification_counts ?? {},
        // A count, not the list: the contaminated set has its own screen
        // in KB Health, read from the KB rather than from a run record
        // that may be several merges out of date.
        contaminated_count: Array.isArray(row.contaminated_docs) ? row.contaminated_docs.length : 0,
        triggers: row.triggers ?? [],
        started_at: row.started_at,
        finished_at: row.finished_at,
        duration_ms: row.duration_ms,
      })),
    });
  });

  // -- jobs + dead letter (U-10) ---------------------------------------------

  app.get("/v1/dashboard/ops/jobs", async (req, reply) => {
    const viewer = await viewerFor(req, reply, "read");
    if (!viewer) return reply;
    const query = (req.query ?? {}) as Record<string, unknown>;
    const state = typeof query.state === "string" && query.state ? query.state : undefined;
    const system = typeof query.system === "string" && query.system ? query.system : undefined;
    const rows = await listJobs(deps.pool, {
      ...(state ? { state } : {}),
      ...(system ? { system } : {}),
      limit: limitOf(query.limit, 50),
    });
    const { rows: counts } = await deps.pool.query<{ state: string; n: string }>(
      `SELECT state, count(*) AS n FROM jobs GROUP BY state`,
    );
    return reply.send({
      api_version: API_VERSION,
      counts: Object.fromEntries(counts.map((c) => [c.state, Number(c.n)])),
      jobs: rows.map((job) => ({
        job_id: job.job_id,
        type: neutralize(job.type),
        system: neutralize(job.system),
        state: job.state,
        attempt: job.attempt,
        max_attempts: job.max_attempts,
        deferrals: job.deferrals,
        // Error text comes from a connector, which reads a source the
        // customer controls: user-influenceable, therefore inert (§6).
        error: job.error
          ? {
              code: neutralize((job.error as { code?: unknown }).code ?? "unknown"),
              message: neutralize((job.error as { message?: unknown }).message ?? ""),
              retryable: Boolean((job.error as { retryable?: unknown }).retryable),
            }
          : null,
        triggers: job.triggers ?? [],
        // The chain (B1-F1): which job replaced this one, so a queue of
        // repeated failures reads as one story rather than several.
        reenqueued_as: job.reenqueued_as ?? null,
        created_at: job.created_at,
        finished_at: job.finished_at,
      })),
    });
  });

  /**
   * Re-enqueue a dead-lettered job **as the caller** (§3: "Re-enqueue is
   * `POST /v1/jobs` as the user").
   *
   * Two rules, and the second was bought by finding B1-F1.
   *
   * **The dead row is not touched beyond a pointer to its replacement.**
   * An operator looking at this screen is looking at a fault, and a
   * re-enqueue that flipped the old row back to `queued` would delete the
   * fault while appearing to fix it.
   *
   * **The payload is REBUILT from the connection registration, never
   * replayed from the dead job.** A job's payload is a *capture* of the
   * registry taken at enqueue time, so a job that predates a credential
   * change carries the reference that used to be right — and replaying it
   * re-runs a configuration the estate has abandoned. The pilot found
   * this the hard way after A-4: snapshot jobs captured before the vault
   * migration carried `env://SUPABASE_DSN`, the runner has had no `env`
   * resolver since, and each press produced a fresh dead job with the
   * same impossible reference. Same fan-out rule as everywhere else — the
   * registry is the one source for what a connection uses, and a captured
   * copy that disagrees with it is not evidence, it is a stale duplicate.
   */
  app.post("/v1/dashboard/ops/jobs/:jobId/reenqueue", async (req, reply) => {
    const viewer = await viewerFor(req, reply, "write");
    if (!viewer) return reply;
    const { jobId } = req.params as { jobId: string };
    const { rows } = await deps.pool.query<{
      job_id: string;
      type: string;
      system: string;
      connector_name: string;
      version_constraint: string;
      payload: Record<string, unknown>;
      state: string;
      reenqueued_as: string | null;
    }>(
      `SELECT job_id, type, system, connector_name, version_constraint, payload, state,
              reenqueued_as
         FROM jobs WHERE job_id = $1`,
      [jobId],
    );
    const dead = rows[0];
    if (!dead) return reply.code(404).send({ error: "not_found" });
    if (dead.state !== "dead_lettered") {
      return reply.code(409).send({
        error: "not_dead_lettered",
        detail: `job ${jobId} is ${dead.state}; re-enqueue is offered for dead-lettered jobs only`,
      });
    }
    if (dead.reenqueued_as) {
      // B1-F1: pressing again on the same dead row starts a parallel
      // branch from a stale point rather than continuing the chain. The
      // operator wants the newest job in the chain, so say which it is.
      return reply.code(409).send({
        error: "already_reenqueued",
        detail:
          `job ${jobId} was already re-enqueued as ${dead.reenqueued_as}. ` +
          "Re-enqueue that one if it also failed — pressing here again would fork the chain " +
          "from a job that is two attempts old.",
        job_id: dead.reenqueued_as,
      });
    }
    if (!REBUILDABLE_TYPES.has(dead.type)) {
      return reply.code(409).send({
        error: "not_reenqueueable",
        detail:
          `a ${dead.type} job carries a captured request — a statement, an identity and the ` +
          "guardrails it was granted — not a connection's configuration. Replaying it would " +
          "re-run somebody else's request under their recorded identity with nobody waiting " +
          "for the result. Re-run it from the session that asked.",
      });
    }

    // The registration, which is the authority for what this system uses
    // *now*. Its `payload` is `{config, credentials}` — the same shape a
    // snapshot or probe job takes, which is why substitution is clean
    // rather than a translation.
    const registration = await getSyncSystem(deps.pool, dead.system);
    if (!registration) {
      return reply.code(409).send({
        error: "no_registration",
        detail:
          `no connection is registered for '${dead.system}', so there is no current ` +
          "configuration to run this job against. The dead job's own payload names a " +
          "configuration the estate no longer has; running it would prove nothing.",
      });
    }

    const refsOf = (payload: unknown): string[] =>
      ((payload as { credentials?: { ref?: unknown }[] } | null)?.credentials ?? [])
        .map((c) => (typeof c.ref === "string" ? c.ref : null))
        .filter((r): r is string => r !== null)
        .sort();
    const capturedRefs = refsOf(dead.payload);
    const currentRefs = refsOf(registration.payload);
    const refsChanged = JSON.stringify(capturedRefs) !== JSON.stringify(currentRefs);

    let created: { jobId: string; merged: boolean };
    try {
      created = await enqueue(deps.pool, deps.cfg, {
        type: dead.type,
        system: dead.system,
        // The connector too: a registration that moved to another
        // connector or widened its constraint is the current answer.
        connector: {
          name: registration.connector_name,
          version_constraint: registration.version_constraint,
        },
        payload: registration.payload,
        trigger: {
          kind: "dashboard",
          // The acting identity, on the row itself — which is what the
          // job's `triggers` array was always for, and the reason a
          // re-enqueue is attributable without reading a log.
          detail: { actor: viewer.identity.subject, via: "dashboard", reenqueue_of: dead.job_id },
        },
      });
    } catch (err) {
      if (err instanceof EnqueueError) {
        // The *registration* does not validate — which is a fault in the
        // connection, not in the dead job, and is said as such.
        return reply.code(400).send({
          error: "invalid_enqueue",
          detail:
            `the current registration for '${dead.system}' does not validate against this ` +
            "core's job contract, so no job could be built from it. Fix the connection first.",
          fields: err.problems,
        });
      }
      throw err;
    }

    await deps.pool.query(`UPDATE jobs SET reenqueued_as = $2 WHERE job_id = $1`, [
      dead.job_id,
      created.jobId,
    ]);
    await writeGovernanceAudit(
      deps.pool,
      {
        subject: viewer.identity.subject,
        roles: viewer.identity.roles,
        profile: viewer.profile,
        tool: "dashboard.ops.reenqueue",
        args: { job_id: dead.job_id, type: dead.type, system: dead.system },
        kbRef: viewer.ws?.headSha ?? null,
        decision: "allowed",
        decisionReason: null,
        resultMeta: {
          new_job_id: created.jobId,
          merged: created.merged,
          rebuilt_from_registration: true,
          references_changed: refsChanged,
        },
      },
      deps.log,
    );

    return reply.code(201).send({
      api_version: API_VERSION,
      job_id: created.jobId,
      merged: created.merged,
      reenqueue_of: dead.job_id,
      // Stated because it is the design, not an omission.
      dead_job_unchanged: true,
      // B1-F1: when the dead job's captured references differ from the
      // registration's, the operator is about to see a *different*
      // outcome from the same button, and the reason belongs in the
      // answer rather than in a changelog.
      rebuilt_from_registration: true,
      references: {
        captured: capturedRefs,
        current: currentRefs,
        changed: refsChanged,
        ...(refsChanged
          ? {
              note:
                "This job was captured before the connection's credential references changed. " +
                "The new job runs against the references the connection holds now — which is " +
                "why it may behave differently from the one that died.",
            }
          : {}),
      },
    });
  });

  // -- webhook secrets (U-11, write-only per UI-8) ---------------------------

  /**
   * What a webhook secret's *row* looks like — never what it is. The
   * store holds a sha256; there is nothing here that could return a
   * secret even if a future caller asked for one.
   */
  app.get("/v1/dashboard/ops/hooks", async (req, reply) => {
    const viewer = await viewerFor(req, reply, "read");
    if (!viewer) return reply;
    const { rows } = await deps.pool.query<{
      system: string;
      created_at: string;
      rotated_at: string | null;
    }>(
      `SELECT s.system,
              to_jsonb(h.created_at) #>> '{}' AS created_at,
              to_jsonb(h.rotated_at) #>> '{}' AS rotated_at
         FROM sync_systems s
         LEFT JOIN sync_hooks h ON h.system = s.system
        ORDER BY s.system`,
    );
    return reply.send({
      api_version: API_VERSION,
      role_scope: viewer.canWrite ? "write" : "read",
      hooks: rows.map((row) => ({
        system: neutralize(row.system),
        configured: row.created_at !== null,
        created_at: row.created_at,
        rotated_at: row.rotated_at,
        // The address a CI job posts to. Not a secret, and useless
        // without one.
        path: `/v1/hooks/${encodeURIComponent(row.system)}`,
      })),
    });
  });

  /**
   * Create or rotate, and **show the secret exactly once** (UI-8).
   *
   * The plaintext exists in this handler and in this one reply. It is
   * never stored, never logged, and never re-derivable: what the row
   * holds is a sha256 of it, which is also all the hook endpoint needs
   * to verify a later delivery.
   */
  app.post("/v1/dashboard/ops/hooks/:system/rotate", async (req, reply) => {
    const viewer = await viewerFor(req, reply, "write");
    if (!viewer) return reply;
    const { system } = req.params as { system: string };
    const registered = await getSyncSystem(deps.pool, system);
    if (!registered) {
      return reply.code(404).send({
        error: "not_found",
        detail: "no connection is registered under this system, so nothing would post to its hook",
      });
    }
    const secret = randomBytes(32).toString("base64url");
    const outcome = await setHookSecret(
      deps.pool,
      system,
      createHash("sha256").update(secret).digest("hex"),
    );
    await writeGovernanceAudit(
      deps.pool,
      {
        subject: viewer.identity.subject,
        roles: viewer.identity.roles,
        profile: viewer.profile,
        tool: "dashboard.ops.hook_rotate",
        // The system, never the secret and never a digest of it: an
        // args digest over the secret would be a verifier for it.
        args: { system },
        kbRef: viewer.ws?.headSha ?? null,
        decision: "allowed",
        decisionReason: null,
        resultMeta: { outcome },
      },
      deps.log,
    );
    return reply.code(201).send({
      api_version: API_VERSION,
      system: neutralize(system),
      outcome,
      secret,
      // The UI renders this sentence rather than composing its own, so
      // the warning and the fact it describes ship together.
      shown_once:
        "This is the only time this value is shown. The server stored a hash of it and cannot " +
        "return it again; if it is lost, rotate for a new one.",
      hook_path: `/v1/hooks/${encodeURIComponent(system)}`,
    });
  });
}
