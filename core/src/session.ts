/**
 * Browser session auth for the dashboard (D-102.1, dashboard spec UI-2).
 *
 * The OIDC authorization-code flow (PKCE) runs **at the core**, against
 * the same IdP the MCP path uses. What the browser gets is an opaque,
 * HttpOnly, SameSite session cookie; the access token stays server-side
 * in `dashboard_sessions`, so the page never holds a bearer credential
 * and there is no dashboard service account to hold a wider one.
 *
 * The load-bearing property is what this module does *not* contain: no
 * role parsing, no claim walking, no profile mapping. Every request's
 * `{subject, roles}` comes from `OidcClient.resolveIdentity` — the one
 * verifier the MCP path already calls — so the dashboard cannot drift
 * from MCP enforcement, and an IdP-side role revocation lands on the
 * next dashboard call exactly as it lands on the next tool call (MT-9).
 * `dashboard-auth.test.ts` asserts that by construction.
 *
 * Two credential shapes reach the same resolver: the session cookie
 * (browsers) and a bearer access token (scripts — how extract-audit.sh
 * became an API client). A cookie is ambient and therefore CSRF-exposed,
 * so every cookie-authenticated write must also carry the session's CSRF
 * token; a bearer token is not sent automatically by a browser and needs
 * no such proof. When both are present the cookie rules, so presenting a
 * bearer header can never shed the CSRF requirement.
 */

import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import pg from "pg";
import type { CoreConfig } from "./config.js";
import { generatePkce, type Identity, type OidcClient } from "./oidc.js";

export const SESSION_COOKIE = "cl_session";
export const CSRF_HEADER = "x-cl-csrf";

/** Authorization-code round trips are short; a stale one is a dead one. */
const AUTH_STATE_TTL_S = 600;

export interface SessionDeps {
  cfg: CoreConfig;
  pool: pg.Pool;
  oidc: OidcClient;
  log: (msg: string, err?: unknown) => void;
}

export interface SessionRow {
  sessionHash: string;
  subject: string;
  csrfToken: string;
  expiresAt: Date;
}

export type AuthOutcome =
  | { ok: true; identity: Identity; via: "cookie" | "bearer"; session: SessionRow | null }
  | { ok: false; status: number; code: string; detail: string };

function hash(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function constantTimeEqual(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  if (left.length !== right.length) return false;
  return timingSafeEqual(left, right);
}

/** Minimal Cookie-header parse; no dependency, no cookie ever written
 * by us that needs quoting (all values are base64url). */
export function parseCookies(header: string | undefined): Map<string, string> {
  const out = new Map<string, string>();
  if (!header) return out;
  for (const part of header.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    const name = part.slice(0, eq).trim();
    if (name) out.set(name, part.slice(eq + 1).trim());
  }
  return out;
}

/**
 * Post-login targets are same-origin paths only. An open redirect here
 * would hand the login flow to whoever crafted the link, so anything
 * that is not a plain absolute path falls back to the configured
 * landing path rather than being sanitized into one.
 */
export function safeRedirectPath(candidate: unknown, fallback: string): string {
  if (typeof candidate !== "string" || !candidate.startsWith("/")) return fallback;
  if (candidate.startsWith("//") || candidate.startsWith("/\\")) return fallback;
  // Control characters and whitespace would let a crafted value split the
  // Location header or smuggle a second target past the checks above.
  if (/[\u0000-\u0020\u007f]/.test(candidate)) return fallback;
  return candidate;
}

/** The core's own callback URL, read at request time so a deployment
 * (or a test that learns its port after binding) reflects immediately. */
function redirectUri(cfg: CoreConfig): string {
  return `${cfg.mcp.publicUrl.replace(/\/$/, "")}/v1/auth/callback`;
}

function setSessionCookie(deps: SessionDeps, reply: FastifyReply, value: string, maxAgeS: number): void {
  const attrs = [
    `${SESSION_COOKIE}=${value}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    `Max-Age=${maxAgeS}`,
  ];
  if (deps.cfg.dashboard.cookieSecure) attrs.push("Secure");
  void reply.header("set-cookie", attrs.join("; "));
}

function clearSessionCookie(deps: SessionDeps, reply: FastifyReply): void {
  const attrs = [`${SESSION_COOKIE}=`, "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"];
  if (deps.cfg.dashboard.cookieSecure) attrs.push("Secure");
  void reply.header("set-cookie", attrs.join("; "));
}

async function loadSession(pool: pg.Pool, sessionId: string): Promise<
  (SessionRow & { accessToken: string }) | null
> {
  const { rows } = await pool.query<{
    session_hash: string;
    subject: string;
    access_token: string;
    csrf_token: string;
    expires_at: Date;
  }>(
    `SELECT session_hash, subject, access_token, csrf_token, expires_at
       FROM dashboard_sessions
      WHERE session_hash = $1 AND expires_at > now()`,
    [hash(sessionId)],
  );
  const row = rows[0];
  if (!row) return null;
  return {
    sessionHash: row.session_hash,
    subject: row.subject,
    accessToken: row.access_token,
    csrfToken: row.csrf_token,
    expiresAt: row.expires_at,
  };
}

/**
 * Resolve the caller for any dashboard request.
 *
 * `write` requests authenticated by cookie must present the session's
 * CSRF token; read requests and bearer-authenticated calls need not.
 * Identity itself is always the verifier's answer, never the session
 * row's — the row holds a token, and a token that the IdP no longer
 * honours resolves to nobody.
 */
export async function authenticate(
  deps: SessionDeps,
  req: FastifyRequest,
  opts: { write: boolean } = { write: false },
): Promise<AuthOutcome> {
  const cookies = parseCookies(req.headers.cookie);
  const sessionId = cookies.get(SESSION_COOKIE);
  const header = req.headers.authorization ?? "";
  const bearer = header.startsWith("Bearer ") ? header.slice(7) : "";

  let token = "";
  let session: (SessionRow & { accessToken: string }) | null = null;
  let via: "cookie" | "bearer";

  if (sessionId) {
    session = await loadSession(deps.pool, sessionId);
    if (!session) {
      return {
        ok: false,
        status: 401,
        code: "session_expired",
        detail: "no live session for this cookie; re-authenticate at /v1/auth/login",
      };
    }
    token = session.accessToken;
    via = "cookie";
  } else if (bearer) {
    token = bearer;
    via = "bearer";
  } else {
    return { ok: false, status: 401, code: "unauthorized", detail: "no session cookie and no bearer token" };
  }

  if (opts.write && via === "cookie") {
    const provided = req.headers[CSRF_HEADER];
    const supplied = typeof provided === "string" ? provided : "";
    if (!supplied || !constantTimeEqual(supplied, session!.csrfToken)) {
      return {
        ok: false,
        status: 403,
        code: "csrf_required",
        detail: `write requests on a cookie session must carry the session CSRF token in ${CSRF_HEADER}`,
      };
    }
  }

  let identity: Identity | null;
  try {
    identity = await deps.oidc.resolveIdentity(token);
  } catch (err) {
    deps.log("dashboard identity resolution failed", err);
    return { ok: false, status: 503, code: "idp_unavailable", detail: "identity provider unreachable" };
  }
  if (!identity) {
    // The IdP stopped honouring the token: expiry, revocation, logout
    // elsewhere. The session row is now worthless — drop it so the next
    // request takes the clean unauthenticated path.
    if (session) {
      await deps.pool
        .query(`DELETE FROM dashboard_sessions WHERE session_hash = $1`, [session.sessionHash])
        .catch((err: unknown) => deps.log("session cleanup failed", err));
    }
    return {
      ok: false,
      status: 401,
      code: via === "cookie" ? "session_expired" : "unauthorized",
      detail: "the identity provider no longer honours this token; re-authenticate",
    };
  }

  if (session) {
    await deps.pool
      .query(`UPDATE dashboard_sessions SET last_seen_at = now() WHERE session_hash = $1`, [
        session.sessionHash,
      ])
      .catch((err: unknown) => deps.log("session touch failed", err));
  }

  return {
    ok: true,
    identity,
    via,
    session: session
      ? {
          sessionHash: session.sessionHash,
          subject: session.subject,
          csrfToken: session.csrfToken,
          expiresAt: session.expiresAt,
        }
      : null,
  };
}

/** Expired sessions and dead in-flight grants are swept opportunistically. */
async function sweepExpired(deps: SessionDeps): Promise<void> {
  await deps.pool
    .query(`DELETE FROM dashboard_sessions WHERE expires_at < now()`)
    .catch((err: unknown) => deps.log("session sweep failed", err));
  await deps.pool
    .query(`DELETE FROM dashboard_auth_states WHERE expires_at < now()`)
    .catch((err: unknown) => deps.log("auth-state sweep failed", err));
}

export function registerAuth(app: FastifyInstance, deps: SessionDeps): void {
  // -- authorization-code start ----------------------------------------------

  app.get("/v1/auth/login", async (req, reply) => {
    const query = req.query as { redirect?: unknown };
    const redirectTo = safeRedirectPath(query.redirect, deps.cfg.dashboard.postLoginPath);
    const state = randomBytes(24).toString("base64url");
    const pkce = generatePkce();
    await sweepExpired(deps);
    await deps.pool.query(
      `INSERT INTO dashboard_auth_states (state_hash, code_verifier, redirect_to, expires_at)
       VALUES ($1, $2, $3, now() + make_interval(secs => $4))`,
      [hash(state), pkce.verifier, redirectTo, AUTH_STATE_TTL_S],
    );
    let target: string;
    try {
      target = await deps.oidc.authorizationUrl({
        redirectUri: redirectUri(deps.cfg),
        state,
        codeChallenge: pkce.challenge,
      });
    } catch (err) {
      deps.log("authorization URL construction failed", err);
      return reply.code(503).send({ error: "idp_unavailable" });
    }
    return reply.code(302).header("location", target).send();
  });

  // -- authorization-code callback -------------------------------------------

  app.get("/v1/auth/callback", async (req, reply) => {
    const query = req.query as { code?: unknown; state?: unknown; error?: unknown };
    if (typeof query.error === "string" && query.error) {
      return reply.code(400).send({ error: "authorization_failed", detail: query.error });
    }
    const code = typeof query.code === "string" ? query.code : "";
    const state = typeof query.state === "string" ? query.state : "";
    if (!code || !state) {
      return reply.code(400).send({ error: "invalid_request", detail: "code and state are required" });
    }
    // Single-use by construction: the row is claimed by the DELETE, so a
    // replayed callback finds nothing to exchange against.
    const { rows } = await deps.pool.query<{ code_verifier: string; redirect_to: string }>(
      `DELETE FROM dashboard_auth_states
        WHERE state_hash = $1 AND expires_at > now()
        RETURNING code_verifier, redirect_to`,
      [hash(state)],
    );
    const pending = rows[0];
    if (!pending) {
      return reply.code(400).send({ error: "invalid_state", detail: "unknown, expired, or already-used state" });
    }

    let grant;
    try {
      grant = await deps.oidc.exchangeCode({
        code,
        redirectUri: redirectUri(deps.cfg),
        codeVerifier: pending.code_verifier,
      });
    } catch (err) {
      deps.log("authorization-code exchange failed", err);
      return reply.code(503).send({ error: "idp_unavailable" });
    }
    if (!grant) {
      return reply.code(400).send({ error: "invalid_grant", detail: "the IdP refused the authorization code" });
    }

    // The session's subject comes from the verifier, not from the token
    // body — the same resolution every later request repeats.
    let identity: Identity | null;
    try {
      identity = await deps.oidc.resolveIdentity(grant.accessToken);
    } catch (err) {
      deps.log("identity resolution failed at callback", err);
      return reply.code(503).send({ error: "idp_unavailable" });
    }
    if (!identity) {
      return reply.code(401).send({ error: "unauthorized", detail: "the IdP does not honour the freshly issued token" });
    }

    // D-102.1: expiry follows the IdP's token lifetime, with the
    // deployment's cap as a ceiling — never an extension.
    const lifetimeS = Math.min(grant.expiresIn, deps.cfg.dashboard.sessionMaxS);
    const sessionId = randomBytes(32).toString("base64url");
    const csrfToken = randomBytes(32).toString("base64url");
    await deps.pool.query(
      `INSERT INTO dashboard_sessions
         (session_hash, subject, access_token, refresh_token, csrf_token, expires_at)
       VALUES ($1, $2, $3, $4, $5, now() + make_interval(secs => $6))`,
      [hash(sessionId), identity.subject, grant.accessToken, grant.refreshToken, csrfToken, lifetimeS],
    );
    setSessionCookie(deps, reply, sessionId, lifetimeS);
    return reply.code(302).header("location", pending.redirect_to).send();
  });

  // -- session introspection (the SPA's bootstrap) ---------------------------

  app.get("/v1/auth/session", async (req, reply) => {
    const auth = await authenticate(deps, req);
    if (!auth.ok) {
      return reply.code(auth.status).send({ error: auth.code, detail: auth.detail });
    }
    return reply.send({
      api_version: "1",
      subject: auth.identity.subject,
      roles: auth.identity.roles,
      ...(auth.identity.display ? { display: auth.identity.display } : {}),
      via: auth.via,
      // Present only on cookie sessions: a bearer caller has no ambient
      // credential to protect and no CSRF token to spend.
      ...(auth.session
        ? { csrf_token: auth.session.csrfToken, expires_at: auth.session.expiresAt.toISOString() }
        : {}),
    });
  });

  // -- logout ----------------------------------------------------------------

  app.post("/v1/auth/logout", async (req, reply) => {
    const auth = await authenticate(deps, req, { write: true });
    if (!auth.ok) {
      // An already-dead session logging out is a success, not an error.
      if (auth.code === "session_expired") {
        clearSessionCookie(deps, reply);
        return reply.send({ api_version: "1", status: "logged_out" });
      }
      return reply.code(auth.status).send({ error: auth.code, detail: auth.detail });
    }
    if (auth.session) {
      await deps.pool.query(`DELETE FROM dashboard_sessions WHERE session_hash = $1`, [
        auth.session.sessionHash,
      ]);
    }
    clearSessionCookie(deps, reply);
    return reply.send({ api_version: "1", status: "logged_out" });
  });
}
