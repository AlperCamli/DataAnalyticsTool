/**
 * Per-call OIDC identity resolution (MCP spec §3, MCP-R1).
 *
 * Identity is resolved by token **introspection** against the customer
 * IdP on every call — never from a locally verified JWT alone — so role
 * revocation at the IdP takes effect on the very next call (MT-9) and a
 * mid-session token swap re-binds identity by construction (MCP-R3).
 * The discovery document is cached (endpoints are not roles); nothing
 * derived from a token ever is.
 *
 * Since B-0 this module also carries the browser leg of the same flow
 * (D-102.1): the authorization-code grant that mints a dashboard
 * session's token. It lives here deliberately — `resolveIdentity` below
 * stays the **one** place `{subject, roles}` is derived, for the MCP
 * path and the dashboard path alike, so there is no second role-
 * resolution code path to drift from this one (UI-2).
 */

import { createHash, randomBytes } from "node:crypto";
import type { McpConfig } from "./config.js";

export interface Identity {
  subject: string;
  roles: string[];
  display?: string;
}

interface Discovery {
  introspection_endpoint?: string;
  userinfo_endpoint?: string;
  authorization_endpoint?: string;
  token_endpoint?: string;
}

/** One authorization-code grant's PKCE pair (RFC 7636, S256). */
export interface PkcePair {
  verifier: string;
  challenge: string;
}

export function generatePkce(): PkcePair {
  const verifier = randomBytes(32).toString("base64url");
  return {
    verifier,
    challenge: createHash("sha256").update(verifier).digest("base64url"),
  };
}

export interface TokenGrant {
  accessToken: string;
  refreshToken: string | null;
  /** Seconds until the access token expires, per the IdP's response. */
  expiresIn: number;
}

/** Walk a dotted claim path (`realm_access.roles`) through the payload. */
function claimPath(payload: Record<string, unknown>, dotted: string): unknown {
  let cursor: unknown = payload;
  for (const part of dotted.split(".")) {
    if (cursor === null || typeof cursor !== "object") return undefined;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return cursor;
}

export class OidcClient {
  private discovery: Discovery | null = null;

  constructor(private readonly cfg: McpConfig) {}

  private async discover(): Promise<Discovery> {
    if (this.discovery) return this.discovery;
    const url = `${this.cfg.oidcIssuer}/.well-known/openid-configuration`;
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`OIDC discovery failed (${response.status}) at ${url}`);
    }
    this.discovery = (await response.json()) as Discovery;
    return this.discovery;
  }

  /**
   * Resolve `{subject, roles}` from the bearer token, live at the IdP.
   * Returns null for a missing/invalid/expired/revoked token.
   */
  async resolveIdentity(token: string): Promise<Identity | null> {
    if (!token) return null;
    const discovery = await this.discover();
    if (!discovery.introspection_endpoint) {
      throw new Error("IdP advertises no introspection endpoint; per-call role resolution requires one");
    }
    const headers: Record<string, string> = {
      "content-type": "application/x-www-form-urlencoded",
    };
    if (this.cfg.oidcClientId) {
      const basic = Buffer.from(`${this.cfg.oidcClientId}:${this.cfg.oidcClientSecret}`).toString("base64");
      headers.authorization = `Basic ${basic}`;
    }
    const response = await fetch(discovery.introspection_endpoint, {
      method: "POST",
      headers,
      body: new URLSearchParams({ token }).toString(),
    });
    if (!response.ok) return null;
    const payload = (await response.json()) as Record<string, unknown>;
    if (payload.active !== true) return null;
    const subject =
      (typeof payload.preferred_username === "string" && payload.preferred_username) ||
      (typeof payload.username === "string" && payload.username) ||
      (typeof payload.sub === "string" && payload.sub) ||
      "";
    if (!subject) return null;
    let roles: string[] = [];
    const claim = claimPath(payload, this.cfg.rolesClaim);
    if (Array.isArray(claim)) {
      roles = claim.filter((r): r is string => typeof r === "string");
    } else if (typeof claim === "string") {
      roles = claim.split(/[\s,]+/).filter(Boolean);
    }
    const display = typeof payload.name === "string" ? payload.name : undefined;
    return { subject, roles, ...(display !== undefined ? { display } : {}) };
  }

  // -- browser authorization-code leg (D-102.1) ------------------------------
  //
  // Nothing below derives identity. These build the redirect and trade a
  // code for a token; the token is then handed to `resolveIdentity`
  // above like any other, which is what keeps the dashboard's identity
  // and the MCP path's identity the same computation.

  /** The IdP's authorization URL for one PKCE authorization-code grant. */
  async authorizationUrl(params: {
    redirectUri: string;
    state: string;
    codeChallenge: string;
    scope?: string;
  }): Promise<string> {
    const discovery = await this.discover();
    if (!discovery.authorization_endpoint) {
      throw new Error("IdP advertises no authorization endpoint; the browser session flow requires one");
    }
    const url = new URL(discovery.authorization_endpoint);
    url.searchParams.set("response_type", "code");
    url.searchParams.set("client_id", this.cfg.oidcClientId);
    url.searchParams.set("redirect_uri", params.redirectUri);
    url.searchParams.set("state", params.state);
    url.searchParams.set("code_challenge", params.codeChallenge);
    url.searchParams.set("code_challenge_method", "S256");
    url.searchParams.set("scope", params.scope ?? "openid profile");
    return url.toString();
  }

  /** Exchange an authorization code for the caller's own access token. */
  async exchangeCode(params: {
    code: string;
    redirectUri: string;
    codeVerifier: string;
  }): Promise<TokenGrant | null> {
    const discovery = await this.discover();
    if (!discovery.token_endpoint) {
      throw new Error("IdP advertises no token endpoint; the browser session flow requires one");
    }
    const headers: Record<string, string> = {
      "content-type": "application/x-www-form-urlencoded",
    };
    const body: Record<string, string> = {
      grant_type: "authorization_code",
      code: params.code,
      redirect_uri: params.redirectUri,
      code_verifier: params.codeVerifier,
    };
    if (this.cfg.oidcClientId) {
      const basic = Buffer.from(`${this.cfg.oidcClientId}:${this.cfg.oidcClientSecret}`).toString("base64");
      headers.authorization = `Basic ${basic}`;
      body.client_id = this.cfg.oidcClientId;
    }
    const response = await fetch(discovery.token_endpoint, {
      method: "POST",
      headers,
      body: new URLSearchParams(body).toString(),
    });
    if (!response.ok) return null;
    const payload = (await response.json()) as Record<string, unknown>;
    const accessToken = typeof payload.access_token === "string" ? payload.access_token : "";
    if (!accessToken) return null;
    return {
      accessToken,
      refreshToken: typeof payload.refresh_token === "string" ? payload.refresh_token : null,
      expiresIn: Number(payload.expires_in) > 0 ? Number(payload.expires_in) : 3600,
    };
  }
}
