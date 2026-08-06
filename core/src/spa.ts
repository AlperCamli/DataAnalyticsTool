/**
 * The dashboard's own surface: a module map the server resolves, and the
 * static asset bundle that renders it (checkpoint B-2, ruling D-103.1).
 *
 * Two things live here and the split between them is the whole design.
 *
 * **The module map is a server answer.** `GET /v1/dashboard/modules`
 * reads `.contextlayer/dashboard.yaml` (UI-9) and returns the modules
 * *this caller* sees, resolved from their OIDC roles server-side. The
 * client renders the list it is given. It has no role names in it, no
 * allow/deny branch, and no way to reach a module the server did not
 * return — and if it forged a route anyway, the module's own API would
 * 403, because that is where enforcement actually is (UI-1).
 *
 * **The assets are files.** No frontend server, no backend-for-frontend,
 * no token minting for the browser: the SPA is `app.js` and `app.css`
 * handed out by the core, running inside the D-102 session cookie. That
 * is UI-2 made structural — there is no second identity domain because
 * there is no second process to hold one.
 *
 * The bundle is built by `web/build.mjs` (esbuild) into `web/dist/`. If
 * it is missing, this module says so in plain words rather than serving
 * a blank page: a dashboard that renders nothing and explains nothing is
 * the failure UI-10 exists to prevent, and it applies to the shell too.
 */

import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { FastifyInstance, FastifyReply } from "fastify";
import type { CoreConfig } from "./config.js";
import type { KbReader, KbState } from "./kbread.js";
import { authenticate, type SessionDeps } from "./session.js";

export const API_VERSION = "1";

export interface SpaDeps extends SessionDeps {
  cfg: CoreConfig;
  kb: KbReader;
  log: (msg: string, err?: unknown) => void;
}

/** Where the SPA lives. A prefix rather than `/`, so an asset route can
 * never shadow an API one and the two are legible in an access log. */
export const APP_BASE = "/app";

export interface ModuleDef {
  id: string;
  title: string;
  /** The client route. Its data still comes from a governed API. */
  path: string;
  /** Shipped but unbuilt: rendered as a stated dark state (UI-10), not
   * hidden — a menu that quietly omits things teaches nobody. */
  built: boolean;
  description: string;
}

/**
 * The registry (platform-architecture §6, dashboard spec §3), in build
 * order. Everything past Connections is declared and unbuilt at B-2;
 * saying so is cheaper than an empty sidebar that implies the product
 * ends here.
 */
export const MODULES: ModuleDef[] = [
  {
    id: "connections",
    title: "Connections",
    path: "/connections",
    built: true,
    description: "Register, test and health-check the sources this estate reads from.",
  },
  {
    id: "kb_health",
    title: "KB Health",
    path: "/kb-health",
    built: false,
    description: "Freshness and trust map, doc-status counts, the drift-PR queue. Arrives at checkpoint B-1.",
  },
  {
    id: "gap_triage",
    title: "Gap Triage",
    path: "/gap-triage",
    built: false,
    description: "The fault-ledger queue and the knowledge-request verdicts. Arrives at checkpoint B-1.",
  },
  {
    id: "setup",
    title: "Setup",
    path: "/setup",
    built: false,
    description: "Bundle download and staleness. The server half ships (A-2); the view arrives at B-3.",
  },
  {
    id: "profiles",
    title: "Profiles",
    path: "/profiles",
    built: false,
    description: "Profile editing, as a pull request under your identity. Arrives at checkpoint B-3.",
  },
  {
    id: "ops",
    title: "Ops",
    path: "/ops",
    built: false,
    description: "Runs, jobs, webhook secrets, detector rules. Arrives at checkpoint B-1.",
  },
  {
    id: "publish",
    title: "Publish",
    path: "/publish",
    built: false,
    description: "Deliveries and attestation history. The API ships (B-0); the view arrives at B-1.",
  },
  {
    id: "audit",
    title: "Audit",
    path: "/audit",
    built: false,
    description: "Who asked what, and what the server decided. The API ships (B-0); the view arrives at B-4.",
  },
  {
    id: "benchmarks",
    title: "Benchmarks",
    path: "/benchmarks",
    built: false,
    description: "Golden-suite scores per KB version. Ships dark until a baseline exists.",
  },
];

/** Modules a deployment turns on when its KB configures nothing. */
const DEFAULT_ENABLED = new Set(MODULES.map((m) => m.id));

interface DashboardYaml {
  branding?: { name?: unknown };
  modules?: Record<string, { enabled?: unknown } | null>;
  role_views?: Record<string, unknown>;
}

/**
 * Resolve the caller's module list from `dashboard.yaml` and their
 * roles — server-side, and the only place this resolution happens.
 *
 * `role_views` maps a role to the modules it sees. A KB that declares
 * none gives every enabled module to every authenticated caller, which
 * is the honest default: the modules themselves are role-gated by their
 * own APIs, so a visible module the caller cannot use renders the
 * server's 403 rather than data (DT-2). What `role_views` buys is
 * tidiness, not security, and this comment exists so nobody later
 * mistakes it for the latter.
 */
export function modulesFor(ws: KbState | null, roles: string[]): {
  modules: ModuleDef[];
  source: "kb" | "default";
  branding: string | null;
} {
  const raw = (ws?.dashboard ?? null) as DashboardYaml | null;
  if (!raw || typeof raw !== "object") {
    return { modules: MODULES.filter((m) => DEFAULT_ENABLED.has(m.id)), source: "default", branding: null };
  }
  const configured = raw.modules ?? {};
  const enabled = new Set(
    MODULES.filter((m) => {
      const entry = configured[m.id];
      if (entry === undefined) return DEFAULT_ENABLED.has(m.id);
      return entry !== null && (entry as { enabled?: unknown }).enabled !== false;
    }).map((m) => m.id),
  );

  const views = raw.role_views;
  let visible: Set<string> | null = null;
  if (views && typeof views === "object") {
    visible = new Set<string>();
    for (const [role, ids] of Object.entries(views)) {
      if (!roles.includes(role)) continue;
      if (Array.isArray(ids)) for (const id of ids) if (typeof id === "string") visible.add(id);
    }
    // A KB that declares role_views but says nothing about this
    // caller's roles shows them nothing. The narrow reading again: a
    // silently-full menu would make the config look enforced when it is
    // not being applied at all.
  }

  return {
    modules: MODULES.filter((m) => enabled.has(m.id) && (visible === null || visible.has(m.id))),
    source: "kb",
    branding: typeof raw.branding?.name === "string" ? raw.branding.name : null,
  };
}

// ---------------------------------------------------------------------------
// Static assets

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** `web/dist` beside the source tree in dev, beside `dist/` in the image. */
export function assetDir(): string {
  const candidates = [
    path.resolve(HERE, "..", "web", "dist"),
    path.resolve(HERE, "..", "..", "web", "dist"),
  ];
  return candidates.find((c) => existsSync(path.join(c, "app.js"))) ?? candidates[0]!;
}

const CONTENT_TYPES: Record<string, string> = {
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".svg": "image/svg+xml",
  ".map": "application/json; charset=utf-8",
};

const UNBUILT_PAGE = `<!doctype html><meta charset="utf-8">
<title>Context Layer — dashboard not built</title>
<style>body{font:16px/1.6 ui-sans-serif,system-ui,sans-serif;max-width:44rem;margin:4rem auto;padding:0 1.5rem}
code{background:#8881;padding:.15em .4em;border-radius:.25em}</style>
<h1>The dashboard bundle is not in this build</h1>
<p>The core is running and its APIs are up — this is the browser bundle only.
Build it with <code>npm run build:web</code> in <code>core/</code>, or use an
image built by the project <code>Dockerfile</code>, which runs that step.</p>
<p>Nothing is wrong with your session or your permissions.</p>`;

export function registerSpa(app: FastifyInstance, deps: SpaDeps): void {
  // -- the module map (a server answer, per UI-1) -----------------------------

  app.get("/v1/dashboard/modules", async (req, reply) => {
    const auth = await authenticate(deps, req);
    if (!auth.ok) {
      return reply.code(auth.status).send({ error: auth.code, detail: auth.detail });
    }
    let ws: KbState | null = null;
    try {
      ws = await deps.kb.current();
    } catch (err) {
      deps.log("KB workspace unavailable while resolving dashboard modules", err);
    }
    const resolved = modulesFor(ws, auth.identity.roles);
    return reply.send({
      api_version: API_VERSION,
      subject: auth.identity.subject,
      ...(auth.identity.display ? { display: auth.identity.display } : {}),
      // Which config produced this list. An operator who edits
      // dashboard.yaml and sees no change should be able to tell that
      // the file was never read, without reading logs.
      config_source: ws === null ? "unreadable_kb" : resolved.source,
      branding: resolved.branding,
      modules: resolved.modules,
    });
  });

  // -- the assets ------------------------------------------------------------

  const serve = (reply: FastifyReply, file: string): FastifyReply => {
    const dir = assetDir();
    const full = path.join(dir, file);
    // Path traversal is closed by construction: `file` is one of a
    // fixed set below, never a request parameter.
    if (!existsSync(full) || !statSync(full).isFile()) {
      return reply.code(503).type("text/html; charset=utf-8").send(UNBUILT_PAGE);
    }
    return reply
      .type(CONTENT_TYPES[path.extname(file)] ?? "application/octet-stream")
      .header("cache-control", "no-cache")
      .send(readFileSync(full));
  };

  app.get(`${APP_BASE}/app.js`, async (_req, reply) => serve(reply, "app.js"));
  app.get(`${APP_BASE}/app.css`, async (_req, reply) => serve(reply, "app.css"));

  // Every in-app route serves the same shell; the client resolves the
  // rest. Unauthenticated is fine here — the shell holds no data, and
  // its first call is `/v1/auth/session`, which is where the login flow
  // starts. Nothing is protected by not shipping a file.
  const shell = async (_req: unknown, reply: FastifyReply) => serve(reply, "index.html");
  app.get(APP_BASE, shell);
  app.get(`${APP_BASE}/`, shell);
  for (const module of MODULES) app.get(`${APP_BASE}${module.path}`, shell);

  // A person handed the bare address should land somewhere, not on a
  // 401 from the ops surface.
  app.get("/", async (_req, reply) => reply.code(302).header("location", `${APP_BASE}/`).send());

  // Browsers ask for this on every page load whether or not a page names
  // one. We ship no icon, so the honest answer is "nothing here" — 204,
  // not the 401 the ops surface would otherwise give, and not a 404 that
  // re-fires on every navigation. Keeps a healthy dashboard's console clean.
  app.get("/favicon.ico", async (_req, reply) => reply.code(204).send());
}
