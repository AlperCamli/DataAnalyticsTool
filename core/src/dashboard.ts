/**
 * The dashboard's governed read APIs and its named write inlets
 * (dashboard spec §5 — the B-0 deliverables).
 *
 * Three reads: audit (U-12), publish deliveries (U-9), ledger triage
 * (U-5). Each authenticates the caller's own identity, filters by role
 * and subject **server-side**, paginates, and answers in a JSON shape
 * versioned with the core.
 *
 * UI-3 is the rule this module exists to make structural: a reporter
 * reads only rows whose subject is their own token-derived identity, and
 * the subject is taken from the resolved session — never from a query
 * parameter. A crafted `subject=` for somebody else is a 403 here, not a
 * filter the client was trusted to apply. The `fetch-all-filter-client`
 * trap CP-8 named cannot be fallen into from the client, because the
 * rows never leave the server.
 *
 * Role scope (D-102.2): steward audit scope v1 is **all**, not "own +
 * team" — no team concept exists in the role model, so a filter could
 * only invent one. Roles come from the IdP and are mapped to profiles by
 * the KB's own `roles.yaml` (UI-4: the dashboard never knows a role the
 * server doesn't). An absent map means *no* steward: the narrow reading
 * is the safe one.
 *
 * On text: audit rows are returned **as stored** (§5.1) — the evidence
 * extraction's whole claim is that what ran is what the server recorded,
 * and neutralizing statement text would corrupt the record it exists to
 * reproduce. Ledger text is the opposite case and is treated so: §5.3
 * requires server-scrubbed output, so titles, descriptions, rejection
 * reasons and proposals leave here already LED-R2-scrubbed (at storage)
 * and LED-R5-neutralized (here, at the render boundary).
 */

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import pg from "pg";
import { writeGovernanceAudit } from "./audit.js";
import { neutralize } from "./changelog.js";
import type { CoreConfig } from "./config.js";
import type { KbReader, KbState } from "./kbread.js";
import {
  deliverBatch,
  ENRICHMENT_REQUEST,
  getIssue,
  HUMAN_FILED,
  listEvents,
  listTriageIssues,
  normalizeQueryTerms,
  recordEvent,
  recordTriage,
  recordVerdict,
  returnToQueue,
  type LedgerEventRow,
  type TriageIssue,
} from "./ledger.js";
import type { Identity, OidcClient } from "./oidc.js";
import { authenticate, type SessionDeps } from "./session.js";
import { fqnVisible, visibilityScopes } from "./visibility.js";

export const API_VERSION = "1";

/** The queue's live set: everything not yet finished with. Overridable
 * per request with `status=` (csv) or `status=all`. */
const DEFAULT_QUEUE_STATUSES = ["open", "triaged", "approved", "batched"];

export interface DashboardDeps extends SessionDeps {
  cfg: CoreConfig;
  pool: pg.Pool;
  oidc: OidcClient;
  kb: KbReader;
  log: (msg: string, err?: unknown) => void;
}

/** The caller, as the server sees them: identity from the verifier, KB
 * state, visibility scopes, and the role scope those imply. */
interface Viewer {
  identity: Identity;
  ws: KbState;
  scopes: string[];
  profiles: Set<string>;
  isSteward: boolean;
}

/**
 * UI-4: view roles are server roles first. The caller's profiles are
 * exactly the KB `roles.yaml` entries whose `oidc_group` is among the
 * roles the IdP just asserted — the same mapping the MCP path's
 * visibility uses, read from the same file.
 */
export function profilesForRoles(ws: KbState, callerRoles: string[]): Set<string> {
  const out = new Set<string>();
  for (const entry of ws.roles ?? []) {
    if (entry.oidcGroup && entry.profile && callerRoles.includes(entry.oidcGroup)) {
      out.add(entry.profile);
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Pagination (UI-B): keyset cursors, server default, hard cap.

interface Page {
  limit: number;
  cursor: Record<string, unknown> | null;
}

class BadRequest extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
  }
}

function encodeCursor(value: Record<string, unknown>): string {
  return Buffer.from(JSON.stringify(value), "utf-8").toString("base64url");
}

function decodeCursor(raw: unknown): Record<string, unknown> | null {
  if (typeof raw !== "string" || !raw) return null;
  try {
    const parsed = JSON.parse(Buffer.from(raw, "base64url").toString("utf-8")) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("cursor is not an object");
    }
    return parsed as Record<string, unknown>;
  } catch {
    throw new BadRequest("invalid_cursor", "cursor is not a cursor this server issued");
  }
}

/**
 * Over-cap requests are clamped rather than refused — the caller learns
 * the effective size from `page.limit` and pages for the rest. A
 * nonsensical limit is a 400, because silently reinterpreting it would
 * hide a client bug behind plausible-looking data.
 */
function readPage(cfg: CoreConfig, query: Record<string, unknown>): Page {
  const raw = query.limit;
  let limit = cfg.dashboard.pageDefault;
  if (raw !== undefined && raw !== "") {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed < 1) {
      throw new BadRequest("invalid_argument", "limit must be a positive integer");
    }
    limit = Math.min(parsed, cfg.dashboard.pageMax);
  }
  return { limit, cursor: decodeCursor(query.cursor) };
}

function str(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

/** ISO-8601 in, ISO-8601 out; anything else is a 400 rather than a
 * silently-ignored filter that would over-return rows. */
function timestamp(value: unknown, field: string): string | undefined {
  const raw = str(value);
  if (raw === undefined) return undefined;
  if (Number.isNaN(Date.parse(raw))) {
    throw new BadRequest("invalid_argument", `${field} must be an ISO-8601 timestamp`);
  }
  return raw;
}

// ---------------------------------------------------------------------------
// Subject scoping (UI-3 / DT-1)

/**
 * The single place a request's subject scope is decided.
 *
 * A steward may name a subject or omit one (scope `all`, D-102.2).
 * Anyone else is pinned to their own resolved identity, and asking for
 * another subject is refused outright — the crafted-request case DT-1
 * proves. Note what is *not* here: no branch that reads a subject from
 * the client and trusts it.
 */
function subjectScope(
  viewer: Viewer,
  query: Record<string, unknown>,
): { subject: string | null; roleScope: "self" | "all" } {
  const requested = str(query.subject);
  if (viewer.isSteward) {
    return { subject: requested ?? null, roleScope: "all" };
  }
  if (requested !== undefined && requested !== viewer.identity.subject) {
    throw new BadRequest(
      "forbidden",
      "this role reads its own rows only; the subject filter is taken from the session",
    );
  }
  return { subject: viewer.identity.subject, roleScope: "self" };
}

// ---------------------------------------------------------------------------

export function registerDashboard(app: FastifyInstance, deps: DashboardDeps): void {
  /** Resolve the caller and the KB they are reading against. */
  async function viewerFor(
    req: FastifyRequest,
    reply: FastifyReply,
    opts: { write: boolean } = { write: false },
  ): Promise<Viewer | null> {
    const auth = await authenticate(deps, req, opts);
    if (!auth.ok) {
      await reply.code(auth.status).send({ error: auth.code, detail: auth.detail });
      return null;
    }
    let ws: KbState;
    try {
      ws = await deps.kb.current();
    } catch (err) {
      deps.log("KB workspace unavailable", err);
      await reply.code(503).send({ error: "kb_unavailable" });
      return null;
    }
    const profiles = profilesForRoles(ws, auth.identity.roles);
    return {
      identity: auth.identity,
      ws,
      scopes: visibilityScopes(ws.roles, auth.identity.roles),
      profiles,
      isSteward: profiles.has("steward"),
    };
  }

  /**
   * Record a governance act (D-114.1, closing spec §5.1).
   *
   * The profile string is the caller's resolved profile set, the same
   * one the ledger inlets stamp on an event — so an audit row and a
   * ledger event about the same act agree about who did it.
   */
  async function governanceAudit(
    viewer: Viewer,
    tool: string,
    args: Record<string, unknown>,
    opts: { decision: "allowed" | "denied"; reason?: string; resultMeta?: Record<string, unknown> },
  ): Promise<void> {
    await writeGovernanceAudit(
      deps.pool,
      {
        subject: viewer.identity.subject,
        roles: viewer.identity.roles,
        profile: [...viewer.profiles].sort().join(",") || null,
        tool,
        args,
        kbRef: viewer.ws.headSha,
        decision: opts.decision,
        decisionReason: opts.reason ?? null,
        ...(opts.resultMeta ? { resultMeta: opts.resultMeta } : {}),
      },
      deps.log,
    );
  }

  /** Uniform 400 for the argument/cursor failures thrown above. */
  function handle(reply: FastifyReply, err: unknown): FastifyReply {
    if (err instanceof BadRequest) {
      const status = err.code === "forbidden" ? 403 : 400;
      return reply.code(status).send({ error: err.code, detail: err.message });
    }
    throw err;
  }

  // -- (a) Audit read (§5.1, U-12) -------------------------------------------

  app.get("/v1/dashboard/audit", async (req, reply) => {
    const viewer = await viewerFor(req, reply);
    if (!viewer) return reply;
    const query = (req.query ?? {}) as Record<string, unknown>;
    let page: Page;
    let scope: { subject: string | null; roleScope: "self" | "all" };
    let since: string | undefined;
    let until: string | undefined;
    try {
      page = readPage(deps.cfg, query);
      scope = subjectScope(viewer, query);
      since = timestamp(query.since, "since");
      until = timestamp(query.until, "until");
    } catch (err) {
      return handle(reply, err);
    }
    const order = str(query.order) === "asc" ? "asc" : "desc";
    const decision = str(query.decision);
    if (decision !== undefined && !["allowed", "denied", "filtered"].includes(decision)) {
      return reply.code(400).send({ error: "invalid_argument", detail: "decision must be allowed, denied, or filtered" });
    }

    const params: unknown[] = [];
    const where: string[] = [];
    if (scope.subject !== null) {
      params.push(scope.subject);
      where.push(`subject = $${params.length}`);
    }
    if (since) {
      params.push(since);
      where.push(`ts >= $${params.length}::timestamptz`);
    }
    if (until) {
      params.push(until);
      where.push(`ts <= $${params.length}::timestamptz`);
    }
    const tool = str(query.tool);
    if (tool) {
      params.push(tool);
      where.push(`tool = $${params.length}`);
    }
    if (decision) {
      params.push(decision);
      where.push(`decision = $${params.length}`);
    }
    if (page.cursor) {
      params.push(page.cursor.ts, page.cursor.id);
      const n = params.length;
      where.push(
        `(ts, audit_id) ${order === "asc" ? ">" : "<"} ($${n - 1}::timestamptz, $${n}::uuid)`,
      );
    }
    params.push(page.limit + 1);

    // The record is rendered by Postgres, not rebuilt in JS: a JS Date
    // would truncate the stored microseconds, and the evidence
    // extraction's whole claim is that these rows are what the server
    // wrote. `to_jsonb` also fixes the key order, so the JSON is stable.
    const { rows } = await deps.pool.query<{ audit_id: string; ts: string; record: Record<string, unknown> }>(
      `SELECT a.audit_id, to_jsonb(a.ts) #>> '{}' AS ts, to_jsonb(a) AS record
         FROM audit_records a
        ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
        ORDER BY a.ts ${order === "asc" ? "ASC" : "DESC"}, a.audit_id ${order === "asc" ? "ASC" : "DESC"}
        LIMIT $${params.length}`,
      params,
    );
    const hasMore = rows.length > page.limit;
    const window_ = hasMore ? rows.slice(0, page.limit) : rows;
    const last = window_[window_.length - 1];

    return reply.send({
      api_version: API_VERSION,
      scope: { subject: scope.subject, role_scope: scope.roleScope },
      // §5.1: "audit records as stored" — args digests, decisions
      // including denied and filtered, with the true reason (M-8/M-4).
      rows: window_.map((row) => row.record),
      page: {
        limit: page.limit,
        order,
        next_cursor: hasMore && last ? encodeCursor({ ts: last.ts, id: last.audit_id }) : null,
      },
    });
  });

  // -- (b) Publish deliveries read (§5.2, U-9) -------------------------------

  app.get("/v1/dashboard/deliveries", async (req, reply) => {
    const viewer = await viewerFor(req, reply);
    if (!viewer) return reply;
    const query = (req.query ?? {}) as Record<string, unknown>;
    let page: Page;
    let scope: { subject: string | null; roleScope: "self" | "all" };
    let since: string | undefined;
    let until: string | undefined;
    try {
      page = readPage(deps.cfg, query);
      scope = subjectScope(viewer, query);
      since = timestamp(query.since, "since");
      until = timestamp(query.until, "until");
    } catch (err) {
      return handle(reply, err);
    }

    // A delivery's subject is the identity the audit trail recorded for
    // the call that made it — the same subject endpoint (a) filters on,
    // so the two reads agree about who owns what. `created_by` on the
    // artifact is the fallback for rows whose audit ref is gone.
    const params: unknown[] = [];
    const where: string[] = [];
    if (scope.subject !== null) {
      params.push(scope.subject);
      where.push(`coalesce(au.subject, ra.created_by) = $${params.length}`);
    }
    const artifactId = str(query.artifact_id);
    if (artifactId) {
      params.push(artifactId);
      where.push(`d.artifact_id = $${params.length}`);
    }
    if (since) {
      params.push(since);
      where.push(`d.delivered_at >= $${params.length}::timestamptz`);
    }
    if (until) {
      params.push(until);
      where.push(`d.delivered_at <= $${params.length}::timestamptz`);
    }
    if (page.cursor) {
      params.push(page.cursor.delivered_at, page.cursor.artifact_id, page.cursor.target);
      const n = params.length;
      where.push(
        `(d.delivered_at, d.artifact_id, d.target) < ($${n - 2}::timestamptz, $${n - 1}::text, $${n}::text)`,
      );
    }
    params.push(page.limit + 1);

    const { rows } = await deps.pool.query<{
      artifact_id: string;
      target: string;
      revision: number;
      content_hash: string;
      workspace_id: string;
      dataset_id: string;
      delivered_at: string;
      subject: string | null;
      attested_revision: number | null;
    }>(
      `SELECT d.artifact_id, d.target, d.revision, d.content_hash, d.workspace_id,
              d.dataset_id, to_jsonb(d.delivered_at) #>> '{}' AS delivered_at,
              coalesce(au.subject, ra.created_by) AS subject,
              at.revision AS attested_revision
         FROM model_deliveries d
         LEFT JOIN audit_records au ON au.audit_id = d.audit_ref
         LEFT JOIN report_artifacts ra
                ON ra.artifact_id = d.artifact_id AND ra.revision = d.revision
         LEFT JOIN report_attestations at
                ON at.artifact_id = d.artifact_id AND at.target = d.target
               AND at.revision = d.revision
        ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
        ORDER BY d.delivered_at DESC, d.artifact_id DESC, d.target DESC
        LIMIT $${params.length}`,
      params,
    );
    const hasMore = rows.length > page.limit;
    const window_ = hasMore ? rows.slice(0, page.limit) : rows;

    // Per-revision definition hashes (§5.2): the attestation history for
    // each pair on this page, so "what changed in this revision" (F-17)
    // has its rows without a second round trip.
    const artifactIds = [...new Set(window_.map((r) => r.artifact_id))];
    const { rows: attestations } = artifactIds.length
      ? await deps.pool.query<{
          artifact_id: string;
          target: string;
          revision: number;
          report_id: string;
          definition_hash: string;
          verified_at: string;
          attested_at: string;
        }>(
          `SELECT artifact_id, target, revision, report_id, definition_hash,
                  to_jsonb(verified_at) #>> '{}' AS verified_at,
                  to_jsonb(attested_at)  #>> '{}' AS attested_at
             FROM report_attestations
            WHERE artifact_id = ANY($1)
            ORDER BY artifact_id, target, revision`,
          [artifactIds],
        )
      : { rows: [] };

    const pairKey = (artifactId: string, target: string) => JSON.stringify([artifactId, target]);
    const byPair = new Map<string, typeof attestations>();
    for (const row of attestations) {
      const key = pairKey(row.artifact_id, row.target);
      byPair.set(key, [...(byPair.get(key) ?? []), row]);
    }
    const last = window_[window_.length - 1];

    return reply.send({
      api_version: API_VERSION,
      scope: { subject: scope.subject, role_scope: scope.roleScope },
      rows: window_.map((row) => ({
        artifact_id: row.artifact_id,
        target: row.target,
        subject: row.subject,
        delivery: {
          revision: row.revision,
          content_hash: row.content_hash,
          workspace_id: row.workspace_id,
          dataset_id: row.dataset_id,
          delivered_at: row.delivered_at,
        },
        // The loud state (F-15): a delivered revision no attestation
        // records means the two-call contract stopped between calls.
        dangling: row.attested_revision === null,
        attestations: (byPair.get(pairKey(row.artifact_id, row.target)) ?? []).map((a) => ({
          revision: a.revision,
          report_id: a.report_id,
          definition_hash: a.definition_hash,
          verified_at: a.verified_at,
          attested_at: a.attested_at,
        })),
      })),
      page: {
        limit: page.limit,
        order: "desc",
        next_cursor:
          hasMore && last
            ? encodeCursor({
                delivered_at: last.delivered_at,
                artifact_id: last.artifact_id,
                target: last.target,
              })
            : null,
      },
    });
  });

  // -- (c) Ledger triage read (§5.3, U-5) ------------------------------------

  /** M-4/LED-R2: an issue attributed to an object the caller cannot see
   * is absent, not refused — the same rule the MCP reads apply. */
  const issueVisible = (viewer: Viewer, issue: { object_fqn: string | null }): boolean =>
    issue.object_fqn === null || fqnVisible(viewer.ws, viewer.scopes, issue.object_fqn);

  /** LED-R5 at the render boundary + LED-R7 counts-only. Note there is
   * no subject field on this shape at all: the queue reports how many
   * distinct subjects, never which. */
  const renderIssue = (issue: TriageIssue) => ({
    issue_id: issue.issue_id,
    kind: issue.kind,
    title: neutralize(issue.title),
    ...(issue.object_fqn ? { object_fqn: issue.object_fqn } : {}),
    system: issue.system,
    status: issue.status,
    occurrences: issue.occurrences,
    distinct_subjects: issue.distinct_subjects,
    // D-106.5: an issue reopened after a rejection keeps its verdict
    // below and carries this count — together they are the steward's
    // "rejected before, refiled by N more".
    reopen_count: issue.reopen_count,
    first_seen: issue.first_seen,
    last_seen: issue.last_seen,
    links: issue.links,
    verdict: issue.verdict_at
      ? {
          by: issue.verdict_by,
          at: issue.verdict_at,
          reason: issue.verdict_reason === null ? null : neutralize(issue.verdict_reason),
        }
      : null,
    batch_id: issue.batch_id,
    resolution: issue.resolution,
    // Why a request came back rather than being drafted (§4). Present
    // only on one that did — an absent note is not an empty one.
    returned: issue.returned_at
      ? { at: issue.returned_at, note: issue.return_note === null ? null : neutralize(issue.return_note) }
      : null,
  });

  app.get("/v1/dashboard/ledger", async (req, reply) => {
    const viewer = await viewerFor(req, reply);
    if (!viewer) return reply;
    const query = (req.query ?? {}) as Record<string, unknown>;
    let page: Page;
    try {
      page = readPage(deps.cfg, query);
    } catch (err) {
      return handle(reply, err);
    }

    // The ledger's subject dimension is who filed an event on an issue.
    // A reporter's queue is what they filed; a crafted `filed_by` for
    // somebody else is the DT-1 refusal on this endpoint.
    const requestedFiledBy = str(query.filed_by);
    let filedBy: string | undefined;
    if (viewer.isSteward) {
      filedBy = requestedFiledBy;
    } else {
      if (requestedFiledBy !== undefined && requestedFiledBy !== viewer.identity.subject) {
        return reply.code(403).send({
          error: "forbidden",
          detail: "this role reads the requests it filed; the filer is taken from the session",
        });
      }
      filedBy = viewer.identity.subject;
    }

    const statusRaw = str(query.status);
    const statuses =
      statusRaw === "all" ? [] : statusRaw ? statusRaw.split(",").map((s) => s.trim()).filter(Boolean) : DEFAULT_QUEUE_STATUSES;

    const cursor = page.cursor;
    // Over-fetch so visibility filtering cannot empty a page that has
    // more rows behind it.
    const issues = await listTriageIssues(deps.pool, {
      statuses,
      ...(str(query.kind) ? { kind: str(query.kind)! } : {}),
      ...(str(query.system) ? { system: str(query.system)! } : {}),
      ...(filedBy !== undefined ? { filedBy } : {}),
      limit: page.limit + 1,
      ...(cursor
        ? {
            after: {
              occurrences: Number(cursor.occurrences),
              distinctSubjects: Number(cursor.distinct_subjects),
              lastSeen: String(cursor.last_seen),
              issueId: String(cursor.issue_id),
            },
          }
        : {}),
    });
    const hasMore = issues.length > page.limit;
    const windowIssues = (hasMore ? issues.slice(0, page.limit) : issues).filter((i) => issueVisible(viewer, i));
    const last = (hasMore ? issues.slice(0, page.limit) : issues).slice(-1)[0];

    return reply.send({
      api_version: API_VERSION,
      scope: { filed_by: filedBy ?? null, role_scope: viewer.isSteward ? "all" : "self" },
      issues: windowIssues.map(renderIssue),
      page: {
        limit: page.limit,
        order: "desc",
        next_cursor:
          hasMore && last
            ? encodeCursor({
                occurrences: last.occurrences,
                distinct_subjects: last.distinct_subjects,
                last_seen: last.last_seen,
                issue_id: last.issue_id,
              })
            : null,
      },
    });
  });

  /**
   * §8's issue view: one issue plus its event stream.
   *
   * Per-event `subject` is present for stewards only. That is not a
   * courtesy — a steward already reads every audit row's subject under
   * D-102.2, so withholding it here would be theatre; and LED-R7's
   * counts-only rule governs the *queue*, which never carries an
   * identity for anybody. Everyone else sees the stream without it.
   */
  const renderEvent = (viewer: Viewer, event: LedgerEventRow) => {
    const detail = { ...(event.detail ?? {}) };
    if (typeof detail.proposal === "string") detail.proposal = neutralize(detail.proposal);
    return {
      event_id: event.event_id,
      ts: event.ts,
      detector_class: event.detector_class,
      kind: event.kind,
      system: event.system,
      object_fqn: event.object_fqn,
      ...(viewer.isSteward ? { subject: event.subject } : {}),
      profile: event.profile,
      audit_ref: event.audit_ref,
      kb_ref: event.kb_ref,
      description: event.description === null ? null : neutralize(event.description),
      detail,
      issue_id: event.issue_id,
      issue_status: event.issue_status,
      issue_kind: event.issue_kind,
      routed_to: event.routed_to,
    };
  };

  app.get("/v1/dashboard/ledger/events", async (req, reply) => {
    const viewer = await viewerFor(req, reply);
    if (!viewer) return reply;
    const query = (req.query ?? {}) as Record<string, unknown>;
    let page: Page;
    let scope: { subject: string | null; roleScope: "self" | "all" };
    let since: string | undefined;
    let until: string | undefined;
    try {
      page = readPage(deps.cfg, query);
      scope = subjectScope(viewer, query);
      since = timestamp(query.since, "since");
      until = timestamp(query.until, "until");
    } catch (err) {
      return handle(reply, err);
    }
    const cursor = page.cursor;
    const events = await listEvents(deps.pool, {
      ...(since ? { since } : {}),
      ...(until ? { until } : {}),
      ...(str(query.kind) ? { kind: str(query.kind)! } : {}),
      ...(scope.subject !== null ? { subject: scope.subject } : {}),
      limit: page.limit + 1,
      ...(cursor ? { after: { ts: String(cursor.ts), eventId: String(cursor.id) } } : {}),
    });
    const hasMore = events.length > page.limit;
    const windowEvents = hasMore ? events.slice(0, page.limit) : events;
    const visible = windowEvents.filter((e) => issueVisible(viewer, e));
    const last = windowEvents[windowEvents.length - 1];

    return reply.send({
      api_version: API_VERSION,
      scope: { subject: scope.subject, role_scope: scope.roleScope },
      events: visible.map((e) => renderEvent(viewer, e)),
      page: {
        limit: page.limit,
        order: "asc",
        next_cursor: hasMore && last ? encodeCursor({ ts: last.ts, id: last.event_id }) : null,
      },
    });
  });

  app.get("/v1/dashboard/ledger/issues/:issueId", async (req, reply) => {
    const viewer = await viewerFor(req, reply);
    if (!viewer) return reply;
    const { issueId } = req.params as { issueId: string };
    if (!/^[0-9a-f-]{36}$/i.test(issueId)) {
      return reply.code(404).send({ error: "not_found" });
    }
    const issue = await getIssue(deps.pool, issueId);
    // M-4: hidden and nonexistent are the same answer.
    if (!issue || !issueVisible(viewer, issue)) {
      return reply.code(404).send({ error: "not_found" });
    }
    const events = await listEvents(deps.pool, { issueId, limit: deps.cfg.dashboard.pageMax });
    if (!viewer.isSteward && !events.some((e) => e.subject === viewer.identity.subject)) {
      return reply.code(404).send({ error: "not_found" });
    }
    return reply.send({
      api_version: API_VERSION,
      issue: renderIssue(issue),
      events: events.map((e) => renderEvent(viewer, e)),
    });
  });

  // -- (c) Ledger workflow writes (§5.3) -------------------------------------

  /** Both inlets share one body contract; identity is never in it. */
  function readInlet(body: unknown): { description: string; object: string | null; proposal: string | null } {
    const b = (body ?? {}) as Record<string, unknown>;
    const description = typeof b.description === "string" ? b.description : "";
    if (!description.trim()) {
      throw new BadRequest("invalid_argument", "description (string) required");
    }
    return {
      description,
      object: typeof b.object === "string" && b.object ? b.object : null,
      proposal: typeof b.proposal === "string" && b.proposal.trim() ? b.proposal : null,
    };
  }

  /**
   * The two inlets differ only in kind. LED-R3 is structural in both:
   * subject, session, profile and refs are set from the resolved
   * identity and the server's own state, and a client-supplied subject
   * is not read at all — there is no line here that reads one.
   */
  async function fileEvent(
    viewer: Viewer,
    kind: string,
    inlet: { description: string; object: string | null; proposal: string | null },
  ) {
    const scope = inlet.object ?? (normalizeQueryTerms(inlet.description) || "unattributed");
    return recordEvent(deps.pool, {
      detectorClass: 3,
      kind,
      scope,
      scopeLabel: inlet.object ?? scope,
      system: inlet.object ? inlet.object.split(".")[0]! : null,
      objectFqn: inlet.object,
      subject: viewer.identity.subject,
      sessionId: null,
      profile: [...viewer.profiles].sort().join(",") || null,
      kbRef: viewer.ws.headSha,
      description: inlet.description,
      // Scrubbed and bounded by recordEvent at storage (LED-R2).
      ...(inlet.proposal !== null ? { detail: { proposal: inlet.proposal } } : {}),
    });
  }

  app.post("/v1/dashboard/ledger/gaps", async (req, reply) => {
    const viewer = await viewerFor(req, reply, { write: true });
    if (!viewer) return reply;
    let inlet;
    try {
      inlet = readInlet(req.body);
    } catch (err) {
      return handle(reply, err);
    }
    const result = await fileEvent(viewer, HUMAN_FILED, inlet);
    return reply.code(201).send({
      api_version: API_VERSION,
      issue_id: result.issueId,
      occurrences: result.occurrences,
      routed_to: result.routedTo,
    });
  });

  app.post("/v1/dashboard/ledger/requests", async (req, reply) => {
    const viewer = await viewerFor(req, reply, { write: true });
    if (!viewer) return reply;
    let inlet;
    try {
      inlet = readInlet(req.body);
    } catch (err) {
      return handle(reply, err);
    }
    const result = await fileEvent(viewer, ENRICHMENT_REQUEST, inlet);
    return reply.code(201).send({
      api_version: API_VERSION,
      issue_id: result.issueId,
      occurrences: result.occurrences,
      routed_to: result.routedTo,
    });
  });

  /**
   * Steward verdicts (UI-11). Ledger state only: this handler calls
   * `recordVerdict`, which writes one row and holds nothing that could
   * reach a repository. No git call, no KB content — asserted by DT-11
   * behaviourally (the KB's refs and PR store are unchanged across an
   * approve) and statically (this module imports no git provider).
   */
  app.post("/v1/dashboard/ledger/issues/:issueId/verdict", async (req, reply) => {
    const viewer = await viewerFor(req, reply, { write: true });
    if (!viewer) return reply;
    const { issueId } = req.params as { issueId: string };
    if (!viewer.isSteward) {
      // D-114.1: the refusal is a governance act and is recorded as one.
      // A reporter's attempted verdict is exactly the row an auditor
      // came for, and a success-only log would not have it.
      await governanceAudit(viewer, "dashboard.ledger.verdict", { issue_id: issueId }, {
        decision: "denied",
        reason: "verdicts on knowledge requests are steward-gated (UI-11)",
      });
      return reply.code(403).send({
        error: "forbidden",
        detail: "verdicts on knowledge requests are steward-gated (dashboard spec UI-11)",
      });
    }
    const body = (req.body ?? {}) as Record<string, unknown>;
    const verdict = body.verdict;
    if (verdict !== "approve" && verdict !== "reject") {
      return reply.code(400).send({ error: "invalid_argument", detail: "verdict must be approve or reject" });
    }
    const reason = typeof body.reason === "string" ? body.reason : "";
    // A rejection the filer cannot read is not a decision, it is a
    // disappearance — the reply path (F-10) needs the reason.
    if (verdict === "reject" && !reason.trim()) {
      return reply.code(400).send({ error: "invalid_argument", detail: "reject requires a reason (it is shown to the filer)" });
    }
    const outcome = await recordVerdict(deps.pool, {
      issueId,
      verdict,
      reason: verdict === "reject" ? reason : null,
      by: viewer.identity.subject,
    });
    if (!outcome.ok) {
      const status = outcome.code === "not_found" ? 404 : outcome.code === "wrong_kind" ? 400 : 409;
      return reply.code(status).send({ error: outcome.code, detail: outcome.detail });
    }
    await governanceAudit(
      viewer,
      "dashboard.ledger.verdict",
      // The verdict and the issue, never the reason text: the reason is
      // ledger content with its own scrub and its own reader (the
      // filer), and copying it here would put user-authored text into
      // the restricted store for no gain the ledger row does not give.
      { issue_id: issueId, verdict },
      { decision: "allowed", resultMeta: { status: outcome.issue.status } },
    );
    return reply.send({ api_version: API_VERSION, issue: renderIssue(outcome.issue) });
  });


  /**
   * Hand a batched request back (§4's `batched → approved` transition).
   *
   * The enrich skill's honest exit: a request it cannot draft without
   * guessing goes back to the queue with a note saying what evidence
   * would unblock it, rather than into a document nobody can source.
   * Steward-gated like every other ledger workflow write — the skill
   * runs under the steward's own identity, so this is the same gate,
   * not a new one.
   */
  app.post("/v1/dashboard/ledger/issues/:issueId/return", async (req, reply) => {
    const viewer = await viewerFor(req, reply, { write: true });
    if (!viewer) return reply;
    const { issueId } = req.params as { issueId: string };
    if (!viewer.isSteward) {
      await governanceAudit(viewer, "dashboard.ledger.return", { issue_id: issueId }, {
        decision: "denied",
        reason: "returning a batched request is steward-gated (fault-ledger spec §4)",
      });
      return reply.code(403).send({
        error: "forbidden",
        detail: "returning a batched request to the queue is steward-gated (fault-ledger spec §4)",
      });
    }
    const body = (req.body ?? {}) as Record<string, unknown>;
    const note = typeof body.note === "string" ? body.note : "";
    // A return with no note is a silent drop wearing a state change: the
    // next steward reads `approved` and learns nothing about why it came
    // back or what would fix it.
    if (!note.trim()) {
      return reply.code(400).send({
        error: "invalid_argument",
        detail: "note (string) required — say what evidence would unblock this request",
      });
    }
    const outcome = await returnToQueue(deps.pool, { issueId, note });
    if (!outcome.ok) {
      const status = outcome.code === "not_found" ? 404 : outcome.code === "wrong_kind" ? 400 : 409;
      return reply.code(status).send({ error: outcome.code, detail: outcome.detail });
    }
    await governanceAudit(viewer, "dashboard.ledger.return", { issue_id: issueId }, {
      decision: "allowed",
      resultMeta: { status: outcome.issue.status },
    });
    return reply.send({ api_version: API_VERSION, issue: renderIssue(outcome.issue) });
  });


  /**
   * Gap triage (§8's one-click actions, §7's lifecycle).
   *
   * B-1 shipped the Knowledge Requests half of this module with its full
   * lifecycle and left the *gap* half read-only — a queue a steward could
   * read and not act on, which is the shortfall finding B1-F3 records.
   * Two actions, both steward-gated, both ledger state only: nothing here
   * writes KB content or calls git, for the same reason a verdict does
   * not (UI-11 governs the whole module, not only the request queue).
   */
  app.post("/v1/dashboard/ledger/issues/:issueId/triage", async (req, reply) => {
    const viewer = await viewerFor(req, reply, { write: true });
    if (!viewer) return reply;
    const { issueId } = req.params as { issueId: string };
    if (!viewer.isSteward) {
      await governanceAudit(viewer, "dashboard.ledger.triage", { issue_id: issueId }, {
        decision: "denied",
        reason: "acknowledging and dismissing ledger issues is steward-gated (fault-ledger §8)",
      });
      return reply.code(403).send({
        error: "forbidden",
        detail: "acknowledging and dismissing ledger issues is steward-gated (fault-ledger spec §8)",
      });
    }
    const body = (req.body ?? {}) as Record<string, unknown>;
    const action = body.action;
    if (action !== "acknowledge" && action !== "dismiss") {
      return reply.code(400).send({
        error: "invalid_argument",
        detail: "action must be acknowledge or dismiss",
      });
    }
    const reason = typeof body.reason === "string" ? body.reason : "";
    // Same rule as a rejection: a dismissal nobody can read is a
    // disappearance. L-4 will reopen this issue if it recurs, and the
    // next steward needs to know why the last one declined it.
    if (action === "dismiss" && !reason.trim()) {
      return reply.code(400).send({
        error: "invalid_argument",
        detail: "dismiss requires a reason (it is kept on the issue, and read if this recurs)",
      });
    }
    const outcome = await recordTriage(deps.pool, {
      issueId,
      action,
      reason: action === "dismiss" ? reason : null,
      by: viewer.identity.subject,
    });
    if (!outcome.ok) {
      const status = outcome.code === "not_found" ? 404 : outcome.code === "wrong_kind" ? 400 : 409;
      return reply.code(status).send({ error: outcome.code, detail: outcome.detail });
    }
    await governanceAudit(viewer, "dashboard.ledger.triage", { issue_id: issueId, action }, {
      decision: "allowed",
      resultMeta: { status: outcome.issue.status },
    });
    return reply.send({
      api_version: API_VERSION,
      issue: renderIssue(outcome.issue),
      // What the state change actually buys, in the response, because
      // "triaged" on its own tells a steward nothing about what happens
      // next — and "nothing happens next automatically" is the answer.
      note:
        action === "acknowledge"
          ? "Acknowledged. This gap is now on the enrich skill's work list — it reads triaged " +
            "ledger items first (skill spec §6 S1). Nothing drafts by itself: run enrich in a " +
            "session and it picks this up."
          : "Dismissed, with the reason kept on the issue. If the same gap recurs it reopens " +
            "automatically (L-4) and the next steward reads why it was declined.",
    });
  });

  /** The "deliver batch" trigger (§8): stamps approved requests batched
   * and hands the enrich skill a scoped work list. It drafts nothing. */
  app.post("/v1/dashboard/ledger/batches", async (req, reply) => {
    const viewer = await viewerFor(req, reply, { write: true });
    if (!viewer) return reply;
    if (!viewer.isSteward) {
      await governanceAudit(viewer, "dashboard.ledger.batch", {}, {
        decision: "denied",
        reason: "cutting a batch is steward-gated (fault-ledger spec §8)",
      });
      return reply.code(403).send({
        error: "forbidden",
        detail: "cutting a batch is steward-gated (fault-ledger spec §8)",
      });
    }
    const body = (req.body ?? {}) as Record<string, unknown>;
    const requested = body.max === undefined ? deps.cfg.dashboard.batchMax : Number(body.max);
    if (!Number.isInteger(requested) || requested < 1) {
      return reply.code(400).send({ error: "invalid_argument", detail: "max must be a positive integer" });
    }
    const max = Math.min(requested, deps.cfg.dashboard.batchMax);
    const { batchId, issues } = await deliverBatch(deps.pool, { max, by: viewer.identity.subject });
    await governanceAudit(
      viewer,
      "dashboard.ledger.batch",
      { max },
      { decision: "allowed", resultMeta: { batch_id: batchId, count: issues.length } },
    );
    return reply.code(201).send({
      api_version: API_VERSION,
      batch_id: batchId,
      count: issues.length,
      issues: issues.map(renderIssue),
      // The batch is a work list, not a draft. Said in the response
      // because the trigger's name invites the other reading.
      note:
        "These requests are stamped for drafting. Nothing has been written to the knowledge base " +
        "and no pull request exists yet — the enrich skill drafts from this list, and a human " +
        "merges the diff it produces.",
    });
  });

  // -- (d) the F-10 reply path: the filer's inbox (UI-D, DT-10) --------------

  /**
   * What happened to the things this caller filed.
   *
   * D-103.2 closed UI-D on the badge: resolutions and rejection reasons
   * reach the filer on their next dashboard session. This is that read.
   * `unread` is the badge's number, and it is the *server's* number —
   * the filer scope is the session's subject (the same rule the ledger
   * queue applies), and asking for somebody else's inbox is the DT-1
   * refusal rather than a filter the client was trusted to apply.
   *
   * A steward reading their own inbox sees their own filings, not the
   * estate's: this endpoint has no `all` scope, because "what happened
   * to what I asked for" is a personal question whatever role asks it.
   */
  app.get("/v1/dashboard/inbox", async (req, reply) => {
    const viewer = await viewerFor(req, reply);
    if (!viewer) return reply;
    const subject = viewer.identity.subject;
    const requested = str((req.query as Record<string, unknown>)?.subject);
    if (requested !== undefined && requested !== subject) {
      return reply.code(403).send({
        error: "forbidden",
        detail: "an inbox is its owner's; the filer is taken from the session",
      });
    }

    const { rows } = await deps.pool.query<{
      issue_id: string;
      kind: string;
      title: string;
      status: string;
      object_fqn: string | null;
      verdict_by: string | null;
      verdict_at: string | null;
      verdict_reason: string | null;
      resolution: Record<string, unknown> | null;
      resolved_at: string | null;
      reopen_count: number;
      acked_verdict_at: string | null;
      acked_at: string | null;
    }>(
      `SELECT i.issue_id, i.kind, i.title, i.status, i.object_fqn,
              i.verdict_by,
              to_jsonb(i.verdict_at)  #>> '{}' AS verdict_at,
              i.verdict_reason, i.resolution,
              to_jsonb(i.resolved_at) #>> '{}' AS resolved_at,
              i.reopen_count,
              to_jsonb(a.acked_verdict_at) #>> '{}' AS acked_verdict_at,
              to_jsonb(a.acked_at)         #>> '{}' AS acked_at
         FROM ledger_issues i
         LEFT JOIN dashboard_inbox_acks a
                ON a.issue_id = i.issue_id AND a.subject = $1
        WHERE i.status IN ('rejected', 'resolved')
          AND EXISTS (SELECT 1 FROM ledger_events e
                       WHERE e.issue_id = i.issue_id AND e.subject = $1)
        ORDER BY coalesce(i.resolved_at, i.verdict_at) DESC NULLS LAST, i.issue_id DESC
        LIMIT $2`,
      [subject, deps.cfg.dashboard.pageMax],
    );

    const items = rows
      .filter((row) => issueVisible(viewer, row))
      .map((row) => {
        // News is unread until acknowledged, and a *re*-verdict is news
        // again: comparing the acknowledged verdict time against the
        // current one is what makes a re-rejection after a refiling fire
        // the badge a second time rather than staying silently seen.
        const stamp = row.resolved_at ?? row.verdict_at;
        const unread =
          row.acked_at === null ||
          (stamp !== null && row.acked_verdict_at !== null && stamp > row.acked_verdict_at) ||
          (stamp !== null && row.acked_verdict_at === null);
        return {
          issue_id: row.issue_id,
          kind: row.kind,
          title: neutralize(row.title),
          ...(row.object_fqn ? { object_fqn: neutralize(row.object_fqn) } : {}),
          status: row.status,
          unread,
          reopen_count: row.reopen_count,
          // The two terminal shapes, each carrying what the filer needs
          // to act: a reason they can argue with, or a diff they can read.
          rejection:
            row.status === "rejected"
              ? {
                  by: row.verdict_by,
                  at: row.verdict_at,
                  reason: row.verdict_reason === null ? null : neutralize(row.verdict_reason),
                }
              : null,
          resolution:
            row.status === "resolved"
              ? {
                  at: row.resolved_at,
                  kind: (row.resolution?.kind as string | undefined) ?? null,
                  pr_url: (row.resolution?.pr_url as string | undefined) ?? null,
                }
              : null,
        };
      });

    return reply.send({
      api_version: API_VERSION,
      scope: { subject, role_scope: "self" },
      unread: items.filter((i) => i.unread).length,
      items,
    });
  });

  /** Mark inbox items seen, for this caller only. The subject is the
   * session's; there is no line here that reads one from the body. */
  app.post("/v1/dashboard/inbox/ack", async (req, reply) => {
    const viewer = await viewerFor(req, reply, { write: true });
    if (!viewer) return reply;
    const body = (req.body ?? {}) as Record<string, unknown>;
    const ids = Array.isArray(body.issue_ids)
      ? body.issue_ids.filter((id): id is string => typeof id === "string" && /^[0-9a-f-]{36}$/i.test(id))
      : [];
    if (ids.length === 0) {
      return reply.code(400).send({ error: "invalid_argument", detail: "issue_ids (uuid array) required" });
    }
    // Only issues this caller actually filed can be acknowledged by
    // them — otherwise an ack is a write against somebody else's row.
    const { rowCount } = await deps.pool.query(
      `INSERT INTO dashboard_inbox_acks (subject, issue_id, acked_verdict_at, acked_at)
       SELECT $1, i.issue_id, coalesce(i.resolved_at, i.verdict_at), now()
         FROM ledger_issues i
        WHERE i.issue_id = ANY($2::uuid[])
          AND EXISTS (SELECT 1 FROM ledger_events e
                       WHERE e.issue_id = i.issue_id AND e.subject = $1)
       ON CONFLICT (subject, issue_id) DO UPDATE
          SET acked_verdict_at = excluded.acked_verdict_at, acked_at = now()`,
      [viewer.identity.subject, ids],
    );
    return reply.send({ api_version: API_VERSION, acknowledged: rowCount ?? 0 });
  });
}
