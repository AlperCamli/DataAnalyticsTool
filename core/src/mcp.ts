/**
 * The MCP server (MCP tool reference spec, CP-4/M1): streamable HTTP on
 * `/mcp`, OAuth against the customer IdP via RFC 9728 protected-resource
 * metadata, and the eleven-tool surface with server-side enforcement on
 * every call.
 *
 * Enforcement chain per call (§3):
 *   identity  — resolved from the bearer token at the IdP on EVERY call
 *               (MCP-R1; token swap re-binds, MCP-R3; revocation is
 *               next-call effective, MT-9);
 *   profile   — bound from the client's config (`?profile=` — the
 *               compiled-config convenience) but validated server-side
 *               against the token's roles (MCP-R2); the allow-set is
 *               roles ∩ profile.tools.allow with qualifier enforcement
 *               (MCP-R4), and profile limits are injected server-side
 *               (MCP-R8);
 *   visibility— the roles.yaml map applied to every doc, search hit,
 *               and lineage node (M-4, MCP-R10/R11);
 *   audit     — one record per call including denied/filtered with the
 *               true reason (M-8, MCP-R13);
 *   limits    — per-identity rate limits (§7, MCP-R14).
 *
 * Requests are handled statelessly (one transport per request): there
 * is no session state a fixated token could inherit — the presented
 * token's identity governs, always.
 */

import { randomUUID } from "node:crypto";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import pg from "pg";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { writeAudit } from "./audit.js";
import { neutralize } from "./changelog.js";
import type { CoreConfig } from "./config.js";
import { createProvider } from "./gitkb.js";
import type { KbReader, KbState } from "./kbread.js";
import {
  FLAG_GAP_KINDS,
  listIssues,
  normalizeQueryTerms,
  recordEvent,
  registryKind,
} from "./ledger.js";
import type { Identity, OidcClient } from "./oidc.js";
import { parseProfile, profilePermitted, toolAllowed, type Profile } from "./profiles.js";
import { categoryForTool, type RateLimiter } from "./ratelimit.js";
import { buildIndex, search, type IndexEntry } from "./searchindex.js";
import { humanTrust, machineTrust, refsEnvelope, type TrustBlock } from "./trust.js";
import { validateRequest, SqlValidatorUnavailable } from "./valsql.js";
import { fqnVisible, pathVisible, visibilityScopes } from "./visibility.js";

export interface McpDeps {
  cfg: CoreConfig;
  pool: pg.Pool;
  oidc: OidcClient;
  kb: KbReader;
  limiter: RateLimiter;
  log: (msg: string, err?: unknown) => void;
}

// ---------------------------------------------------------------------------
// Tool registry (the eleven-tool surface; no other names exist)

const TOOL_DEFS: { name: string; description: string; inputSchema: Record<string, unknown> }[] = [
  {
    name: "search_context",
    description:
      "Resolve plain-language intent to entities, metrics, tables, and docs. Deterministic lexical ranking; returns one-liners + refs — follow with get_* tools.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string" },
        limit: { type: "number", default: 10 },
      },
      required: ["query"],
    },
  },
  {
    name: "get_entity",
    description: "Full entity doc (human-owned) with the maps: routing table, blend keys, and trust block.",
    inputSchema: {
      type: "object",
      properties: { name: { type: "string" } },
      required: ["name"],
    },
  },
  {
    name: "get_table",
    description:
      "Machine facts (from the latest accepted snapshot) + human semantics doc for any object, each with its own trust block. Works for tables, views, and API objects.",
    inputSchema: {
      type: "object",
      properties: { system: { type: "string" }, name: { type: "string" } },
      required: ["system", "name"],
    },
  },
  {
    name: "get_metric",
    description: "Metric doc with per-system implementations and certification trail.",
    inputSchema: {
      type: "object",
      properties: { name: { type: "string" } },
      required: ["name"],
    },
  },
  {
    name: "get_lineage",
    description:
      "Walk the lineage graph from an object FQN: nodes + edges with operations and evidence tiers. The \"why doesn't this match the source system\" tool.",
    inputSchema: {
      type: "object",
      properties: {
        object: { type: "string" },
        direction: { type: "string", enum: ["upstream", "downstream", "both"], default: "both" },
        depth: { type: "number", default: 3 },
      },
      required: ["object"],
    },
  },
  {
    name: "validate_sql",
    description:
      "Validate a query against the latest accepted snapshot: SQL dialect (parser-based, SELECT-only) or API dialect (documented dimensions/metrics). A pass issues a signed validation token.",
    inputSchema: {
      type: "object",
      properties: {
        system: { type: "string" },
        request: {
          type: "object",
          properties: {
            dialect: { type: "string", enum: ["sql", "api"] },
            statement: { type: "string" },
            operation: { type: "string" },
            body: { type: "object" },
          },
          required: ["dialect"],
        },
      },
      required: ["system", "request"],
    },
  },
  {
    name: "execute_sql",
    description: "Execute a validated query (requires a validation token). Arrives with the CP-6 execution gateway.",
    inputSchema: {
      type: "object",
      properties: {
        system: { type: "string" },
        request: { type: "object" },
        validation_token: { type: "string" },
      },
      required: ["system", "request", "validation_token"],
    },
  },
  {
    name: "publish_report",
    description: "Publish a report artifact to a configured target. Arrives with the CP-6/CP-7 publish path.",
    inputSchema: {
      type: "object",
      properties: { artifact: { type: "object" }, target: { type: "string" } },
      required: ["artifact", "target"],
    },
  },
  {
    name: "report_freshness",
    description: "Estate summary: per-system snapshot age and triggers, doc-status counts, open sync PRs, freshness warnings.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "flag_gap",
    description:
      "File a context gap into the fault ledger. Returns the deduplicated issue id, its occurrence count, and who it is routed to.",
    inputSchema: {
      type: "object",
      properties: {
        kind: { type: "string", enum: [...FLAG_GAP_KINDS] },
        description: { type: "string" },
        object: { type: "string" },
      },
      required: ["kind", "description"],
    },
  },
  {
    name: "list_gaps",
    description: "Steward-gated triage reads over the fault ledger issues.",
    inputSchema: {
      type: "object",
      properties: {
        status: { type: "string", enum: ["open", "triaged"], default: "open" },
        kind: { type: "string" },
        system: { type: "string" },
        limit: { type: "number", default: 20 },
      },
    },
  },
];

/** Tools whose call takes a system/target qualifier (MCP-R4). */
function qualifierArg(tool: string, args: Record<string, unknown>): string | undefined {
  if (tool === "execute_sql") return typeof args.system === "string" ? args.system : undefined;
  if (tool === "publish_report") return typeof args.target === "string" ? args.target : undefined;
  return undefined;
}

/** list_gaps is S-gated (L-7/LED-R1): server-resolved profile only. */
const STEWARD_GATED = new Set(["list_gaps"]);
const STEWARD_PROFILES = new Set(["steward", "benchmark"]);

interface ToolOutcome {
  payload: Record<string, unknown>;
  isError?: boolean;
  decision?: "allowed" | "filtered";
  reason?: string;
  resultMeta?: Record<string, unknown>;
  statementText?: string | null;
}

const err = (code: string, message: string, extra: Record<string, unknown> = {}): ToolOutcome => ({
  payload: { code, message, ...extra },
  isError: true,
  resultMeta: { error: code },
});

// Search index cache per workspace build.
const indexCache = new WeakMap<KbState, IndexEntry[]>();
function indexFor(ws: KbState): IndexEntry[] {
  let index = indexCache.get(ws);
  if (!index) {
    index = buildIndex(ws);
    indexCache.set(ws, index);
  }
  return index;
}

function slug(name: string): string {
  return name.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
}

function trustForEntry(ws: KbState, entry: IndexEntry): TrustBlock | undefined {
  const doc = ws.docs.get(entry.path);
  if (!doc) return undefined;
  if (doc.docClass === "machine-object" || doc.docClass === "machine-group" || doc.docClass === "machine-index") {
    const system = entry.path.startsWith("systems/") ? entry.path.split("/")[1]! : "";
    return system ? machineTrust(ws, system) : undefined;
  }
  if (doc.docClass && doc.docClass !== "human-notes") return humanTrust(ws, doc);
  return undefined; // repo-level docs: no trust block (KB-F)
}

// ---------------------------------------------------------------------------
// Tool implementations

interface CallContext {
  deps: McpDeps;
  ws: KbState;
  identity: Identity;
  profile: Profile;
  scopes: string[];
  sessionId: string | null;
  auditId: string;
}

async function toolSearchContext(ctx: CallContext, args: Record<string, unknown>): Promise<ToolOutcome> {
  const query = typeof args.query === "string" ? args.query : "";
  if (!query.trim()) return err("invalid_argument", "query (string) required");
  const limit = Math.min(Math.max(Number(args.limit ?? 10) || 10, 1), 50);
  const hits = search(indexFor(ctx.ws), ctx.scopes, query, limit);
  const results = hits.map((hit) => {
    const trust = trustForEntry(ctx.ws, hit.entry);
    return {
      ref_kind: hit.entry.refKind,
      path: hit.entry.path,
      ...(hit.entry.fqn ? { fqn: hit.entry.fqn } : {}),
      one_liner: hit.entry.oneLiner || hit.entry.title,
      ...(trust ? { trust } : {}),
    };
  });
  let ledgerEvent = false;
  if (results.length === 0) {
    // Class-1 zero_result_search (§6.1, MT-7) — server-side, no agent
    // cooperation required; scope is the scrubbed normalized terms.
    const scope = normalizeQueryTerms(query) || "empty-query";
    await recordEvent(ctx.deps.pool, {
      detectorClass: 1,
      kind: "coverage_gap",
      scope,
      scopeLabel: scope,
      subject: ctx.identity.subject,
      sessionId: ctx.sessionId,
      profile: ctx.profile.name,
      auditRef: ctx.auditId,
      kbRef: ctx.ws.headSha,
      snapshotRef: refsEnvelope(ctx.ws).snapshot_ref,
      detail: { rule: "zero_result_search" },
    });
    ledgerEvent = true;
  }
  return {
    payload: { results, refs: refsEnvelope(ctx.ws) },
    resultMeta: { results: results.length, ...(ledgerEvent ? { ledger_event: "coverage_gap" } : {}) },
  };
}

async function toolGetEntity(ctx: CallContext, args: Record<string, unknown>): Promise<ToolOutcome> {
  const name = typeof args.name === "string" ? args.name : "";
  if (!name) return err("invalid_argument", "name (string) required");
  let docPath = `entities/${slug(name)}.md`;
  if (!ctx.ws.docs.has(docPath)) {
    const lower = name.trim().toLowerCase();
    const byAlias = indexFor(ctx.ws).find(
      (entry) => entry.refKind === "entity" && (entry.aliases.includes(lower) || entry.title.toLowerCase() === lower),
    );
    if (byAlias) docPath = byAlias.path;
  }
  const doc = ctx.ws.docs.get(docPath);
  if (doc && !pathVisible(ctx.scopes, docPath)) {
    // M-4: hidden ⇒ not_found; the audit records the true reason.
    return { ...err("not_found", `no entity ${name}`), decision: "filtered", reason: "hidden by visibility map" };
  }
  if (!doc) {
    const suggestions = indexFor(ctx.ws)
      .filter((entry) => entry.refKind === "entity" && pathVisible(ctx.scopes, entry.path))
      .map((entry) => entry.title)
      .slice(0, 5);
    return err("not_found", `no entity ${name}`, { suggestions });
  }
  return {
    payload: {
      path: doc.path,
      title: doc.title,
      front_matter: doc.fm ?? {},
      content: doc.body,
      trust: humanTrust(ctx.ws, doc),
      refs: refsEnvelope(ctx.ws),
    },
    resultMeta: { path: doc.path },
  };
}

async function toolGetTable(ctx: CallContext, args: Record<string, unknown>): Promise<ToolOutcome> {
  const system = typeof args.system === "string" ? args.system : "";
  const name = typeof args.name === "string" ? args.name : "";
  if (!system || !name) return err("invalid_argument", "system and name (strings) required");
  const state = ctx.ws.systems.get(system);
  if (!state) return err("not_found", `no accepted snapshot for system ${system}`);
  let fqn: string | null = null;
  if (name.includes(".")) {
    fqn = `${system}.${name}`;
    if (!state.objects.has(fqn)) fqn = null;
  } else {
    const candidates = [...state.objects.values()].filter((o) => o.name === name);
    if (candidates.length === 1) fqn = candidates[0]!.fqn;
    else if (candidates.length > 1) {
      return err("invalid_argument", `name ${name} is ambiguous in ${system}; qualify the schema`, {
        candidates: candidates.map((c) => c.fqn).filter((f) => fqnVisible(ctx.ws, ctx.scopes, f)),
      });
    }
  }
  if (!fqn) return err("not_found", `no object ${name} in ${system}`);
  if (!fqnVisible(ctx.ws, ctx.scopes, fqn)) {
    return { ...err("not_found", `no object ${name} in ${system}`), decision: "filtered", reason: "hidden by visibility map" };
  }
  const object = state.objects.get(fqn)!;
  const machineInfo = ctx.ws.machineByFqn.get(fqn);
  const machineDoc = machineInfo ? ctx.ws.docs.get(machineInfo.path) : undefined;
  const humanPath = machineInfo
    ? machineInfo.path.replace(/\.schema\.md$/, ".md")
    : null;
  const humanDoc = humanPath ? ctx.ws.docs.get(humanPath) : undefined;
  const referencedBy: string[] = [];
  for (const other of state.objects.values()) {
    const foreign = (other.keys as { foreign?: { ref?: string }[] }).foreign;
    if (!Array.isArray(foreign)) continue;
    for (const fk of foreign) {
      if (fk.ref === `${object.schema}.${object.name}` && fqnVisible(ctx.ws, ctx.scopes, other.fqn)) {
        referencedBy.push(other.fqn);
      }
    }
  }
  return {
    payload: {
      fqn,
      kind: object.kind,
      hot: humanDoc !== undefined,
      machine: {
        path: machineInfo?.path ?? null,
        content: machineDoc?.body ?? null,
        trust: machineTrust(ctx.ws, system),
      },
      human: humanDoc
        ? { path: humanPath, content: humanDoc.body, front_matter: humanDoc.fm ?? {}, trust: humanTrust(ctx.ws, humanDoc) }
        : null,
      referenced_by: referencedBy.sort(),
      refs: refsEnvelope(ctx.ws),
    },
    resultMeta: { fqn, render_lag: state.renderLag },
  };
}

async function toolGetMetric(ctx: CallContext, args: Record<string, unknown>): Promise<ToolOutcome> {
  const name = typeof args.name === "string" ? args.name : "";
  if (!name) return err("invalid_argument", "name (string) required");
  const docPath = `metrics/${slug(name)}.md`;
  const doc = ctx.ws.docs.get(docPath);
  if (doc && !pathVisible(ctx.scopes, docPath)) {
    return { ...err("not_found", `no metric ${name}`), decision: "filtered", reason: "hidden by visibility map" };
  }
  if (!doc) return err("not_found", `no metric ${name}`);
  const trust = humanTrust(ctx.ws, doc);
  return {
    payload: {
      path: doc.path,
      title: doc.title,
      front_matter: doc.fm ?? {},
      content: doc.body,
      certified: trust.status === "verified",
      trust,
      refs: refsEnvelope(ctx.ws),
    },
    resultMeta: { path: doc.path, certified: trust.status === "verified" },
  };
}

async function toolGetLineage(ctx: CallContext, args: Record<string, unknown>): Promise<ToolOutcome> {
  const object = typeof args.object === "string" ? args.object : "";
  if (!object) return err("invalid_argument", "object (FQN string) required");
  const direction = args.direction === "upstream" || args.direction === "downstream" ? args.direction : "both";
  const depth = Math.min(Math.max(Number(args.depth ?? 3) || 3, 1), 10);
  const graph = ctx.ws.graph;
  if (!graph) return err("not_found", "no lineage graph in the KB");
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  if (!nodeById.has(object)) return err("not_found", `no lineage node ${object}`);
  if (!fqnVisible(ctx.ws, ctx.scopes, object)) {
    return { ...err("not_found", `no lineage node ${object}`), decision: "filtered", reason: "hidden by visibility map" };
  }
  const edges = graph.edges as { id: string; source: string; target: string }[];
  const downstream = new Map<string, typeof edges>();
  const upstream = new Map<string, typeof edges>();
  for (const edge of edges) {
    if (!downstream.has(edge.source)) downstream.set(edge.source, []);
    downstream.get(edge.source)!.push(edge);
    if (!upstream.has(edge.target)) upstream.set(edge.target, []);
    upstream.get(edge.target)!.push(edge);
  }
  const visited = new Set<string>([object]);
  const includedEdges = new Map<string, (typeof edges)[number]>();
  let cycles = false;
  let frontier = [object];
  for (let hop = 0; hop < depth && frontier.length > 0; hop += 1) {
    const next: string[] = [];
    for (const fqn of frontier) {
      const candidates = [
        ...(direction !== "upstream" ? downstream.get(fqn) ?? [] : []),
        ...(direction !== "downstream" ? upstream.get(fqn) ?? [] : []),
      ];
      for (const edge of candidates) {
        const neighbor = edge.source === fqn ? edge.target : edge.source;
        // MCP-R11 (P-E amendment): hidden nodes and their edges are
        // omitted — never masked-but-revealed — and never traversed.
        if (!fqnVisible(ctx.ws, ctx.scopes, neighbor)) continue;
        includedEdges.set(edge.id, edge);
        if (visited.has(neighbor)) {
          if (neighbor !== fqn) cycles = true;
          continue;
        }
        visited.add(neighbor);
        next.push(neighbor);
      }
    }
    frontier = next;
  }
  const nodes = [...visited].sort().map((fqn) => {
    const node = nodeById.get(fqn) ?? { id: fqn };
    const humanPath = ctx.ws.humanByFqn.get(fqn);
    const humanDoc = humanPath ? ctx.ws.docs.get(humanPath) : undefined;
    return { ...node, ...(humanDoc ? { trust: humanTrust(ctx.ws, humanDoc) } : {}) };
  });
  return {
    payload: {
      object,
      direction,
      depth,
      nodes,
      edges: [...includedEdges.values()].sort((a, b) => (a.id < b.id ? -1 : 1)),
      cycles_detected: cycles,
      refs: refsEnvelope(ctx.ws),
    },
    resultMeta: { nodes: nodes.length, edges: includedEdges.size },
  };
}

async function toolValidateSql(ctx: CallContext, args: Record<string, unknown>): Promise<ToolOutcome> {
  const system = typeof args.system === "string" ? args.system : "";
  const request = (args.request as Record<string, unknown> | undefined) ?? {};
  if (!system) return err("invalid_argument", "system (string) required");
  let outcome;
  try {
    outcome = await validateRequest(
      ctx.deps.cfg,
      ctx.deps.pool,
      ctx.ws,
      ctx.identity,
      ctx.profile,
      { system, request },
    );
  } catch (e) {
    if (e instanceof SqlValidatorUnavailable) {
      return err("upstream_error", `SQL validator unavailable: ${e.message}`);
    }
    throw e;
  }
  if (outcome.error) return err(outcome.error.code, outcome.error.message);
  const statementText =
    typeof request.statement === "string"
      ? request.statement
      : JSON.stringify({ operation: request.operation, body: request.body });
  return {
    payload: {
      verdict: outcome.verdict,
      findings: outcome.findings,
      guardrails: outcome.guardrails,
      ...(outcome.validationToken
        ? { validation_token: outcome.validationToken.token, token_expires_at: outcome.validationToken.expiresAt }
        : {}),
      refs: refsEnvelope(ctx.ws),
    },
    resultMeta: {
      verdict: outcome.verdict,
      system,
      cited_objects: outcome.citedObjects,
      finding_codes: outcome.findings.map((f) => f.code),
    },
    statementText,
  };
}

async function toolExecuteStub(_ctx: CallContext, _args: Record<string, unknown>): Promise<ToolOutcome> {
  return err(
    "upstream_error",
    "execute_sql arrives with the CP-6 execution gateway (M2); validation tokens issued now are verifiable by the same library the gateway will use",
  );
}

async function toolPublishStub(_ctx: CallContext, _args: Record<string, unknown>): Promise<ToolOutcome> {
  return err("upstream_error", "publish_report arrives with the CP-6/CP-7 publish path");
}

async function toolReportFreshness(ctx: CallContext, _args: Record<string, unknown>): Promise<ToolOutcome> {
  const { rows: warningRows } = await ctx.deps.pool.query<{
    system: string;
    raised_at: Date;
    age_s: string;
    threshold_s: string;
  }>(`SELECT system, raised_at, age_s, threshold_s FROM freshness_warnings ORDER BY system`);
  const warnings = new Map(warningRows.map((w) => [w.system, w]));
  const policySystems =
    ((ctx.ws.syncPolicy?.systems as Record<string, Record<string, unknown>> | undefined) ?? {});
  const systems = [...ctx.ws.systems.values()].map((state) => {
    const policy = policySystems[state.system] ?? {};
    const warning = warnings.get(state.system);
    return {
      system: state.system,
      last_snapshot_at: state.capturedAt,
      accepted_at: state.acceptedAt,
      trigger: policy.triggers ?? null,
      freshness_threshold: policy.freshness_threshold ?? null,
      age_warning: warning
        ? { raised_at: warning.raised_at, age_s: Number(warning.age_s), threshold_s: Number(warning.threshold_s) }
        : null,
    };
  });
  const statusCounts: Record<string, number> = {};
  for (const doc of ctx.ws.docs.values()) {
    if (!doc.docClass || !["human-object", "human-group", "entity", "metric", "lineage-note"].includes(doc.docClass)) {
      continue;
    }
    if (!pathVisible(ctx.scopes, doc.path)) continue;
    const status = typeof doc.fm?.status === "string" ? doc.fm.status : "draft";
    statusCounts[status] = (statusCounts[status] ?? 0) + 1;
  }
  let openSyncPrs: { number: number; url: string }[] = [];
  if (ctx.deps.cfg.sync.enabled) {
    try {
      openSyncPrs = (await createProvider(ctx.deps.cfg.sync).listOpenSyncPrs()).map((pr) => ({
        number: pr.number,
        url: pr.url,
      }));
    } catch {
      // provider unreachable — freshness still serves ops-state facts
    }
  }
  return {
    payload: {
      systems,
      doc_status_counts: statusCounts,
      open_sync_prs: openSyncPrs,
      refs: refsEnvelope(ctx.ws),
    },
    resultMeta: { systems: systems.length },
  };
}

async function toolFlagGap(ctx: CallContext, args: Record<string, unknown>): Promise<ToolOutcome> {
  const kind = typeof args.kind === "string" ? args.kind : "";
  const description = typeof args.description === "string" ? args.description : "";
  const object = typeof args.object === "string" && args.object ? args.object : null;
  if (!FLAG_GAP_KINDS.includes(kind as (typeof FLAG_GAP_KINDS)[number])) {
    return err("invalid_argument", `kind must be one of ${FLAG_GAP_KINDS.join(", ")}`);
  }
  if (!description.trim()) return err("invalid_argument", "description (string) required");
  const scope = object ?? (normalizeQueryTerms(description) || "unattributed");
  // LED-R3: identity/session/profile/refs are server-set — nothing the
  // client passes can forge them (the schema has no such fields; extras
  // are ignored by construction).
  const result = await recordEvent(ctx.deps.pool, {
    detectorClass: kind === "result_disputed" ? 3 : 2,
    kind: registryKind(kind),
    scope,
    scopeLabel: object ?? scope,
    system: object ? object.split(".")[0] : null,
    objectFqn: object,
    subject: ctx.identity.subject,
    sessionId: ctx.sessionId,
    profile: ctx.profile.name,
    auditRef: ctx.auditId,
    kbRef: ctx.ws.headSha,
    snapshotRef: refsEnvelope(ctx.ws).snapshot_ref,
    description,
  });
  return {
    payload: {
      issue_id: result.issueId,
      occurrences: result.occurrences,
      routed_to: result.routedTo,
      refs: refsEnvelope(ctx.ws),
    },
    resultMeta: { issue_id: result.issueId, occurrences: result.occurrences },
  };
}

async function toolListGaps(ctx: CallContext, args: Record<string, unknown>): Promise<ToolOutcome> {
  // LED-R1: steward/benchmark server-resolved profiles only — enforced
  // here as well as via the profile allowlist, so a mis-authored custom
  // profile cannot widen the surface.
  if (!STEWARD_PROFILES.has(ctx.profile.name)) {
    return {
      ...err("permission_denied", "list_gaps is limited to the steward and benchmark profiles"),
      decision: "filtered",
      reason: `profile ${ctx.profile.name} is not steward-gated`,
    };
  }
  const issues = await listIssues(ctx.deps.pool, {
    status: typeof args.status === "string" ? args.status : "open",
    ...(typeof args.kind === "string" ? { kind: args.kind } : {}),
    ...(typeof args.system === "string" ? { system: args.system } : {}),
    limit: Number(args.limit ?? 20) || 20,
  });
  // LED-R2 visibility filter + LED-R7 counts-only + LED-R5 neutralized
  // text at the render point.
  const visible = issues.filter(
    (issue) => issue.object_fqn === null || fqnVisible(ctx.ws, ctx.scopes, issue.object_fqn),
  );
  return {
    payload: {
      issues: visible.map((issue) => ({
        issue_id: issue.issue_id,
        kind: issue.kind,
        title: neutralize(issue.title),
        ...(issue.object_fqn ? { object_fqn: issue.object_fqn } : {}),
        occurrences: issue.occurrences,
        distinct_subjects: issue.distinct_subjects,
        first_seen: issue.first_seen,
        last_seen: issue.last_seen,
        links: issue.links,
      })),
      refs: refsEnvelope(ctx.ws),
    },
    resultMeta: { issues: visible.length, filtered: issues.length - visible.length },
  };
}

const TOOL_IMPLS: Record<string, (ctx: CallContext, args: Record<string, unknown>) => Promise<ToolOutcome>> = {
  search_context: toolSearchContext,
  get_entity: toolGetEntity,
  get_table: toolGetTable,
  get_metric: toolGetMetric,
  get_lineage: toolGetLineage,
  validate_sql: toolValidateSql,
  execute_sql: toolExecuteStub,
  publish_report: toolPublishStub,
  report_freshness: toolReportFreshness,
  flag_gap: toolFlagGap,
  list_gaps: toolListGaps,
};

// ---------------------------------------------------------------------------
// Transport wiring

export function registerMcp(app: FastifyInstance, deps: McpDeps): void {
  const { cfg } = deps;

  const resourceMetadata = {
    resource: `${cfg.mcp.publicUrl}/mcp`,
    authorization_servers: [cfg.mcp.oidcIssuer],
    bearer_methods_supported: ["header"],
  };
  app.get("/.well-known/oauth-protected-resource", async () => resourceMetadata);
  app.get("/.well-known/oauth-protected-resource/mcp", async () => resourceMetadata);

  const unauthorized = (reply: FastifyReply, detail: string) =>
    reply
      .code(401)
      .header(
        "www-authenticate",
        `Bearer resource_metadata="${cfg.mcp.publicUrl}/.well-known/oauth-protected-resource"`,
      )
      .send({ error: "unauthorized", detail });

  app.route({
    method: ["GET", "DELETE"],
    url: "/mcp",
    handler: async (_req, reply) =>
      reply.code(405).send({ error: "method_not_allowed", detail: "stateless streamable HTTP: POST only" }),
  });

  app.post("/mcp", async (req: FastifyRequest, reply: FastifyReply) => {
    const header = req.headers.authorization ?? "";
    const token = header.startsWith("Bearer ") ? header.slice(7) : "";
    // MCP-R1: identity from the IdP on every call; nothing cached.
    let identity: Identity | null;
    try {
      identity = await deps.oidc.resolveIdentity(token);
    } catch (e) {
      deps.log("identity resolution failed", e);
      return reply.code(503).send({ error: "idp_unavailable" });
    }
    if (!identity) return unauthorized(reply, "invalid or expired token");

    let ws: KbState;
    try {
      ws = await deps.kb.current();
    } catch (e) {
      deps.log("KB workspace unavailable", e);
      return reply.code(503).send({ error: "kb_unavailable" });
    }

    const profileName = typeof (req.query as { profile?: string }).profile === "string"
      ? (req.query as { profile: string }).profile
      : "";
    const body = req.body as { method?: string; params?: { name?: string; arguments?: Record<string, unknown> } } | null;
    const isToolCall = body?.method === "tools/call";
    const sessionId = typeof req.headers["mcp-session-id"] === "string" ? req.headers["mcp-session-id"] : null;

    const connectionDenied = async (reason: string) => {
      // MCP-R2: a profile the caller's roles don't permit fails the
      // connection (initialize and every subsequent request alike).
      if (isToolCall) {
        await writeAudit(deps.pool, {
          auditId: randomUUID(),
          subject: identity.subject,
          roles: identity.roles,
          profile: profileName || null,
          sessionId,
          tool: body?.params?.name ?? "(unknown)",
          args: body?.params?.arguments ?? {},
          kbRef: ws.headSha,
          snapshotRef: refsEnvelope(ws).snapshot_ref,
          decision: "denied",
          decisionReason: reason,
          durationMs: 0,
          resultMeta: {},
          statementText: null,
        }).catch((e) => deps.log("audit write failed", e));
      }
      return reply.code(403).send({ error: "forbidden", detail: reason });
    };

    if (!profileName) return connectionDenied("profile query parameter required (compiled client config supplies it)");
    const rawProfile = ws.profiles.get(profileName);
    if (!rawProfile) return connectionDenied(`no profile ${profileName} in the KB`);
    const profile = parseProfile(profileName, rawProfile);
    if (!profilePermitted(profile, identity.roles)) {
      return connectionDenied(`roles [${identity.roles.join(", ")}] do not permit profile ${profileName}`);
    }
    const scopes = visibilityScopes(ws.roles, identity.roles);

    const server = new Server(
      { name: "context-layer", version: "1.0.0" },
      { capabilities: { tools: {} } },
    );

    server.setRequestHandler(ListToolsRequestSchema, () => ({
      // M-3: tools outside the allow-set are hidden, not just denied.
      tools: TOOL_DEFS.filter((tool) => profile.allow.has(tool.name)),
    }));

    server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const tool = request.params.name;
      const args = (request.params.arguments as Record<string, unknown> | undefined) ?? {};
      const auditId = randomUUID();
      const started = Date.now();
      let outcome: ToolOutcome;
      let decision: "allowed" | "denied" | "filtered" = "allowed";
      let reason: string | null = null;

      const limit = deps.limiter.check(identity.subject, categoryForTool(tool));
      if (!limit.allowed) {
        decision = "denied";
        reason = "rate_limited";
        outcome = err("rate_limited", "per-identity rate limit exceeded (source protection, not licensing)", {
          retry_after_s: limit.retryAfterS,
        });
      } else if (!TOOL_IMPLS[tool]) {
        decision = "denied";
        reason = "unknown tool";
        outcome = err("not_found", `unknown tool ${tool}`);
      } else {
        const gate = toolAllowed(profile, tool, qualifierArg(tool, args));
        if (!gate.allowed) {
          // M-3: hidden tools are also denied on direct call.
          decision = "denied";
          reason = gate.reason ?? "outside profile allow-set";
          outcome = err("permission_denied", reason);
        } else if (STEWARD_GATED.has(tool) && !STEWARD_PROFILES.has(profile.name)) {
          decision = "denied";
          reason = `tool ${tool} is steward-gated (server-resolved profile ${profile.name})`;
          outcome = err("permission_denied", reason);
        } else {
          try {
            outcome = await TOOL_IMPLS[tool]!(
              { deps, ws, identity, profile, scopes, sessionId, auditId },
              args,
            );
            if (outcome.decision === "filtered") {
              decision = "filtered";
              reason = outcome.reason ?? null;
            }
          } catch (e) {
            deps.log(`tool ${tool} failed`, e);
            outcome = err("upstream_error", "internal error; the failure is logged and audited");
          }
        }
      }

      await writeAudit(deps.pool, {
        auditId,
        subject: identity.subject,
        roles: identity.roles,
        profile: profile.name,
        sessionId,
        tool,
        args,
        kbRef: ws.headSha,
        snapshotRef: refsEnvelope(ws).snapshot_ref,
        decision,
        decisionReason: reason,
        durationMs: Date.now() - started,
        resultMeta: outcome.resultMeta ?? {},
        statementText: tool === "validate_sql" ? outcome.statementText ?? null : null,
      }).catch((e) => deps.log("audit write failed", e));

      return {
        content: [{ type: "text" as const, text: JSON.stringify(outcome.payload) }],
        ...(outcome.isError ? { isError: true } : {}),
      };
    });

    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: true,
    });
    await server.connect(transport);
    reply.hijack();
    await transport.handleRequest(req.raw, reply.raw, req.body);
  });
}
