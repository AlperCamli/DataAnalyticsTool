/**
 * Rig for the B-0 dashboard suites: the MCP rig with the dashboard
 * surface enabled, plus a browser stand-in that walks the real OIDC
 * authorization-code flow against the compose dev IdP — login redirect,
 * IdP form post, callback, session cookie. Nothing here fakes a session:
 * the tests get a cookie the core minted from a code it exchanged, which
 * is the only way to exercise what D-102.1 actually specifies.
 */

import { setupMcpRig, USERS, type McpRig } from "./mcp-helpers.js";
import type { TestCore } from "./helpers.js";

export interface DashboardRig extends McpRig {
  /** Live PR store + refs, for the DT-11 "no git call" assertion. */
  gitFingerprint: () => string;
}

export async function setupDashboardRig(
  overrides: { dashboard?: Partial<TestCore["cfg"]["dashboard"]>; rolesYaml?: string | null } = {},
): Promise<DashboardRig> {
  const rig = await setupMcpRig({
    dashboard: { enabled: true, ...overrides.dashboard },
    ...(overrides.rolesYaml !== undefined ? { rolesYaml: overrides.rolesYaml } : {}),
  });
  // The redirect URI is derived from the public URL at request time, so
  // it can be pinned to the port the core actually bound.
  rig.core.cfg.mcp.publicUrl = rig.base;
  const { readFileSync, existsSync } = await import("node:fs");
  const { execFileSync } = await import("node:child_process");
  return {
    ...rig,
    gitFingerprint: () => {
      const refs = execFileSync("git", ["for-each-ref", "--format=%(refname) %(objectname)"], {
        cwd: rig.kb.remote,
        encoding: "utf-8",
      });
      const prs = existsSync(rig.kb.prsFile) ? readFileSync(rig.kb.prsFile, "utf-8") : "(no pr store)";
      return `${refs}\n---\n${prs}`;
    },
  };
}

export interface BrowserSession {
  cookie: string;
  csrf: string;
  subject: string;
  roles: string[];
  expiresAt: string;
}

function cookieFrom(headers: Headers): string {
  const all = headers.getSetCookie?.() ?? [];
  const raw = all.find((c) => c.startsWith("cl_session=")) ?? "";
  return raw.split(";")[0] ?? "";
}

/**
 * Walk the authorization-code flow end to end as a browser would:
 * /v1/auth/login → IdP authorize form → callback → cookie.
 */
export async function login(rig: McpRig, user: keyof typeof USERS): Promise<BrowserSession> {
  const start = await fetch(`${rig.base}/v1/auth/login`, { redirect: "manual" });
  if (start.status !== 302) throw new Error(`login did not redirect (${start.status})`);
  const authorizeUrl = new URL(start.headers.get("location")!);

  // The dev IdP's login page posts these hidden fields back with
  // credentials; reconstruct them from the redirect's query.
  const form = new URLSearchParams();
  for (const [key, value] of authorizeUrl.searchParams) form.set(key, value);
  form.set("username", USERS[user].username);
  form.set("password", USERS[user].password);
  const authorized = await fetch(`${authorizeUrl.origin}${authorizeUrl.pathname}`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: form.toString(),
    redirect: "manual",
  });
  if (authorized.status !== 302) throw new Error(`IdP did not issue a code (${authorized.status})`);

  const callback = await fetch(authorized.headers.get("location")!, { redirect: "manual" });
  if (callback.status !== 302) {
    throw new Error(`callback failed (${callback.status}): ${await callback.text()}`);
  }
  const cookie = cookieFrom(callback.headers);
  if (!cookie) throw new Error("callback set no session cookie");

  const session = await fetch(`${rig.base}/v1/auth/session`, { headers: { cookie } });
  const body = (await session.json()) as {
    subject: string;
    roles: string[];
    csrf_token: string;
    expires_at: string;
  };
  return {
    cookie,
    csrf: body.csrf_token,
    subject: body.subject,
    roles: body.roles,
    expiresAt: body.expires_at,
  };
}

export interface ApiResult {
  status: number;
  json: Record<string, unknown>;
  headers: Headers;
}

async function parse(response: Response): Promise<ApiResult> {
  const text = await response.text();
  let json: Record<string, unknown> = {};
  try {
    json = text ? (JSON.parse(text) as Record<string, unknown>) : {};
  } catch {
    json = { _raw: text };
  }
  return { status: response.status, json, headers: response.headers };
}

/** GET as a cookie session. */
export async function apiGet(
  rig: McpRig,
  session: BrowserSession | null,
  path: string,
): Promise<ApiResult> {
  return parse(
    await fetch(`${rig.base}${path}`, {
      headers: session ? { cookie: session.cookie } : {},
    }),
  );
}

/** GET as a bearer caller — the shape extract-audit.sh uses. */
export async function apiGetBearer(rig: McpRig, token: string | null, path: string): Promise<ApiResult> {
  return parse(
    await fetch(`${rig.base}${path}`, {
      headers: token ? { authorization: `Bearer ${token}` } : {},
    }),
  );
}

/**
 * POST as a cookie session. `csrf: null` deliberately omits the token —
 * that is the CSRF negative, not an oversight.
 */
export async function apiPost(
  rig: McpRig,
  session: BrowserSession,
  path: string,
  body: unknown,
  opts: { csrf?: string | null } = {},
): Promise<ApiResult> {
  const csrf = opts.csrf === undefined ? session.csrf : opts.csrf;
  return parse(
    await fetch(`${rig.base}${path}`, {
      method: "POST",
      headers: {
        cookie: session.cookie,
        "content-type": "application/json",
        ...(csrf === null ? {} : { "x-cl-csrf": csrf }),
      },
      body: JSON.stringify(body),
    }),
  );
}
