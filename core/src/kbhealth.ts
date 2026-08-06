/**
 * KB Health (dashboard spec §3, checkpoint B-1) — R2's home screen.
 *
 * One governed read assembles the whole module: per-source freshness
 * against `sync-policy.yaml`, the sync-configuration state DT-9 asks
 * about, doc-status counts at KB HEAD, the contaminated set with the
 * lineage paths that carried the contamination, and the drift-PR queue.
 * Plus a second read for the lineage explorer (U-15).
 *
 * Three properties are worth stating before the code, because each is a
 * rule rather than a convenience.
 *
 * **One computation, two surfaces (D-114.2).** The freshness rows and
 * the doc-status counts are computed *here* and imported by the MCP
 * `report_freshness` tool, rather than each surface deriving its own.
 * A dashboard that could disagree with `report_freshness` about whether
 * a source is stale is a dashboard nobody can cite as evidence — the
 * fan-out rule, applied to a computation instead of a value.
 *
 * **The sync state is the core's own resolved config (D-114.3).** DT-9
 * words the warning as coming "from /healthz's sync_enabled". Taken
 * literally that would have the browser fetch an unauthenticated ops
 * probe and re-derive a warning from it — a second source for one fact.
 * The block below reads `cfg.sync.enabled`, which is the same value
 * `effectiveFlags()` hands `/healthz`: one value, two renderings, and a
 * test that asserts the two agree.
 *
 * **Nothing here can merge (D-114.4).** The drift-PR queue is a list of
 * links out to the git provider. There is no merge affordance because
 * there is no code path that could reach one: every route in this file
 * is a GET, and §7.3 is the line the test is written against.
 *
 * Visibility is the MCP path's, unchanged: a doc whose path the caller's
 * scopes do not cover is *absent* from the counts rather than zeroed, so
 * two roles legitimately read two different totals and each is true for
 * its reader (M-4).
 */

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import pg from "pg";
import { neutralize } from "./changelog.js";
import type { CoreConfig } from "./config.js";
import { createProvider, type PrInfo } from "./gitkb.js";
import type { KbDoc, KbState } from "./kbread.js";
import { policyFromDoc, PolicyError, type SyncPolicy } from "./policy.js";
import { authenticate, type SessionDeps } from "./session.js";
import { pathVisible, visibilityScopes } from "./visibility.js";

export const API_VERSION = "1";

export interface KbHealthDeps extends SessionDeps {
  cfg: CoreConfig;
  pool: pg.Pool;
  kb: { current(): Promise<KbState> };
  log: (msg: string, err?: unknown) => void;
}

/** The doc classes whose `status` front-matter is a human trust claim.
 * Machine docs carry facts and no status of their own (KB §5). */
const HUMAN_CLASSES = new Set(["human-object", "human-group", "entity", "metric", "lineage-note"]);

// ---------------------------------------------------------------------------
// Doc status (shared with the MCP report_freshness tool)

/**
 * Status counts over the human-owned docs this caller can see.
 *
 * The default is `draft`, not "unknown": KB §5 says an unstated status is
 * a draft, and counting it as its own bucket would invent a fourth state
 * the KB does not have.
 */
export function docStatusCounts(ws: KbState, scopes: string[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const doc of ws.docs.values()) {
    if (!doc.docClass || !HUMAN_CLASSES.has(doc.docClass)) continue;
    if (!pathVisible(scopes, doc.path)) continue;
    const status = typeof doc.fm?.status === "string" ? doc.fm.status : "draft";
    counts[status] = (counts[status] ?? 0) + 1;
  }
  return counts;
}

// ---------------------------------------------------------------------------
// Contamination + the lineage path that carried it

export interface ContaminationRow {
  doc: string;
  title: string;
  object: string | null;
  /** The changed object that contaminated this doc. */
  source_object: string | null;
  change: string | null;
  detail: string | null;
  /**
   * How the contamination reached this doc: the FQN hops from the
   * changed object to this doc's own object. `["a","b"]` is a direct
   * dependency; a longer list is a derived view chain. Empty when the
   * doc *is* the changed object, and null when nothing in the KB can
   * say — which is a real state and reads as one.
   */
  path: string[] | null;
  path_source: "recorded" | "declared" | "derived" | "self" | "unknown";
}

/** Adjacency from `lineage/graph.json`, source → targets. */
function lineageEdges(ws: KbState): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const edge of ws.graph?.edges ?? []) {
    const source = typeof edge.source === "string" ? edge.source : null;
    const target = typeof edge.target === "string" ? edge.target : null;
    if (!source || !target) continue;
    out.set(source, [...(out.get(source) ?? []), target]);
  }
  return out;
}

/** Shortest hop chain from `from` to `to`, or null when the graph has
 * none. Breadth-first and bounded: a lineage graph is small, and an
 * unbounded walk on a cyclic one would hang a page load. */
function shortestPath(edges: Map<string, string[]>, from: string, to: string): string[] | null {
  if (from === to) return [from];
  const seen = new Set([from]);
  let frontier: string[][] = [[from]];
  for (let depth = 0; depth < 8 && frontier.length > 0; depth += 1) {
    const next: string[][] = [];
    for (const trail of frontier) {
      for (const hop of edges.get(trail[trail.length - 1]!) ?? []) {
        if (seen.has(hop)) continue;
        const extended = [...trail, hop];
        if (hop === to) return extended;
        seen.add(hop);
        next.push(extended);
      }
    }
    frontier = next;
  }
  return null;
}

/**
 * Every contaminated doc the caller can see, with how the contamination
 * reached it.
 *
 * The front-matter is the authority for *that* a doc is contaminated
 * (the sync run wrote it there and the KB carries it at HEAD). The path
 * is best-effort in four graded ways, and the grade is reported rather
 * than smoothed over: `recorded` when the scan wrote a path into the
 * front-matter, `declared` when the doc's own `depends_on` names the
 * changed object (a direct edge, which is the common case), `derived`
 * when the lineage graph supplies a longer chain, and `unknown` when
 * neither does. An unknown path is a triage fact — it means the doc
 * relies on something it never declared — so it must not render as an
 * empty list, which would read as "no hops".
 */
export function contaminationList(ws: KbState, scopes: string[]): ContaminationRow[] {
  const edges = lineageEdges(ws);
  const rows: ContaminationRow[] = [];
  for (const doc of ws.docs.values()) {
    if (!doc.docClass || !HUMAN_CLASSES.has(doc.docClass)) continue;
    if (doc.fm?.status !== "contaminated") continue;
    if (!pathVisible(scopes, doc.path)) continue;

    const contamination = (doc.fm.contamination ?? null) as Record<string, unknown> | null;
    const sourceObject =
      contamination && typeof contamination.object === "string" ? contamination.object : null;
    const own = typeof doc.fm.object === "string" ? doc.fm.object : null;
    const dependsOn = Array.isArray(doc.fm.depends_on)
      ? (doc.fm.depends_on as unknown[]).filter((d): d is string => typeof d === "string")
      : [];

    let path: string[] | null = null;
    let pathSource: ContaminationRow["path_source"] = "unknown";
    const recorded = contamination?.path;
    if (Array.isArray(recorded) && recorded.every((p) => typeof p === "string")) {
      path = recorded as string[];
      pathSource = "recorded";
    } else if (sourceObject !== null && own !== null && sourceObject === own) {
      path = [own];
      pathSource = "self";
    } else if (sourceObject !== null && dependsOn.includes(sourceObject)) {
      path = own ? [sourceObject, own] : [sourceObject];
      pathSource = "declared";
    } else if (sourceObject !== null && own !== null) {
      const walked = shortestPath(edges, sourceObject, own);
      if (walked) {
        path = walked;
        pathSource = "derived";
      }
    }

    rows.push({
      // Doc paths and object names are attacker-influenceable (the F4
      // lesson), so they leave here inert exactly as ledger text does.
      doc: neutralize(doc.path),
      title: neutralize(doc.title),
      object: own === null ? null : neutralize(own),
      source_object: sourceObject === null ? null : neutralize(sourceObject),
      change:
        contamination && typeof contamination.change === "string"
          ? neutralize(contamination.change)
          : null,
      detail:
        contamination && typeof contamination.detail === "string"
          ? neutralize(contamination.detail)
          : null,
      path: path === null ? null : path.map((hop) => neutralize(hop)),
      path_source: pathSource,
    });
  }
  // Worst first is not available (contamination has no severity), so the
  // order is the one a person can predict: by system, then by doc.
  return rows.sort((a, b) => (a.doc < b.doc ? -1 : a.doc > b.doc ? 1 : 0));
}

// ---------------------------------------------------------------------------
// Freshness (shared with the MCP report_freshness tool)

export interface SourceRow {
  system: string;
  /** In the sync policy at HEAD? A connection absent from it is not a
   * sync source and freshness is not its verdict (the B-2 correction). */
  in_policy: boolean;
  last_snapshot_at: string | null;
  accepted_at: string | null;
  age_s: number | null;
  threshold_s: number | null;
  trigger_mode: "schedule" | "webhook" | "manual" | null;
  schedule_interval_s: number | null;
  /** `stale` is the computed verdict; `warning` is the state the
   * scheduler persisted. They can differ for exactly as long as a
   * disabled scheduler leaves an old row behind — which is itself worth
   * seeing, so both are reported. */
  stale: boolean;
  warning_raised_at: string | null;
  render_lag: boolean;
}

export async function freshnessRows(
  pool: pg.Pool,
  ws: KbState,
  policy: SyncPolicy | null,
  now: Date = new Date(),
): Promise<SourceRow[]> {
  const { rows: warnings } = await pool.query<{ system: string; raised_at: Date }>(
    `SELECT system, raised_at FROM freshness_warnings`,
  );
  const raisedAt = new Map(warnings.map((w) => [w.system, w.raised_at.toISOString()]));

  // The union of both directions, because each single-source list hides
  // a real failure: a policy system with no snapshot has never synced,
  // and a snapshot for a system no policy names is a source nobody is
  // watching. Neither is visible from the other list alone.
  const systems = new Set<string>([...ws.systems.keys(), ...(policy?.systems.keys() ?? [])]);
  const rows: SourceRow[] = [];
  for (const system of [...systems].sort()) {
    const state = ws.systems.get(system) ?? null;
    const sp = policy?.systems.get(system) ?? null;
    const capturedAt = state ? Date.parse(state.capturedAt) : null;
    const ageS =
      capturedAt !== null && Number.isFinite(capturedAt)
        ? Math.max(0, Math.round((now.getTime() - capturedAt) / 1000))
        : null;
    rows.push({
      system: neutralize(system),
      in_policy: sp !== null,
      last_snapshot_at: state?.capturedAt ?? null,
      accepted_at: state?.acceptedAt ?? null,
      age_s: ageS,
      threshold_s: sp?.freshnessThresholdS ?? null,
      trigger_mode: sp === null ? null : sp.scheduleIntervalS !== null ? "schedule" : sp.webhook ? "webhook" : "manual",
      schedule_interval_s: sp?.scheduleIntervalS ?? null,
      // Only a policy system can be stale: staleness is measured against
      // a threshold, and a source with no threshold has none to cross.
      stale: sp !== null && (ageS === null || ageS > sp.freshnessThresholdS),
      warning_raised_at: raisedAt.get(system) ?? null,
      render_lag: state?.renderLag ?? false,
    });
  }
  return rows;
}

// ---------------------------------------------------------------------------

export function registerKbHealth(app: FastifyInstance, deps: KbHealthDeps): void {
  async function viewerFor(
    req: FastifyRequest,
    reply: FastifyReply,
  ): Promise<{ ws: KbState; scopes: string[] } | null> {
    const auth = await authenticate(deps, req);
    if (!auth.ok) {
      await reply.code(auth.status).send({ error: auth.code, detail: auth.detail });
      return null;
    }
    let ws: KbState;
    try {
      ws = await deps.kb.current();
    } catch (err) {
      deps.log("KB workspace unavailable", err);
      await reply.code(503).send({
        error: "kb_unavailable",
        detail: "the knowledge base could not be read; nothing on this screen would be true",
      });
      return null;
    }
    return { ws, scopes: visibilityScopes(ws.roles, auth.identity.roles) };
  }

  /** The policy at HEAD, from the workspace the rest of this read uses. */
  function policyOf(ws: KbState): { policy: SyncPolicy | null; error: string | null } {
    if (ws.syncPolicy === null) {
      return { policy: null, error: "sync-policy.yaml is absent from the knowledge base at HEAD" };
    }
    try {
      return { policy: policyFromDoc(ws.syncPolicy), error: null };
    } catch (err) {
      // A policy that does not parse must not read as "no thresholds":
      // the difference between "nothing is configured" and "the
      // configuration is broken" is the whole diagnosis.
      return {
        policy: null,
        error: err instanceof PolicyError ? err.message : "sync-policy.yaml could not be parsed",
      };
    }
  }

  // -- the module's one read -------------------------------------------------

  app.get("/v1/dashboard/kb-health", async (req, reply) => {
    const viewer = await viewerFor(req, reply);
    if (!viewer) return reply;
    const { ws, scopes } = viewer;
    const { policy, error: policyError } = policyOf(ws);
    const sources = await freshnessRows(deps.pool, ws, policy);
    const counts = docStatusCounts(ws, scopes);

    // DT-9 / SO-F: the two-silent-days shape, made visible. The estate is
    // configured to sync — the policy lists systems with thresholds and
    // triggers — and this core's sync engine is off, so no trigger will
    // ever fire and every source will age past its threshold in silence.
    // Reported as a state with its own count, because "sync is disabled"
    // alone reads like a deliberate setting rather than a fault.
    const configuredSystems = policy?.systems.size ?? 0;
    const sync = {
      // The same value effectiveFlags() reports to /healthz (D-114.3).
      enabled: deps.cfg.sync.enabled,
      configured_systems: configuredSystems,
      policy_readable: policy !== null,
      ...(policyError ? { policy_error: neutralize(policyError) } : {}),
      configured_but_disabled: !deps.cfg.sync.enabled && configuredSystems > 0,
    };

    // The drift-PR queue (§7.3): links out, and nothing else. Asking the
    // provider is skipped when sync is off — there is no drift loop to
    // have opened anything, and a provider error would then read as a
    // fault rather than as the disabled state above.
    let driftPrs: { available: boolean; reason: string | null; prs: unknown[] } = {
      available: false,
      reason: "sync is disabled on this core, so no drift PR can have been opened by it",
      prs: [],
    };
    if (deps.cfg.sync.enabled) {
      try {
        const open: PrInfo[] = await createProvider(deps.cfg.sync).listOpenSyncPrs();
        driftPrs = {
          available: true,
          reason: null,
          prs: open.map((pr) => ({
            number: pr.number,
            // Echoed from the git provider, therefore user-influenceable
            // (§6 names PR titles explicitly).
            title: neutralize(pr.title ?? ""),
            url: pr.url,
            branch: neutralize(pr.branch ?? ""),
          })),
        };
      } catch (err) {
        deps.log("git provider unreachable while listing drift PRs", err);
        driftPrs = {
          available: false,
          reason: "the git provider did not answer; this list is unknown, not empty",
          prs: [],
        };
      }
    }

    return reply.send({
      api_version: API_VERSION,
      kb: {
        ref: ws.headSha,
        remote: deps.cfg.sync.gitRemote || null,
        // A failed re-render means the machine docs served are HEAD's,
        // not the latest snapshot's. Stated, never inferred.
        render_failed: ws.renderFailed,
      },
      sync,
      sources,
      docs: {
        counts,
        total: Object.values(counts).reduce((a, b) => a + b, 0),
        // So a reader knows the total is *theirs*, not the estate's.
        scope_note:
          "counts cover the human-owned docs your roles can see; another role's totals may differ",
      },
      contamination: contaminationList(ws, scopes),
      drift_prs: driftPrs,
    });
  });

  // -- lineage explorer, read view (U-15) ------------------------------------

  /**
   * The graph as the KB carries it, node-by-node visibility-filtered
   * (MCP-R11): a hidden node is omitted, and so is every edge that
   * touches it. Filtering edges only would leak the hidden node's name
   * through the endpoints of the edges that survived.
   */
  app.get("/v1/dashboard/lineage", async (req, reply) => {
    const viewer = await viewerFor(req, reply);
    if (!viewer) return reply;
    const { ws, scopes } = viewer;
    if (!ws.graph) {
      return reply.send({
        api_version: API_VERSION,
        available: false,
        reason: "this knowledge base carries no lineage/graph.json at HEAD",
        nodes: [],
        edges: [],
      });
    }

    const visibleNode = (id: string): boolean => {
      const docPath = ws.machineByFqn.get(id)?.path;
      // A node with no machine doc is a report or an external system,
      // which no visibility glob covers; those are visible to anyone who
      // can read the graph at all, exactly as the MCP walk treats them.
      if (!docPath) return true;
      return pathVisible(scopes, docPath);
    };

    const nodes = ws.graph.nodes.filter((n) => typeof n.id === "string" && visibleNode(n.id));
    const keep = new Set(nodes.map((n) => n.id));
    const edges = ws.graph.edges.filter(
      (e) =>
        typeof e.source === "string" &&
        typeof e.target === "string" &&
        keep.has(e.source) &&
        keep.has(e.target),
    );

    const humanDoc = (fqn: string): string | null => ws.humanByFqn.get(fqn) ?? null;

    return reply.send({
      api_version: API_VERSION,
      available: true,
      reason: null,
      kb_ref: ws.headSha,
      nodes: nodes.map((n) => ({
        id: neutralize(n.id),
        node_kind: n.node_kind ? neutralize(n.node_kind) : null,
        resolved: n.resolved !== false,
        machine_doc: ws.machineByFqn.get(n.id)?.path ?? null,
        human_doc: humanDoc(n.id),
        // The trust signal a reader needs to know whether to believe the
        // doc behind the node, carried on the node itself.
        status: statusOf(ws, humanDoc(n.id)),
      })),
      edges: edges.map((e) => ({
        source: neutralize(e.source as string),
        target: neutralize(e.target as string),
        operation: typeof e.operation === "string" ? neutralize(e.operation) : null,
        trust: typeof e.trust === "string" ? neutralize(e.trust) : null,
      })),
    });
  });
}

function statusOf(ws: KbState, docPath: string | null): string | null {
  if (!docPath) return null;
  const doc: KbDoc | undefined = ws.docs.get(docPath);
  if (!doc) return null;
  return typeof doc.fm?.status === "string" ? doc.fm.status : "draft";
}
