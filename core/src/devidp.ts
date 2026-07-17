/**
 * DEV-ONLY OIDC provider — the compose-local IdP for the CP-4 pilot and
 * the in-process IdP the MCP conformance tests drive. It is NOT part of
 * the product surface: real deployments point CORE_OIDC_ISSUER at the
 * customer IdP (platform-architecture §2.1 Identity class); this exists
 * because the example estate has no customer IdP and because MT-9 needs a
 * deterministic revocation lever.
 *
 * Implements just enough of OIDC/OAuth for Claude Code's remote-MCP
 * flow and the core's per-call introspection: discovery, JWKS, PKCE
 * authorization-code with a login form, dynamic client registration
 * (RFC 7591), token, introspection (RFC 7662 — reads the user's
 * *current* roles so revocation is immediate), plus password and
 * client-credentials grants for scripting. Users and roles come from a
 * JSON file or the test harness, mutable at runtime via /admin/roles.
 */

import { createHash, createSign, generateKeyPairSync, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import http from "node:http";

export interface DevUser {
  username: string;
  password: string;
  roles: string[];
  display?: string;
}

interface CodeGrant {
  username: string;
  clientId: string;
  redirectUri: string;
  codeChallenge: string | null;
  exp: number;
}

interface IssuedToken {
  username: string;
  exp: number;
  revoked: boolean;
}

function b64url(data: Buffer | string): string {
  return Buffer.from(data).toString("base64url");
}

export interface DevIdp {
  issuer: string;
  port: number;
  close: () => Promise<void>;
  /** MT-9 lever: replace a user's roles; introspection reflects it immediately. */
  setRoles: (username: string, roles: string[]) => void;
  /** Convenience for tests/scripts: mint an access token for a user. */
  passwordToken: (username: string) => string;
  revokeToken: (token: string) => void;
}

export async function startDevIdp(options: {
  port?: number;
  users: DevUser[];
  /** Advertised issuer host (compose: the service name); default 127.0.0.1. */
  host?: string;
  tokenTtlS?: number;
}): Promise<DevIdp> {
  const users = new Map(options.users.map((u) => [u.username, { ...u, roles: [...u.roles] }]));
  const codes = new Map<string, CodeGrant>();
  const tokens = new Map<string, IssuedToken>();
  const clients = new Map<string, { redirectUris: string[] }>();
  const tokenTtlS = options.tokenTtlS ?? 3600;

  const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const jwk = publicKey.export({ format: "jwk" }) as Record<string, string>;
  const kid = "dev-idp-1";

  let issuer = "";

  function jwtFor(username: string, exp: number): string {
    const user = users.get(username)!;
    const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT", kid }));
    const payload = b64url(
      JSON.stringify({
        iss: issuer,
        sub: username,
        preferred_username: username,
        name: user.display ?? username,
        roles: user.roles,
        iat: Math.floor(Date.now() / 1000),
        exp,
      }),
    );
    const signer = createSign("RSA-SHA256");
    signer.update(`${header}.${payload}`);
    const signature = signer.sign(privateKey).toString("base64url");
    return `${header}.${payload}.${signature}`;
  }

  function mintToken(username: string): { token: string; exp: number } {
    const exp = Math.floor(Date.now() / 1000) + tokenTtlS;
    const token = jwtFor(username, exp);
    tokens.set(token, { username, exp, revoked: false });
    return { token, exp };
  }

  function loginPage(query: URLSearchParams, error = ""): string {
    const fields = ["response_type", "client_id", "redirect_uri", "state", "code_challenge", "code_challenge_method", "scope", "resource"]
      .map((k) => {
        const v = query.get(k);
        return v ? `<input type="hidden" name="${k}" value="${v.replace(/"/g, "&quot;")}">` : "";
      })
      .join("\n");
    return `<!doctype html><html><body style="font-family:sans-serif;max-width:22rem;margin:4rem auto">
<h2>Context Layer dev IdP</h2><p style="color:#a00">${error}</p>
<form method="post" action="/authorize">
${fields}
<label>User <input name="username" autofocus></label><br><br>
<label>Password <input name="password" type="password"></label><br><br>
<button type="submit">Sign in</button>
</form><p style="color:#666;font-size:0.8rem">dev-only provider — not for production</p></body></html>`;
  }

  const server = http.createServer((req, res) => {
    void handle(req, res).catch((err) => {
      res.writeHead(500, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "server_error", detail: String(err) }));
    });
  });

  async function readBody(req: http.IncomingMessage): Promise<string> {
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk as Buffer);
    return Buffer.concat(chunks).toString("utf-8");
  }

  function json(res: http.ServerResponse, status: number, body: unknown): void {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  }

  async function handle(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const url = new URL(req.url ?? "/", issuer);
    const path = url.pathname;

    if (path === "/.well-known/openid-configuration") {
      return json(res, 200, {
        issuer,
        authorization_endpoint: `${issuer}/authorize`,
        token_endpoint: `${issuer}/token`,
        jwks_uri: `${issuer}/jwks`,
        introspection_endpoint: `${issuer}/introspect`,
        registration_endpoint: `${issuer}/register`,
        userinfo_endpoint: `${issuer}/userinfo`,
        response_types_supported: ["code"],
        grant_types_supported: ["authorization_code", "refresh_token", "password", "client_credentials"],
        code_challenge_methods_supported: ["S256"],
        token_endpoint_auth_methods_supported: ["none", "client_secret_basic", "client_secret_post"],
        scopes_supported: ["openid", "profile"],
      });
    }
    // RFC 8414 alias some clients probe.
    if (path === "/.well-known/oauth-authorization-server") {
      req.url = "/.well-known/openid-configuration";
      return handle(req, res);
    }

    if (path === "/jwks") {
      return json(res, 200, { keys: [{ ...jwk, kid, alg: "RS256", use: "sig" }] });
    }

    if (path === "/register" && req.method === "POST") {
      const body = JSON.parse((await readBody(req)) || "{}") as { redirect_uris?: string[] };
      const clientId = `dev-${randomBytes(8).toString("hex")}`;
      clients.set(clientId, { redirectUris: body.redirect_uris ?? [] });
      return json(res, 201, {
        client_id: clientId,
        redirect_uris: body.redirect_uris ?? [],
        token_endpoint_auth_method: "none",
        grant_types: ["authorization_code", "refresh_token"],
        response_types: ["code"],
      });
    }

    if (path === "/authorize" && req.method === "GET") {
      res.writeHead(200, { "content-type": "text/html" });
      res.end(loginPage(url.searchParams));
      return;
    }

    if (path === "/authorize" && req.method === "POST") {
      const form = new URLSearchParams(await readBody(req));
      const username = form.get("username") ?? "";
      const password = form.get("password") ?? "";
      const user = users.get(username);
      if (!user || user.password !== password) {
        res.writeHead(401, { "content-type": "text/html" });
        res.end(loginPage(form, "invalid credentials"));
        return;
      }
      const redirectUri = form.get("redirect_uri") ?? "";
      const code = randomBytes(24).toString("base64url");
      codes.set(code, {
        username,
        clientId: form.get("client_id") ?? "",
        redirectUri,
        codeChallenge: form.get("code_challenge"),
        exp: Date.now() + 5 * 60_000,
      });
      const target = new URL(redirectUri);
      target.searchParams.set("code", code);
      const state = form.get("state");
      if (state) target.searchParams.set("state", state);
      res.writeHead(302, { location: target.toString() });
      res.end();
      return;
    }

    if (path === "/token" && req.method === "POST") {
      const form = new URLSearchParams(await readBody(req));
      const grant = form.get("grant_type");
      if (grant === "authorization_code") {
        const code = form.get("code") ?? "";
        const stored = codes.get(code);
        codes.delete(code);
        if (!stored || stored.exp < Date.now()) {
          return json(res, 400, { error: "invalid_grant" });
        }
        if (stored.codeChallenge) {
          const verifier = form.get("code_verifier") ?? "";
          const computed = createHash("sha256").update(verifier).digest("base64url");
          if (computed !== stored.codeChallenge) {
            return json(res, 400, { error: "invalid_grant", error_description: "PKCE verification failed" });
          }
        }
        const { token, exp } = mintToken(stored.username);
        const refresh = `r-${randomBytes(24).toString("base64url")}`;
        tokens.set(refresh, { username: stored.username, exp: Math.floor(Date.now() / 1000) + 30 * 24 * 3600, revoked: false });
        return json(res, 200, {
          access_token: token,
          token_type: "Bearer",
          expires_in: exp - Math.floor(Date.now() / 1000),
          refresh_token: refresh,
          scope: "openid profile",
        });
      }
      if (grant === "refresh_token") {
        const stored = tokens.get(form.get("refresh_token") ?? "");
        if (!stored || stored.revoked || stored.exp < Math.floor(Date.now() / 1000)) {
          return json(res, 400, { error: "invalid_grant" });
        }
        const { token, exp } = mintToken(stored.username);
        return json(res, 200, {
          access_token: token,
          token_type: "Bearer",
          expires_in: exp - Math.floor(Date.now() / 1000),
        });
      }
      if (grant === "password") {
        const user = users.get(form.get("username") ?? "");
        if (!user || user.password !== (form.get("password") ?? "")) {
          return json(res, 400, { error: "invalid_grant" });
        }
        const { token, exp } = mintToken(user.username);
        return json(res, 200, {
          access_token: token,
          token_type: "Bearer",
          expires_in: exp - Math.floor(Date.now() / 1000),
        });
      }
      return json(res, 400, { error: "unsupported_grant_type" });
    }

    if (path === "/introspect" && req.method === "POST") {
      const form = new URLSearchParams(await readBody(req));
      const token = form.get("token") ?? "";
      const stored = tokens.get(token);
      const user = stored ? users.get(stored.username) : undefined;
      if (!stored || stored.revoked || stored.exp < Math.floor(Date.now() / 1000) || !user) {
        return json(res, 200, { active: false });
      }
      // Roles are read live from the user record — a role revoked here
      // is gone on the caller's very next introspection (MT-9).
      return json(res, 200, {
        active: true,
        sub: user.username,
        username: user.username,
        preferred_username: user.username,
        name: user.display ?? user.username,
        roles: user.roles,
        exp: stored.exp,
        iss: issuer,
        token_type: "Bearer",
      });
    }

    if (path === "/userinfo") {
      const auth = req.headers.authorization ?? "";
      const token = auth.startsWith("Bearer ") ? auth.slice(7) : "";
      const stored = tokens.get(token);
      const user = stored && !stored.revoked ? users.get(stored.username) : undefined;
      if (!user) return json(res, 401, { error: "invalid_token" });
      return json(res, 200, { sub: user.username, preferred_username: user.username, name: user.display, roles: user.roles });
    }

    if (path === "/admin/roles" && req.method === "POST") {
      const body = JSON.parse((await readBody(req)) || "{}") as { username?: string; roles?: string[] };
      const user = body.username ? users.get(body.username) : undefined;
      if (!user || !Array.isArray(body.roles)) return json(res, 400, { error: "username + roles required" });
      user.roles = body.roles.filter((r): r is string => typeof r === "string");
      return json(res, 200, { username: user.username, roles: user.roles });
    }

    json(res, 404, { error: "not_found" });
  }

  await new Promise<void>((resolve) => server.listen(options.port ?? 0, "0.0.0.0", resolve));
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  issuer = `http://${options.host ?? "127.0.0.1"}:${port}`;

  return {
    issuer,
    port,
    close: () => new Promise((resolve) => server.close(() => resolve())),
    setRoles: (username, roles) => {
      const user = users.get(username);
      if (!user) throw new Error(`no dev user ${username}`);
      user.roles = [...roles];
    },
    passwordToken: (username) => {
      if (!users.get(username)) throw new Error(`no dev user ${username}`);
      return mintToken(username).token;
    },
    revokeToken: (token) => {
      const stored = tokens.get(token);
      if (stored) stored.revoked = true;
    },
  };
}

/** Compose entrypoint: `node dist/devidp.js users.json` (port via DEVIDP_PORT). */
export async function devIdpMain(): Promise<void> {
  const usersFile = process.argv[2];
  if (!usersFile) {
    console.error("usage: node dist/devidp.js USERS.json");
    process.exit(2);
  }
  const users = JSON.parse(readFileSync(usersFile, "utf-8")) as DevUser[];
  const idp = await startDevIdp({
    port: Number(process.env.DEVIDP_PORT ?? 8180),
    host: process.env.DEVIDP_HOST ?? "127.0.0.1",
    users,
  });
  console.log(`dev IdP (NOT FOR PRODUCTION) at ${idp.issuer}`);
}

const invokedDirectly = process.argv[1]?.endsWith("devidp.js");
if (invokedDirectly) void devIdpMain();
