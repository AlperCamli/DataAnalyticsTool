/**
 * Agent profiles (platform-architecture §5) as the MCP server enforces
 * them: the profile is bound from the client's config (URL parameter),
 * but the server independently validates the caller's roles against the
 * profile's `roles:` list (MCP-R2) and recomputes the per-call
 * allow-set from the *token's* roles — client config can never widen
 * access. Tool entries may carry system/target qualifiers
 * (`execute_sql:supabase`), enforced per call (MCP-R4). Profile
 * `limits` are the guardrails injected server-side (MCP-R8).
 */

export interface Profile {
  name: string;
  displayName: string;
  roles: string[];
  /** tool → allowed qualifiers (null = unqualified grant) */
  allow: Map<string, string[] | null>;
  limits: { row_cap?: number; timeout_s?: number };
}

export function parseProfile(name: string, raw: Record<string, unknown>): Profile {
  const allow = new Map<string, string[] | null>();
  const tools = raw.tools as { allow?: unknown } | undefined;
  const entries = Array.isArray(tools?.allow) ? tools.allow : [];
  for (const entry of entries) {
    if (typeof entry !== "string") continue;
    const [tool, qualifier] = entry.split(":", 2);
    if (!tool) continue;
    if (qualifier) {
      const existing = allow.get(tool);
      if (existing === null) continue; // already unqualified
      allow.set(tool, [...(existing ?? []), qualifier]);
    } else if (!allow.has(tool) || allow.get(tool) !== null) {
      allow.set(tool, null);
    }
  }
  const limits = (raw.limits as Profile["limits"] | undefined) ?? {};
  return {
    name,
    displayName: typeof raw.name === "string" ? raw.name : name,
    roles: Array.isArray(raw.roles) ? raw.roles.filter((r): r is string => typeof r === "string") : [],
    allow,
    limits,
  };
}

/** MCP-R2: the caller's roles permit the profile (non-empty overlap). */
export function profilePermitted(profile: Profile, callerRoles: string[]): boolean {
  return profile.roles.some((role) => callerRoles.includes(role));
}

/**
 * MCP-R4: tool allowed, with qualifier enforcement. `qualifierArg` is
 * the call's system/target argument when the tool takes one.
 */
export function toolAllowed(
  profile: Profile,
  tool: string,
  qualifierArg?: string,
): { allowed: boolean; reason?: string } {
  if (!profile.allow.has(tool)) {
    return { allowed: false, reason: `tool ${tool} is not in the ${profile.name} profile allowlist` };
  }
  const qualifiers = profile.allow.get(tool)!;
  if (qualifiers !== null && qualifierArg !== undefined && !qualifiers.includes(qualifierArg)) {
    return {
      allowed: false,
      reason: `tool ${tool} is granted only for ${qualifiers.join(", ")}, not ${qualifierArg}`,
    };
  }
  if (qualifiers !== null && qualifierArg === undefined) {
    return { allowed: false, reason: `tool ${tool} requires a system qualifier among ${qualifiers.join(", ")}` };
  }
  return { allowed: true };
}
