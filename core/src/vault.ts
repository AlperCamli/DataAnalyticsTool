/**
 * Core-side credential-reference resolution (A-4).
 *
 * The runner has had a resolver seam since CP-3a; the core never did. Its
 * own secrets — the ops database URL, the runner and ops service tokens,
 * the KB git token, the OIDC client secret — arrived as plaintext
 * environment values from a git-ignored file, which is the posture A-4
 * exists to end. This module gives the core the same reference discipline
 * the job payloads have always had.
 *
 *     vault://<mount>/<path>#<field>
 *
 * The shape is deliberately identical to `connectors/sdk/vault.py`, down
 * to the absent version pin: one reference syntax across the platform, so
 * an operator writes the same string in `sync_systems.credentials` and in
 * a core env file and it means the same thing. Always-latest, because a
 * pinned reference is a rotation that silently does not take.
 *
 * **Resolution happens once, at boot, and it is all-or-nothing.** A core
 * that starts with half its secrets resolved is a core that fails later,
 * somewhere else, with a worse error — the same reason snapshots are
 * all-or-nothing per system (S-6). An unresolvable reference names the
 * *variable* and the *reference*, and the process exits.
 *
 * JC-8 throughout: nothing here logs a resolved value, and nothing logs a
 * vault response body — a vault read response is made entirely of
 * credential material, so the rule is not "scrub it" but "never touch it".
 */

export const VAULT_SCHEME = "vault://";

export class VaultError extends Error {}

export interface VaultRef {
  mount: string;
  path: string;
  field: string;
}

/** `vault://secret/contextlayer/core#database_url` → its three parts. */
export function parseVaultRef(ref: string): VaultRef {
  if (!ref.startsWith(VAULT_SCHEME)) {
    throw new VaultError(`${ref}: not a ${VAULT_SCHEME} reference`);
  }
  const body = ref.slice(VAULT_SCHEME.length);
  const hash = body.indexOf("#");
  if (hash === -1) {
    throw new VaultError(
      `${ref}: no #field — a KV v2 secret is a map, so the reference has to ` +
        `say which key it means`,
    );
  }
  const location = body.slice(0, hash);
  const field = body.slice(hash + 1);
  const slash = location.indexOf("/");
  const mount = slash === -1 ? "" : location.slice(0, slash);
  const path = slash === -1 ? "" : location.slice(slash + 1).replace(/^\/+|\/+$/g, "");
  if (!mount || !path || !field) {
    throw new VaultError(`${ref}: expected ${VAULT_SCHEME}<mount>/<path>#<field>`);
  }
  return { mount, path, field };
}

/** The KV v2 read path: `<mount>/data/<path>`. */
export function readPath(ref: VaultRef): string {
  const segments = ref.path.split("/").map(encodeURIComponent).join("/");
  return `${encodeURIComponent(ref.mount)}/data/${segments}`;
}

export interface VaultAuth {
  roleId?: string;
  secretId?: string;
  /** Dev-server path only — a static token in the environment is the same
   *  plaintext problem A-4 removes, one level up. */
  token?: string;
}

export interface VaultSettings {
  addr: string;
  auth: VaultAuth;
  timeoutMs: number;
  approlePath: string;
}

/**
 * Vault settings from the environment, or null when the deployment names
 * no vault at all. Null is legitimate: a stack whose config holds no
 * `vault://` reference needs no vault, and must not be made to want one.
 */
export function vaultSettingsFromEnv(env: NodeJS.ProcessEnv): VaultSettings | null {
  const addr = (env.VAULT_ADDR ?? "").replace(/\/$/, "");
  if (!addr) return null;
  return {
    addr,
    auth: {
      roleId: env.VAULT_ROLE_ID || undefined,
      secretId: env.VAULT_SECRET_ID || undefined,
      token: env.VAULT_TOKEN || undefined,
    },
    timeoutMs: Number(env.VAULT_TIMEOUT_MS ?? 10_000),
    approlePath: env.VAULT_APPROLE_PATH ?? "approle",
  };
}

/** What `/healthz` may say about vault: reachability, never contents. */
export interface VaultHealth {
  configured: boolean;
  reachable: boolean;
  /** Vault's own seal state — the single most common reason a restarted
   *  stack cannot read anything. Operationally vital and not a secret. */
  sealed?: boolean;
  initialized?: boolean;
  /** Why the probe failed, as a short class name — never a body. */
  error?: string;
}

export class VaultClient {
  private token: string | null = null;
  private tokenExpiresAt = 0;

  constructor(
    private readonly settings: VaultSettings,
    private readonly now: () => number = () => Date.now(),
  ) {}

  private get approle(): boolean {
    return Boolean(this.settings.auth.roleId && this.settings.auth.secretId);
  }

  private async request(
    path: string,
    init: RequestInit & { headers?: Record<string, string> } = {},
  ): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.settings.timeoutMs);
    try {
      return await fetch(`${this.settings.addr}${path}`, {
        ...init,
        signal: controller.signal,
      });
    } catch (err) {
      // The error *type* is useful; its message can carry the URL and, in
      // a login, the body that was sent.
      throw new VaultError(
        `vault unreachable at ${this.settings.addr}: ${(err as Error).name}`,
      );
    } finally {
      clearTimeout(timer);
    }
  }

  /** AppRole login, or the dev token passed through. */
  private async clientToken(force = false): Promise<string> {
    if (!this.approle) {
      const token = this.settings.auth.token;
      if (!token) {
        throw new VaultError(
          "vault identity is not configured: set VAULT_ROLE_ID + VAULT_SECRET_ID " +
            "(AppRole), or VAULT_TOKEN for a dev server",
        );
      }
      return token;
    }
    if (!force && this.token && this.now() < this.tokenExpiresAt) return this.token;

    const response = await this.request(
      `/v1/auth/${this.settings.approlePath}/login`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          role_id: this.settings.auth.roleId,
          secret_id: this.settings.auth.secretId,
        }),
      },
    );
    if (!response.ok) {
      throw new VaultError(
        `vault AppRole login refused (HTTP ${response.status}) — the core's own ` +
          `VAULT_ROLE_ID/VAULT_SECRET_ID, not a config reference`,
      );
    }
    const body = (await response.json()) as {
      auth?: { client_token?: string; lease_duration?: number };
    };
    const token = body.auth?.client_token;
    if (!token) throw new VaultError("vault AppRole login returned no client_token");
    const leaseS = Number(body.auth?.lease_duration ?? 0);
    this.token = token;
    // Re-login 30s early so a read never starts on a token about to expire.
    this.tokenExpiresAt = this.now() + Math.max(leaseS - 30, 1) * 1000;
    return token;
  }

  /** Read one field of one KV v2 secret. */
  async read(ref: string): Promise<string> {
    const parsed = parseVaultRef(ref);
    const path = `/v1/${readPath(parsed)}`;
    let response = await this.request(path, {
      headers: { "x-vault-token": await this.clientToken() },
    });
    if (response.status === 401 || response.status === 403) {
      response = await this.request(path, {
        headers: { "x-vault-token": await this.clientToken(true) },
      });
    }

    if (response.status === 404) {
      throw new VaultError(
        `${ref}: no secret at ${parsed.mount}/${parsed.path} (or it is deleted)`,
      );
    }
    if (response.status === 401 || response.status === 403) {
      throw new VaultError(
        `${ref}: denied by vault policy — this identity may not read ` +
          `${parsed.mount}/${parsed.path}`,
      );
    }
    if (!response.ok) {
      throw new VaultError(`${ref}: vault read failed (HTTP ${response.status})`);
    }

    const body = (await response.json()) as { data?: { data?: Record<string, unknown> } };
    const data = body.data?.data;
    if (data === undefined) {
      throw new VaultError(
        `${ref}: vault response was not a KV v2 secret (is the mount KV version 2?)`,
      );
    }
    if (data === null) {
      throw new VaultError(`${ref}: the secret at ${parsed.mount}/${parsed.path} has been deleted`);
    }
    const value = data[parsed.field];
    if (value === undefined || value === null || value === "") {
      // Naming the keys that *are* present would be a helpful hint and a
      // schema leak. The caller already knows what it asked for.
      throw new VaultError(
        `${ref}: the secret at ${parsed.mount}/${parsed.path} has no field "${parsed.field}"`,
      );
    }
    return String(value);
  }

  /** Unauthenticated seal/init probe for `/healthz`. */
  async health(): Promise<VaultHealth> {
    try {
      const response = await this.request("/v1/sys/health?standbyok=true&sealedcode=200&uninitcode=200");
      const body = (await response.json()) as { sealed?: boolean; initialized?: boolean };
      return {
        configured: true,
        reachable: true,
        sealed: Boolean(body.sealed),
        initialized: Boolean(body.initialized),
      };
    } catch (err) {
      return {
        configured: true,
        reachable: false,
        error: err instanceof VaultError ? "unreachable" : (err as Error).name,
      };
    }
  }
}

/**
 * Resolve every `vault://` value in an environment map, at boot.
 *
 * Generic by design: any variable whose value is a reference is one. The
 * alternative — a hand-maintained list of "the secret ones" — is a list
 * that goes stale the first time someone adds a config value, and a
 * secret that silently stays plaintext because its name was not on it.
 *
 * All-or-nothing: the first unresolvable reference throws, naming the
 * variable and the reference so the operator knows *which* key to go
 * look at, and never the value of any key.
 */
export async function resolveEnvReferences(
  env: NodeJS.ProcessEnv,
  client: Pick<VaultClient, "read"> | null,
): Promise<{ env: NodeJS.ProcessEnv; resolved: string[] }> {
  const refs = Object.entries(env).filter(
    ([, value]) => typeof value === "string" && value.startsWith(VAULT_SCHEME),
  ) as [string, string][];
  if (refs.length === 0) return { env, resolved: [] };

  if (!client) {
    throw new VaultError(
      `${refs.length} config value(s) are vault references (${refs
        .map(([name]) => name)
        .sort()
        .join(", ")}) but VAULT_ADDR is not set — this core cannot resolve its ` +
        `own secrets and will not start half-configured`,
    );
  }

  const out: NodeJS.ProcessEnv = { ...env };
  const resolved: string[] = [];
  for (const [name, ref] of refs) {
    try {
      out[name] = await client.read(ref);
      resolved.push(name);
    } catch (err) {
      throw new VaultError(
        `${name} could not be resolved: ${(err as Error).message}`,
      );
    }
  }
  return { env: out, resolved: resolved.sort() };
}
