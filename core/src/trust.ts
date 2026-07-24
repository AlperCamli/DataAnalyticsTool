/**
 * Trust blocks (MCP spec §4, M-5, MCP-R12): computed server-side from
 * KB-HEAD front-matter status + live snapshot hashes; the client can
 * neither suppress nor override them. `agent_guidance` is the single
 * place the KB §5 status semantics map to agent behavior. Machine docs
 * carry snapshot provenance and the render-lag signal (MCP-R9
 * amendment, D-66.4).
 *
 * Honest scope (MCP-R12): for reads this block is advisory to the
 * agent — the hard controls are visibility (M-4), the execute-path
 * snapshot pin (§5), and the audit record.
 */

import type { KbDoc, KbState } from "./kbread.js";

export interface TrustBlock {
  status: string;
  last_verified: string | null;
  written_against: string | null;
  current_hash: string | null;
  hash_match: boolean;
  contamination: unknown;
  agent_guidance: "use-freely" | "warn-user" | "refuse-unless-override";
  snapshot_ref?: string;
  render_lag?: boolean;
}

function guidance(status: string, hashMatch: boolean): TrustBlock["agent_guidance"] {
  if (status === "contaminated") return "refuse-unless-override";
  if (status === "draft" || status === "stale") return "warn-user";
  if (status === "verified") return hashMatch ? "use-freely" : "warn-user";
  return "use-freely";
}

/** Trust for a human-owned doc (object/group/entity/metric/lineage-note). */
export function humanTrust(ws: KbState, doc: KbDoc): TrustBlock {
  const fm = doc.fm ?? {};
  const status = typeof fm.status === "string" ? fm.status : "draft";
  const writtenAgainst = typeof fm.written_against_schema_hash === "string" ? fm.written_against_schema_hash : null;
  const object = typeof fm.object === "string" ? fm.object : null;
  let currentHash: string | null = null;
  if (object) {
    const [system] = object.split(".");
    currentHash = ws.systems.get(system!)?.objects.get(object)?.schemaHash ?? null;
  }
  const hashMatch = writtenAgainst === null || currentHash === null || writtenAgainst === currentHash;
  return {
    status,
    last_verified: typeof fm.last_verified === "string" ? fm.last_verified : null,
    written_against: writtenAgainst,
    current_hash: currentHash,
    hash_match: hashMatch,
    contamination: fm.contamination ?? null,
    agent_guidance: guidance(status, hashMatch),
  };
}

/** Trust for a machine-owned doc: facts at the latest accepted snapshot
 * (MC-5), with provenance + render-lag per the MCP-R9 amendment. */
export function machineTrust(ws: KbState, system: string): TrustBlock {
  const state = ws.systems.get(system);
  const renderLag = state?.renderLag ?? false;
  return {
    status: "machine",
    last_verified: null,
    written_against: null,
    current_hash: null,
    hash_match: !renderLag,
    contamination: null,
    agent_guidance: renderLag ? "warn-user" : "use-freely",
    ...(state ? { snapshot_ref: `sha256:${state.canonicalBodySha256.replace(/^sha256:/, "")}` } : {}),
    render_lag: renderLag,
  };
}

/** The refs envelope every response carries (M-5). */
export function refsEnvelope(ws: KbState): { kb_ref: string; snapshot_ref: Record<string, string> } {
  const snapshotRef: Record<string, string> = {};
  for (const [system, state] of ws.systems) {
    snapshotRef[system] = `sha256:${state.canonicalBodySha256.replace(/^sha256:/, "")}`;
  }
  return { kb_ref: ws.headSha, snapshot_ref: snapshotRef };
}
