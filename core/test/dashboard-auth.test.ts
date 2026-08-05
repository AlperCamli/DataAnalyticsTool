/**
 * B-0 browser session auth (D-102.1, dashboard spec UI-2).
 *
 * The negatives are the point: no cookie is a 401, an expired session is
 * a 401 that re-authenticates cleanly, and a write without the CSRF
 * token is refused. The last test in this file is the structural one —
 * that the dashboard resolves identity through the *same* verifier the
 * MCP path uses and carries no role-resolution code of its own.
 */

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { apiGet, apiPost, login, setupDashboardRig, type DashboardRig } from "./dashboard-helpers.js";
import { repoRoot } from "./helpers.js";
import { USERS } from "./mcp-helpers.js";

const src = (name: string) => readFileSync(path.join(repoRoot(), "core", "src", name), "utf-8");

describe("dashboard session auth (D-102.1)", () => {
  let rig: DashboardRig;

  beforeAll(async () => {
    rig = await setupDashboardRig();
  }, 240_000);

  afterAll(async () => {
    await rig?.stop();
  });

  it("walks the OIDC authorization-code flow and issues an HttpOnly SameSite cookie", async () => {
    const start = await fetch(`${rig.base}/v1/auth/login`, { redirect: "manual" });
    expect(start.status).toBe(302);
    const authorize = new URL(start.headers.get("location")!);
    // The redirect is to the *same* IdP the MCP path introspects against.
    expect(`${authorize.origin}`).toBe(new URL(rig.idp.issuer).origin);
    expect(authorize.searchParams.get("response_type")).toBe("code");
    expect(authorize.searchParams.get("code_challenge_method")).toBe("S256");
    expect(authorize.searchParams.get("code_challenge")).toBeTruthy();

    const form = new URLSearchParams();
    for (const [k, v] of authorize.searchParams) form.set(k, v);
    form.set("username", USERS.reporter.username);
    form.set("password", USERS.reporter.password);
    const authorized = await fetch(`${authorize.origin}${authorize.pathname}`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: form.toString(),
      redirect: "manual",
    });
    expect(authorized.status).toBe(302);

    const callback = await fetch(authorized.headers.get("location")!, { redirect: "manual" });
    expect(callback.status).toBe(302);
    const setCookie = (callback.headers.getSetCookie?.() ?? []).find((c) => c.startsWith("cl_session="))!;
    expect(setCookie).toBeTruthy();
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("SameSite=Lax");
    expect(setCookie).toContain("Path=/");

    // The cookie is opaque: the access token stays server-side (UI-2).
    const value = setCookie.split(";")[0]!.slice("cl_session=".length);
    expect(value).not.toContain(".");
    const { rows } = await rig.core.pool.query<{ subject: string; access_token: string }>(
      `SELECT subject, access_token FROM dashboard_sessions`,
    );
    expect(rows[0]!.subject).toBe(USERS.reporter.username);
    expect(rows[0]!.access_token).not.toBe(value);
  });

  it("resolves the session's identity and roles from the IdP", async () => {
    const session = await login(rig, "steward");
    expect(session.subject).toBe(USERS.steward.username);
    expect(session.roles).toEqual(expect.arrayContaining(["steward", "ops"]));
    expect(session.csrf).toBeTruthy();
  });

  it("a replayed authorization state cannot mint a second session", async () => {
    const start = await fetch(`${rig.base}/v1/auth/login`, { redirect: "manual" });
    const authorize = new URL(start.headers.get("location")!);
    const form = new URLSearchParams();
    for (const [k, v] of authorize.searchParams) form.set(k, v);
    form.set("username", USERS.reporter.username);
    form.set("password", USERS.reporter.password);
    const authorized = await fetch(`${authorize.origin}${authorize.pathname}`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: form.toString(),
      redirect: "manual",
    });
    const callbackUrl = authorized.headers.get("location")!;
    expect((await fetch(callbackUrl, { redirect: "manual" })).status).toBe(302);
    const replay = await fetch(callbackUrl, { redirect: "manual" });
    expect(replay.status).toBe(400);
    expect(((await replay.json()) as { error: string }).error).toBe("invalid_state");
  });

  it("no cookie is a 401 on every B-0 endpoint", async () => {
    for (const endpoint of ["/v1/dashboard/audit", "/v1/dashboard/deliveries", "/v1/dashboard/ledger"]) {
      const res = await apiGet(rig, null, endpoint);
      expect(res.status, endpoint).toBe(401);
      expect(res.json.error, endpoint).toBe("unauthorized");
    }
    expect((await apiGet(rig, null, "/v1/auth/session")).status).toBe(401);
  });

  it("an unknown cookie is a 401, not a server error", async () => {
    const res = await fetch(`${rig.base}/v1/dashboard/audit`, {
      headers: { cookie: "cl_session=not-a-session" },
    });
    expect(res.status).toBe(401);
    expect(((await res.json()) as { error: string }).error).toBe("session_expired");
  });

  it("an expired session is a 401 that re-authenticates cleanly", async () => {
    const session = await login(rig, "reporter");
    expect((await apiGet(rig, session, "/v1/dashboard/audit")).status).toBe(200);

    await rig.core.pool.query(
      `UPDATE dashboard_sessions SET expires_at = now() - interval '1 minute'
        WHERE subject = $1`,
      [USERS.reporter.username],
    );
    const expired = await apiGet(rig, session, "/v1/dashboard/audit");
    expect(expired.status).toBe(401);
    expect(expired.json.error).toBe("session_expired");

    // Re-auth is the ordinary login flow, and it works.
    const fresh = await login(rig, "reporter");
    expect((await apiGet(rig, fresh, "/v1/dashboard/audit")).status).toBe(200);
  });

  it("an IdP-side revocation lands on the very next call (identity is never cached)", async () => {
    // A user of its own: the dev IdP mints a byte-identical JWT for two
    // logins in the same second, so revoking one user's token here would
    // reach across into another test's session.
    const session = await login(rig, "capped");
    expect((await apiGet(rig, session, "/v1/dashboard/audit")).status).toBe(200);

    const sessionHash = createHash("sha256")
      .update(session.cookie.slice("cl_session=".length))
      .digest("hex");
    const { rows } = await rig.core.pool.query<{ access_token: string }>(
      `SELECT access_token FROM dashboard_sessions WHERE session_hash = $1`,
      [sessionHash],
    );
    rig.idp.revokeToken(rows[0]!.access_token);

    const after = await apiGet(rig, session, "/v1/dashboard/audit");
    expect(after.status).toBe(401);
    // The dead session is dropped rather than left to be retried.
    const { rows: left } = await rig.core.pool.query(
      `SELECT 1 FROM dashboard_sessions WHERE session_hash = $1`,
      [sessionHash],
    );
    expect(left).toHaveLength(0);
  });

  it("writes on a cookie session require the CSRF token", async () => {
    const session = await login(rig, "reporter");
    const body = { description: "csrf probe: nothing documents refund handling" };

    const missing = await apiPost(rig, session, "/v1/dashboard/ledger/gaps", body, { csrf: null });
    expect(missing.status).toBe(403);
    expect(missing.json.error).toBe("csrf_required");

    const wrong = await apiPost(rig, session, "/v1/dashboard/ledger/gaps", body, { csrf: "not-the-token" });
    expect(wrong.status).toBe(403);
    expect(wrong.json.error).toBe("csrf_required");

    const ok = await apiPost(rig, session, "/v1/dashboard/ledger/gaps", body);
    expect(ok.status).toBe(201);
  });

  it("a bearer header cannot shed the CSRF requirement of a cookie session", async () => {
    const session = await login(rig, "reporter");
    const res = await fetch(`${rig.base}/v1/dashboard/ledger/gaps`, {
      method: "POST",
      headers: {
        cookie: session.cookie,
        authorization: `Bearer ${rig.token("reporter")}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ description: "cookie plus bearer, no csrf token" }),
    });
    expect(res.status).toBe(403);
    expect(((await res.json()) as { error: string }).error).toBe("csrf_required");
  });

  it("logout drops the session and clears the cookie", async () => {
    const session = await login(rig, "reporter");
    const out = await apiPost(rig, session, "/v1/auth/logout", {});
    expect(out.status).toBe(200);
    expect((out.headers.getSetCookie?.() ?? []).some((c) => c.includes("Max-Age=0"))).toBe(true);

    const after = await apiGet(rig, session, "/v1/dashboard/audit");
    expect(after.status).toBe(401);
  });

  it("post-login redirects stay same-origin", async () => {
    const evil = await fetch(`${rig.base}/v1/auth/login?redirect=${encodeURIComponent("//evil.example/x")}`, {
      redirect: "manual",
    });
    expect(evil.status).toBe(302);
    const { rows } = await rig.core.pool.query<{ redirect_to: string }>(
      `SELECT redirect_to FROM dashboard_auth_states ORDER BY created_at DESC LIMIT 1`,
    );
    expect(rows[0]!.redirect_to).toBe("/");
  });

  /**
   * D-102.1's structural clause, asserted by construction rather than by
   * review: one verifier, no parallel identity code. If a future change
   * grows a second role resolver for the dashboard, this fails.
   */
  it("resolves identity through the same verifier as MCP, with no duplicate role-resolution code", () => {
    const session = src("session.ts");
    const dashboard = src("dashboard.ts");
    const mcp = src("mcp.ts");
    const oidc = src("oidc.ts");

    // Exactly one module derives {subject, roles} from a token.
    expect(oidc).toContain("rolesClaim");
    for (const [name, text] of [
      ["session.ts", session],
      ["dashboard.ts", dashboard],
    ] as const) {
      for (const marker of ["rolesClaim", "introspection_endpoint", "realm_access", "preferred_username"]) {
        expect(text, `${name} must not re-implement role resolution (${marker})`).not.toContain(marker);
      }
    }

    // Both surfaces call the same resolver, imported from the same module.
    expect(session).toContain('from "./oidc.js"');
    expect(session).toMatch(/deps\.oidc\.resolveIdentity\(/);
    expect(mcp).toMatch(/deps\.oidc\.resolveIdentity\(/);

    // The dashboard never resolves identity itself: it asks the session
    // layer, which asks the one verifier.
    expect(dashboard).not.toContain("resolveIdentity");
    expect(dashboard).toContain('from "./session.js"');

    // UI-6/§7.2: no code path from the dashboard reaches a git provider.
    for (const [name, text] of [
      ["session.ts", session],
      ["dashboard.ts", dashboard],
    ] as const) {
      expect(text, `${name} must not import a git provider`).not.toContain("gitkb.js");
    }
  });
});
