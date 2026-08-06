/**
 * The Connections API (checkpoint A-3; dashboard spec §3 "Connections",
 * inventory item U-1, register item E2).
 *
 * What this module ends: since D-63.8 the connection registry has been
 * written by a vendor CLI holding a database credential, explicitly as
 * "E2's Connections-UI stand-in". The CP-8 report graded playbook step 3
 * ASSISTED on exactly that, and D-84's silent-failure pair — a
 * connection reported registered that was absent — is what it cost. So
 * three properties are structural here rather than procedural:
 *
 * 1. **One writer.** `sync_systems` is written through this API and
 *    nowhere else. The admin CLI is now a client of these endpoints
 *    (`core/src/cli.ts`); its direct-database path is deleted, not
 *    deprecated, and `connections.test.ts` asserts at grep level that no
 *    CLI path holds a registry write.
 *
 * 2. **References only, never secrets** (J-4). A create or update whose
 *    payload carries credential *material* rather than a reference is
 *    refused by name — `raw_secret_rejected` — and the refusal names the
 *    field, never the value. `env://` today; `vault://` is accepted by
 *    the same rule so A-4 needs no change here.
 *
 * 3. **Registration returns what the store holds.** Not what the caller
 *    sent, and not what this code intended: `upsertSyncSystem` re-reads
 *    and compares, and a write the store did not take raises rather than
 *    returning. There is no line below that echoes the request body.
 *
 * Role gate (dashboard spec §4, UI-1/UI-7): writing a connection is an
 * ops act, so it takes an ops role — the same server-side role set the
 * job/ops surface already enforces, resolved from the caller's own OIDC
 * identity. A steward reads. Everyone else gets a 403 from the server;
 * there is no shape of this API that a client filters.
 */

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import pg from "pg";
import { writeGovernanceAudit } from "./audit.js";
import { neutralize } from "./changelog.js";
import type { CoreConfig } from "./config.js";
import type { KbReader, KbState } from "./kbread.js";
import type { Identity, OidcClient } from "./oidc.js";
import { parsePolicy, type SyncPolicy } from "./policy.js";
import { awaitJobResult, enqueue, EnqueueError } from "./queue.js";
import { readRemoteFile } from "./gitkb.js";
import { profilesForRoles } from "./dashboard.js";
import { authenticate, type SessionDeps } from "./session.js";
import {
  deleteSyncSystem,
  getSyncSystem,
  listSyncSystems,
  RegistryWriteNotObserved,
  triggerSystem,
  upsertSyncSystem,
  type SyncSystem,
} from "./triggers.js";

export const API_VERSION = "1";

/** sync-policy.yaml's path in the KB (KB spec §3). */
const POLICY_PATH = ".contextlayer/sync-policy.yaml";

/** Default wait before the caller is told the probe has no verdict yet.
 * The probe is one connect or one GET, so a minute is generous, and past
 * it the honest answer is "no verdict yet" — never a failure an operator
 * would read as the source being broken. Deployment-tunable, because how
 * long a runner takes to pick work up is a deployment fact. */
const DEFAULT_PROBE_DEADLINE_S = 60;

export interface ConnectionsDeps extends SessionDeps {
  cfg: CoreConfig;
  pool: pg.Pool;
  oidc: OidcClient;
  kb: KbReader;
  /** The interactive-result channel (JOB_DONE). Absent in deployments
   * with no MCP surface; the await then polls, which is correct but
   * slower — never wrong. */
  notifier?: { waitFor(match: (p: string | undefined) => boolean, ms: number): Promise<void> };
  log: (msg: string, err?: unknown) => void;
}

// ---------------------------------------------------------------------------
// Credential references (J-4)

/**
 * A credential reference: a scheme and a name, no material.
 *
 * `env://` is what the pilot resolver reads today; `vault://` is A-4's
 * and is accepted now so that landing the vault changes the resolver,
 * not this validation. Anything else is refused — including a bare
 * string, which is exactly how key material would arrive.
 */
const CREDENTIAL_REF = /^(env|vault):\/\/[A-Za-z0-9_][A-Za-z0-9_.\-/]*(#[A-Za-z0-9_.\-]+)?$/;

/**
 * Config keys that hold credential *material* in the connector schemas.
 *
 * These exist because the local CLI and developer runs need them
 * (D-14/D-28: `dsn` inline beside `dsn_env`), and the schemas document
 * them as the discouraged form. Through this API they are simply not
 * available: a registration is a durable row in a shared database, and
 * the indirection twin of each key is right there.
 */
const INLINE_SECRET_KEYS: Record<string, string> = {
  dsn: "dsn_env",
  execute_dsn: "execute_dsn_env",
  credentials: "the payload's credentials[] references",
  client_secret: "a credentials[] reference with key: client_secret",
  password: "a credentials[] reference",
  secret: "a credentials[] reference",
  token: "a credentials[] reference",
  api_key: "a credentials[] reference",
  private_key: "a credentials[] reference",
};

/** Value shapes that are credential material whatever they are called. */
const SECRET_SHAPES: { name: string; re: RegExp }[] = [
  { name: "a URI with an embedded password", re: /^[a-z][a-z0-9+.-]*:\/\/[^/\s@]*:[^@/\s]+@/i },
  { name: "a PEM private key", re: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
  { name: "a service-account key JSON", re: /"private_key"\s*:/ },
];

export class PayloadRejected extends Error {
  constructor(readonly code: string, message: string, readonly fields: string[] = []) {
    super(message);
  }
}

/**
 * Walk the config for credential material.
 *
 * The offending **path** is reported and the offending **value** never
 * is — an error message is a place a secret leaks to logs, tickets and
 * screenshots, and this one is designed to be quoted.
 */
function scanConfig(config: Record<string, unknown>, path = "config"): string[] {
  const found: string[] = [];
  for (const [key, value] of Object.entries(config)) {
    const here = `${path}.${key}`;
    const alternative = INLINE_SECRET_KEYS[key];
    if (alternative !== undefined) {
      found.push(`${here} carries credential material inline; use ${alternative} instead`);
      continue;
    }
    if (typeof value === "string") {
      for (const shape of SECRET_SHAPES) {
        if (shape.re.test(value)) {
          found.push(`${here} looks like ${shape.name}; connections hold references, not secrets`);
          break;
        }
      }
    } else if (value && typeof value === "object" && !Array.isArray(value)) {
      found.push(...scanConfig(value as Record<string, unknown>, here));
    }
  }
  return found;
}

export interface ConnectionSpec {
  system: string;
  connector_name: string;
  version_constraint: string;
  payload: { config: Record<string, unknown>; credentials: Record<string, unknown>[] };
}

/**
 * Parse and gate a registration body. Everything that could carry a
 * secret is checked here, once, before anything is written.
 */
export function readConnectionSpec(system: string, body: unknown): ConnectionSpec {
  const b = (body ?? {}) as Record<string, unknown>;
  if (!/^[a-z0-9][a-z0-9_-]{0,62}$/.test(system)) {
    throw new PayloadRejected(
      "invalid_argument",
      "system must be lowercase alphanumeric with - or _ (it names a KB directory and a webhook path)",
    );
  }
  const connector = (b.connector ?? {}) as Record<string, unknown>;
  const name = typeof connector.name === "string" ? connector.name.trim() : "";
  if (!name) {
    throw new PayloadRejected("invalid_argument", "connector.name (non-empty string) is required");
  }
  const constraint =
    typeof connector.version_constraint === "string" && connector.version_constraint.trim()
      ? connector.version_constraint.trim()
      : "*";

  const payload = (b.payload ?? {}) as Record<string, unknown>;
  const config = payload.config;
  if (typeof config !== "object" || config === null || Array.isArray(config)) {
    throw new PayloadRejected("invalid_argument", "payload.config must be an object");
  }
  const rawCredentials = payload.credentials ?? [];
  if (!Array.isArray(rawCredentials)) {
    throw new PayloadRejected("invalid_argument", "payload.credentials must be an array");
  }

  const problems = scanConfig(config as Record<string, unknown>);
  const credentials: Record<string, unknown>[] = [];
  rawCredentials.forEach((entry, i) => {
    const at = `payload.credentials[${i}]`;
    if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
      problems.push(`${at} must be an object of the form {key, ref, required_for?}`);
      return;
    }
    const e = entry as Record<string, unknown>;
    const key = typeof e.key === "string" ? e.key : "";
    const ref = typeof e.ref === "string" ? e.ref : "";
    if (!key) problems.push(`${at}.key (the manifest's credential key) is required`);
    if (!ref) {
      problems.push(
        `${at}.ref is required and must be a reference ` +
          "(vault://<mount>/<path>#<field>, or env://NAME — pilot-only, A-4)",
      );
    } else if (!CREDENTIAL_REF.test(ref)) {
      // Deliberately does not echo `ref`: if this branch fired because
      // somebody pasted a DSN into it, echoing is the leak.
      problems.push(
        `${at}.ref is not a credential reference — it must be ` +
          "vault://<mount>/<path>#<field>, or env://NAME (pilot-only). " +
          "This product stores the reference; the value lives where the resolver reads it",
      );
    }
    for (const forbidden of ["value", "secret", "password", "content", "json", "material"]) {
      if (e[forbidden] !== undefined) {
        problems.push(`${at}.${forbidden} is not a member of a credential reference`);
      }
    }
    const requiredFor = e.required_for;
    if (requiredFor !== undefined && !Array.isArray(requiredFor)) {
      problems.push(`${at}.required_for must be an array of capability/mode names`);
    }
    credentials.push({
      key,
      ref,
      ...(Array.isArray(requiredFor) ? { required_for: requiredFor } : {}),
      ...(typeof e.description === "string" ? { description: e.description } : {}),
    });
  });

  if (problems.length > 0) {
    const secretish = problems.filter(
      (p) => p.includes("credential material") || p.includes("looks like") || p.includes("not a credential reference") || p.includes("is not a member"),
    );
    throw new PayloadRejected(
      secretish.length > 0 ? "raw_secret_rejected" : "invalid_argument",
      secretish.length > 0
        ? "a connection holds credential references only, never credential material (J-4)"
        : "the connection payload is not well-formed",
      problems,
    );
  }

  return {
    system,
    connector_name: name,
    version_constraint: constraint,
    payload: { config: config as Record<string, unknown>, credentials },
  };
}

// ---------------------------------------------------------------------------
// Health (read from what already exists — no new store)

export interface ConnectionHealth {
  status: "green" | "amber" | "red" | "unknown";
  reason: string;
  snapshot: {
    snapshot_id: string;
    captured_at: string;
    accepted_at: string;
    age_s: number;
    object_count: number;
    source_mode: string;
  } | null;
  policy: { threshold_s: number; trigger_mode: "schedule" | "webhook" | "manual" } | null;
  freshness: "fresh" | "stale" | "never_snapshotted" | "not_a_sync_source" | "unknown";
  last_job: {
    job_id: string;
    type: string;
    state: string;
    finished_at: string | null;
    error: { code?: string; message?: string; retryable?: boolean } | null;
  } | null;
}

interface SnapshotRow {
  snapshot_id: string;
  captured_at: string;
  accepted_at: string;
  age_s: string;
  object_count: number;
  source_mode: string;
}

interface JobRowLite {
  job_id: string;
  type: string;
  state: string;
  finished_at: string | null;
  error: Record<string, unknown> | null;
}

/**
 * One connection's health, assembled from three rows that already
 * exist: the latest accepted snapshot, the policy entry that says how
 * old is too old, and the latest job for the system.
 *
 * The states are deliberately four rather than two. "I do not know" is
 * a real answer here — if `sync-policy.yaml` cannot be read there is no
 * threshold, and calling that green because nothing has failed is how a
 * dashboard ends up asserting health it never measured (UI-10, one layer
 * down).
 *
 * **Freshness is not every connection's health axis.** `sync-policy.yaml`
 * is the declaration of which systems are snapshotted; a registered
 * connection absent from it — a publish target like Looker Studio or
 * Power BI — is not a sync source, will never have an accepted snapshot,
 * and must not sit permanently amber for failing to be one. Those are
 * judged on their last job instead. Getting this wrong would have made
 * the playbook's "health green" exit unreachable for two of the pilot's
 * five connections, which is how a health model quietly teaches
 * operators to ignore it.
 */
export async function healthFor(
  pool: pg.Pool,
  system: string,
  policy: SyncPolicy | null,
): Promise<ConnectionHealth> {
  const { rows: snapshots } = await pool.query<SnapshotRow>(
    `SELECT snapshot_id,
            to_jsonb(captured_at) #>> '{}' AS captured_at,
            to_jsonb(accepted_at) #>> '{}' AS accepted_at,
            EXTRACT(EPOCH FROM now() - captured_at)::text AS age_s,
            object_count, source_mode
       FROM accepted_snapshots
      WHERE system = $1
      ORDER BY accepted_at DESC, snapshot_id DESC LIMIT 1`,
    [system],
  );
  const { rows: jobs } = await pool.query<JobRowLite>(
    `SELECT job_id, type, state, to_jsonb(finished_at) #>> '{}' AS finished_at, error
       FROM jobs WHERE system = $1 ORDER BY created_at DESC LIMIT 1`,
    [system],
  );

  const snap = snapshots[0] ?? null;
  const job = jobs[0] ?? null;
  const sp = policy?.systems.get(system) ?? null;
  const triggerMode: "schedule" | "webhook" | "manual" | null = sp
    ? sp.scheduleIntervalS !== null
      ? "schedule"
      : sp.webhook
        ? "webhook"
        : "manual"
    : null;

  const snapshot = snap
    ? {
        snapshot_id: snap.snapshot_id,
        captured_at: snap.captured_at,
        accepted_at: snap.accepted_at,
        age_s: Math.max(0, Math.round(Number(snap.age_s))),
        object_count: snap.object_count,
        source_mode: snap.source_mode,
      }
    : null;

  const lastJob = job
    ? {
        job_id: job.job_id,
        type: job.type,
        state: job.state,
        finished_at: job.finished_at,
        error: (job.error as ConnectionHealth["last_job"] extends null ? never : { code?: string }) ?? null,
      }
    : null;

  let freshness: ConnectionHealth["freshness"];
  if (policy === null) freshness = "unknown";
  else if (sp === null) freshness = "not_a_sync_source";
  else if (snapshot === null) freshness = "never_snapshotted";
  else freshness = snapshot.age_s > sp.freshnessThresholdS ? "stale" : "fresh";

  const jobFailed = job !== null && (job.state === "dead_lettered" || job.state === "cancelled");

  let status: ConnectionHealth["status"];
  let reason: string;
  if (freshness === "unknown") {
    status = "unknown";
    reason = "sync-policy.yaml could not be read from the knowledge base, so no freshness threshold applies";
  } else if (jobFailed) {
    status = "red";
    const code = (job!.error as { code?: string } | null)?.code;
    reason = `the last ${job!.type} job ended ${job!.state}${code ? ` (${code})` : ""}`;
  } else if (freshness === "stale") {
    status = "red";
    reason = `the newest accepted snapshot is ${snapshot!.age_s}s old, past this system's ${sp!.freshnessThresholdS}s threshold`;
  } else if (freshness === "never_snapshotted") {
    status = "amber";
    reason =
      "sync-policy.yaml lists this system, but no snapshot has ever been accepted for it";
  } else if (freshness === "not_a_sync_source") {
    // A publish target, or any connection the policy does not sync.
    // Freshness cannot be its verdict, so evidence that it has actually
    // been used is — and a connection with no such evidence is amber,
    // saying which of the two things is true rather than one of them.
    const evidence =
      job !== null
        ? `its last ${job.type} job ${job.state}`
        : snapshot !== null
          ? `it holds an accepted snapshot ${snapshot.age_s}s old`
          : null;
    if (evidence === null) {
      status = "amber";
      reason =
        "registered and not listed in sync-policy.yaml, so no snapshot is expected — " +
        "and no job has run for it yet, so nothing has exercised it";
    } else {
      status = "green";
      reason = `not a sync source (absent from sync-policy.yaml); ${evidence}`;
    }
  } else {
    status = "green";
    reason = `snapshot ${snapshot!.age_s}s old, inside the ${sp!.freshnessThresholdS}s threshold`;
  }

  return {
    status,
    reason,
    snapshot,
    policy: sp && triggerMode ? { threshold_s: sp.freshnessThresholdS, trigger_mode: triggerMode } : null,
    freshness,
    last_job: lastJob as ConnectionHealth["last_job"],
  };
}

// ---------------------------------------------------------------------------
// Wire shape

/**
 * A connection, as the API renders it.
 *
 * `payload` goes out as stored, which is safe for exactly one reason:
 * the write path above refuses to store material. Names are
 * user-influenceable and therefore neutralized on the way out (UI-5,
 * §6) — the F4 lesson is that object names are attacker-controlled.
 */
function renderConnection(row: SyncSystem, health: ConnectionHealth) {
  const payload = (row.payload ?? {}) as {
    config?: Record<string, unknown>;
    credentials?: { key?: unknown; ref?: unknown; required_for?: unknown }[];
  };
  return {
    system: neutralize(row.system),
    connector: { name: neutralize(row.connector_name), version_constraint: row.version_constraint },
    config: payload.config ?? {},
    // References, which is all there is to show. A reader can see which
    // env var or vault path a connection depends on and nothing about
    // what is behind it — the property J-4 buys and UI-8 protects.
    credentials: (payload.credentials ?? []).map((c) => ({
      key: typeof c.key === "string" ? neutralize(c.key) : null,
      ref: typeof c.ref === "string" ? neutralize(c.ref) : null,
      ...(Array.isArray(c.required_for) ? { required_for: c.required_for } : {}),
    })),
    health,
  };
}

// ---------------------------------------------------------------------------

export function registerConnections(app: FastifyInstance, deps: ConnectionsDeps): void {
  /**
   * The caller, and what their roles let them do here.
   *
   * `adminRoles` is a server-side role list — the same shape as the ops
   * surface's, resolved from the identity the IdP just asserted (UI-4:
   * the dashboard never knows a role the server doesn't). A steward
   * reads because the steward owns the estate's context; writing a
   * connection is provisioning, which is the ops owner's act (R3 in the
   * playbook's persona list).
   */
  async function viewerFor(
    req: FastifyRequest,
    reply: FastifyReply,
    need: "read" | "write",
  ): Promise<{ identity: Identity; ws: KbState | null; canWrite: boolean } | null> {
    const auth = await authenticate(deps, req, { write: need === "write" });
    if (!auth.ok) {
      await reply.code(auth.status).send({ error: auth.code, detail: auth.detail });
      return null;
    }
    const canWrite = auth.identity.roles.some((role) => deps.cfg.dashboard.adminRoles.includes(role));
    let ws: KbState | null = null;
    let isSteward = false;
    try {
      ws = await deps.kb.current();
      isSteward = profilesForRoles(ws, auth.identity.roles).has("steward");
    } catch (err) {
      // The KB being unreachable must not silently widen or narrow the
      // gate: an ops role is decided from config and still stands, and a
      // steward's read is refused rather than guessed at.
      deps.log("KB workspace unavailable while resolving connection access", err);
    }
    const refuse = async (detail: string): Promise<null> => {
      // D-114.1: a denied governance act is recorded, not only an
      // allowed one — the refused attempt is the row an auditor came for.
      await writeGovernanceAudit(
        deps.pool,
        {
          subject: auth.identity.subject,
          roles: auth.identity.roles,
          profile: isSteward ? "steward" : null,
          tool: "dashboard.connection.access",
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
        "registering, changing, deleting or testing a connection is an ops act; " +
          "this identity holds no ops role (dashboard spec §4, UI-7)",
      );
    }
    if (!canWrite && !isSteward) {
      return refuse("connections are visible to ops and steward identities (dashboard spec §4)");
    }
    return { identity: auth.identity, ws, canWrite };
  }

  /** One governed act, recorded (D-114.1). Never carries a payload —
   * `config` is customer configuration and `credentials` are references,
   * and neither belongs copied into the restricted store when the
   * connection row already holds both. */
  async function auditAct(
    viewer: { identity: Identity; ws: KbState | null },
    tool: string,
    args: Record<string, unknown>,
    resultMeta?: Record<string, unknown>,
  ): Promise<void> {
    await writeGovernanceAudit(
      deps.pool,
      {
        subject: viewer.identity.subject,
        roles: viewer.identity.roles,
        profile: null,
        tool,
        args,
        kbRef: viewer.ws?.headSha ?? null,
        decision: "allowed",
        decisionReason: null,
        ...(resultMeta ? { resultMeta } : {}),
      },
      deps.log,
    );
  }

  /** sync-policy.yaml at KB HEAD, or null when the KB cannot be read.
   * Null is a state the health shape carries; it is never a green. */
  async function policyOrNull(): Promise<SyncPolicy | null> {
    try {
      const { text } = await readRemoteFile(deps.cfg.sync, POLICY_PATH);
      return parsePolicy(text);
    } catch (err) {
      deps.log("sync-policy.yaml unreadable; connection freshness reported unknown", err);
      return null;
    }
  }

  function rejected(reply: FastifyReply, err: unknown): FastifyReply {
    if (err instanceof PayloadRejected) {
      return reply.code(400).send({ error: err.code, detail: err.message, fields: err.fields });
    }
    if (err instanceof RegistryWriteNotObserved) {
      // The D-84 shape, refused: the store did not take the write, so
      // nothing here reports that it did.
      deps.log("connection write not observed in the store", err);
      return reply.code(500).send({
        error: "write_not_observed",
        detail: err.message,
      });
    }
    throw err;
  }

  // -- list / read -----------------------------------------------------------

  app.get("/v1/dashboard/connections", async (req, reply) => {
    const viewer = await viewerFor(req, reply, "read");
    if (!viewer) return reply;
    const policy = await policyOrNull();
    const rows = await listSyncSystems(deps.pool);
    const connections = [];
    for (const row of rows) {
      connections.push(renderConnection(row, await healthFor(deps.pool, row.system, policy)));
    }
    return reply.send({
      api_version: API_VERSION,
      role_scope: viewer.canWrite ? "write" : "read",
      policy_readable: policy !== null,
      connections,
    });
  });

  app.get("/v1/dashboard/connections/:system", async (req, reply) => {
    const viewer = await viewerFor(req, reply, "read");
    if (!viewer) return reply;
    const { system } = req.params as { system: string };
    const row = await getSyncSystem(deps.pool, system);
    if (!row) return reply.code(404).send({ error: "not_found" });
    const policy = await policyOrNull();
    return reply.send({
      api_version: API_VERSION,
      role_scope: viewer.canWrite ? "write" : "read",
      policy_readable: policy !== null,
      connection: renderConnection(row, await healthFor(deps.pool, system, policy)),
    });
  });

  // -- create / update -------------------------------------------------------

  /**
   * PUT is the whole of create-and-update: a connection is named by its
   * system, so there is one address for it and registering twice is the
   * same act as changing it. The response is built from `stored` — the
   * row the registry read back — and there is no branch that answers
   * from `spec`.
   */
  app.put("/v1/dashboard/connections/:system", async (req, reply) => {
    const viewer = await viewerFor(req, reply, "write");
    if (!viewer) return reply;
    const { system } = req.params as { system: string };
    const existed = (await getSyncSystem(deps.pool, system)) !== null;
    let stored: SyncSystem;
    try {
      const spec = readConnectionSpec(system, req.body);
      stored = await upsertSyncSystem(deps.pool, spec);
    } catch (err) {
      return rejected(reply, err);
    }
    await auditAct(viewer, "dashboard.connection.upsert", { system, existed });
    const policy = await policyOrNull();
    return reply.code(existed ? 200 : 201).send({
      api_version: API_VERSION,
      // Said plainly because it is the gate clause: this body is a
      // rendering of the store's own row, re-read after the write.
      registered: true,
      read_back: true,
      connection: renderConnection(stored, await healthFor(deps.pool, system, policy)),
    });
  });

  app.delete("/v1/dashboard/connections/:system", async (req, reply) => {
    const viewer = await viewerFor(req, reply, "write");
    if (!viewer) return reply;
    const { system } = req.params as { system: string };
    let deleted: boolean;
    try {
      deleted = await deleteSyncSystem(deps.pool, system);
    } catch (err) {
      return rejected(reply, err);
    }
    if (!deleted) return reply.code(404).send({ error: "not_found" });
    await auditAct(viewer, "dashboard.connection.delete", { system });
    return reply.send({ api_version: API_VERSION, system, deleted: true, read_back: true });
  });

  // -- test ------------------------------------------------------------------

  /**
   * Run the connector's own probe against this connection, as a job.
   *
   * Nothing bespoke happens here: it is the ordinary `test_connection`
   * job type (job spec §4.2), carrying the registration's own config and
   * credential references, claimed by whichever runner hosts the
   * connector, executed by the SDK's builtin probe (capability §3
   * `health_probe: builtin`). The credentials are resolved by the same
   * runner seam that resolves them for a snapshot job — the probe opens
   * no path of its own, which is the point of running it there rather
   * than in the core.
   */
  const probeDeadlineS = deps.cfg.dashboard.probeTimeoutS || DEFAULT_PROBE_DEADLINE_S;

  app.post("/v1/dashboard/connections/:system/test", async (req, reply) => {
    const viewer = await viewerFor(req, reply, "write");
    if (!viewer) return reply;
    const { system } = req.params as { system: string };
    const row = await getSyncSystem(deps.pool, system);
    if (!row) return reply.code(404).send({ error: "not_found" });

    const payload = (row.payload ?? {}) as {
      config?: Record<string, unknown>;
      credentials?: Record<string, unknown>[];
    };
    let jobId: string;
    try {
      ({ jobId } = await enqueue(deps.pool, deps.cfg, {
        type: "test_connection",
        system,
        connector: { name: row.connector_name, version_constraint: row.version_constraint },
        payload: { config: payload.config ?? {}, credentials: payload.credentials ?? [] },
        deadline_s: probeDeadlineS,
        trigger: { kind: "dashboard", detail: { actor: viewer.identity.subject, act: "test_connection" } },
      }));
    } catch (err) {
      if (err instanceof EnqueueError) {
        return reply.code(400).send({ error: "invalid_test", detail: err.problems.join("; ") });
      }
      throw err;
    }
    // Audited at the act, not at the verdict: the probe *ran* under this
    // identity whether or not a runner answers in time, and a row written
    // only on success would omit exactly the probes worth investigating.
    await auditAct(viewer, "dashboard.connection.test", { system }, { job_id: jobId });

    const awaited = await awaitJobResult(
      deps.pool,
      deps.notifier ?? { waitFor: (_m, ms) => new Promise((r) => setTimeout(r, ms)) },
      jobId,
      probeDeadlineS * 1000,
    );

    if (awaited.status === "timeout") {
      return reply.code(202).send({
        api_version: API_VERSION,
        system,
        job_id: jobId,
        outcome: "pending",
        detail:
          `no runner has returned a verdict within ${probeDeadlineS}s. ` +
          "Either no runner hosts this connector, or the probe is still running; " +
          "the job is still in the queue and its outcome will show in this connection's health",
      });
    }

    if (awaited.status === "failed") {
      const error = (awaited.error ?? {}) as {
        code?: string;
        message?: string;
        retryable?: boolean;
        detail?: Record<string, unknown>;
      };
      const checks = Array.isArray(error.detail?.checks) ? error.detail!.checks : [];
      return reply.send({
        api_version: API_VERSION,
        system,
        job_id: jobId,
        outcome: "fail",
        error: {
          code: error.code ?? "internal",
          message: neutralize(error.message ?? "the probe failed"),
          retryable: error.retryable === true,
        },
        checks,
        // The re-auth prompt (A-3 gate clause). It is produced from the
        // error code, not from prose matching, and it names the
        // *references* whose values need attention — the product does
        // not hold those values and cannot show them (J-4/UI-8).
        ...(error.code === "auth_error" ? { reauth: reauthPrompt(row, error.message) } : {}),
      });
    }

    const result = (awaited.result ?? {}) as {
      ok?: boolean;
      checks?: unknown[];
      unprobed?: unknown[];
      connector?: Record<string, unknown>;
    };
    return reply.send({
      api_version: API_VERSION,
      system,
      job_id: jobId,
      outcome: "pass",
      connector: result.connector ?? null,
      checks: result.checks ?? [],
      // Carried to the surface rather than dropped: a capability the
      // probe could not exercise is not a capability that passed.
      unprobed: result.unprobed ?? [],
    });
  });

  /** Manual trigger for one connection — the "pull a snapshot now" act
   * playbook step 3 needs, as the caller's own identity. */
  app.post("/v1/dashboard/connections/:system/sync", async (req, reply) => {
    const viewer = await viewerFor(req, reply, "write");
    if (!viewer) return reply;
    const { system } = req.params as { system: string };
    const row = await getSyncSystem(deps.pool, system);
    if (!row) return reply.code(404).send({ error: "not_found" });
    const jobId = await triggerSystem(deps.pool, deps.cfg, row, {
      kind: "manual",
      detail: { actor: viewer.identity.subject, via: "dashboard" },
    });
    return reply.code(202).send({ api_version: API_VERSION, system, job_id: jobId, triggered: true });
  });
}

/**
 * What an operator has to do about an `auth_error`, in the terms this
 * product can actually offer: the source refused the credential behind
 * one of these references, and the value lives where the resolver reads
 * it, not here.
 */
function reauthPrompt(row: SyncSystem, message: string | undefined) {
  const payload = (row.payload ?? {}) as { credentials?: { key?: unknown; ref?: unknown }[] };
  const refs = (payload.credentials ?? [])
    .map((c) => (typeof c.ref === "string" ? c.ref : null))
    .filter((r): r is string => r !== null);
  return {
    required: true,
    system: row.system,
    connector: row.connector_name,
    message: neutralize(
      message ?? "the source refused the credential behind this connection's reference",
    ),
    credential_refs: refs,
    action:
      refs.length > 0
        ? `Refresh the value behind ${refs.join(", ")} where the resolver reads it, then run this test again. ` +
          "The connection itself needs no change — it holds the reference, never the value."
        : "This connection declares no credential reference, so the refusal is upstream of it — " +
          "check the connector's configuration and the source's own access rules.",
  };
}
