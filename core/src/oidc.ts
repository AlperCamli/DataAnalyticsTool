/**
 * Per-call OIDC identity resolution (MCP spec §3, MCP-R1).
 *
 * Identity is resolved by token **introspection** against the customer
 * IdP on every call — never from a locally verified JWT alone — so role
 * revocation at the IdP takes effect on the very next call (MT-9) and a
 * mid-session token swap re-binds identity by construction (MCP-R3).
 * The discovery document is cached (endpoints are not roles); nothing
 * derived from a token ever is.
 */

import type { McpConfig } from "./config.js";

export interface Identity {
  subject: string;
  roles: string[];
  display?: string;
}

interface Discovery {
  introspection_endpoint?: string;
  userinfo_endpoint?: string;
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
}
