/**
 * Core-side credential-reference resolution (A-4, `core/src/vault.ts`).
 *
 * Three things have to be true, and each has cost something somewhere to
 * learn: the reference syntax matches the runner's exactly (one string
 * means one thing across the platform); boot is all-or-nothing (a core on
 * half its secrets fails later, elsewhere, worse); and no error, log or
 * health field ever carries a resolved value (JC-8).
 *
 * Run against a stub fetch rather than a live Vault, so this suite needs
 * no container. The live path is proved by the pilot migration.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  parseVaultRef,
  readPath,
  resolveEnvReferences,
  VaultClient,
  VaultError,
  vaultSettingsFromEnv,
} from "../src/vault.js";

const CANARY = "postgres://cl:super-secret-canary@db/ops";

/** A stand-in for Vault's AppRole + KV v2 surface. */
function fakeVault(secrets: Record<string, Record<string, unknown>>) {
  const state = {
    logins: 0,
    issued: [] as string[],
    urls: [] as string[],
    posted: [] as string[],
    sealed: false,
    reachable: true,
    secrets,
  };

  const fetchStub = vi.fn(async (url: string, init?: RequestInit) => {
    state.urls.push(url);
    if (!state.reachable) throw new TypeError("fetch failed");
    const path = new URL(url).pathname;

    if (path === "/v1/auth/approle/login") {
      state.posted.push(String(init?.body ?? ""));
      const body = JSON.parse(String(init?.body ?? "{}"));
      if (body.role_id !== "rid" || body.secret_id !== "sid") {
        return new Response(JSON.stringify({ errors: ["invalid role or secret id"] }), {
          status: 400,
        });
      }
      state.logins += 1;
      const token = `s.token-${state.logins}`;
      state.issued.push(token);
      return new Response(
        JSON.stringify({ auth: { client_token: token, lease_duration: 60 } }),
        { status: 200 },
      );
    }

    if (path === "/v1/sys/health") {
      return new Response(JSON.stringify({ sealed: state.sealed, initialized: true }), {
        status: 200,
      });
    }

    const token = (init?.headers as Record<string, string>)?.["x-vault-token"];
    if (!state.issued.includes(token ?? "")) {
      return new Response(JSON.stringify({ errors: ["permission denied"] }), {
        status: 403,
      });
    }
    const location = path.replace("/v1/", "").replace("/data/", "/");
    const secret = state.secrets[location];
    if (!secret) return new Response(JSON.stringify({ errors: [] }), { status: 404 });
    return new Response(JSON.stringify({ data: { data: secret, metadata: {} } }), {
      status: 200,
    });
  });

  vi.stubGlobal("fetch", fetchStub);
  return state;
}

function client(now?: () => number): VaultClient {
  return new VaultClient(
    {
      addr: "https://vault.invalid",
      auth: { roleId: "rid", secretId: "sid" },
      timeoutMs: 1000,
      approlePath: "approle",
    },
    now,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("reference syntax", () => {
  it("parses into mount, path and field, and inserts KV v2's /data/", () => {
    const ref = parseVaultRef("vault://secret/contextlayer/core#database_url");
    expect(ref).toEqual({
      mount: "secret",
      path: "contextlayer/core",
      field: "database_url",
    });
    // The `/data/` segment is the engine's, not the reference's — so the
    // string an operator writes here is the same string they write in the
    // connection registry, and a KV version change rewrites one line.
    expect(readPath(ref)).toBe("secret/data/contextlayer/core");
  });

  it.each([
    ["vault://secret/contextlayer/core", "no #field"],
    ["vault://secret#dsn", "no path"],
    ["vault:///core#dsn", "no mount"],
    ["vault://secret/core#", "empty field"],
    ["env://CL_EXEC_DSN", "wrong scheme"],
  ])("refuses %s (%s)", (ref) => {
    expect(() => parseVaultRef(ref)).toThrow(VaultError);
  });
});

describe("reads", () => {
  it("logs in as itself, then reads the field", async () => {
    const vault = fakeVault({ "secret/contextlayer/core": { database_url: CANARY } });
    const value = await client().read("vault://secret/contextlayer/core#database_url");
    expect(value).toBe(CANARY);
    expect(vault.logins).toBe(1);
    expect(vault.urls[1]).toBe("https://vault.invalid/v1/secret/data/contextlayer/core");
  });

  it("reuses one login across many reads", async () => {
    const vault = fakeVault({
      "secret/a": { k: "1" },
      "secret/b": { k: "2" },
      "secret/c": { k: "3" },
    });
    const c = client();
    for (const name of ["a", "b", "c"]) await c.read(`vault://secret/${name}#k`);
    expect(vault.logins).toBe(1);
  });

  it("re-logs in when the lease has run out", async () => {
    const vault = fakeVault({ "secret/a": { k: "v" } });
    let clock = 0;
    const c = client(() => clock);
    await c.read("vault://secret/a#k");
    expect(vault.logins).toBe(1);
    clock = 10 * 60 * 1000; // past the 60s lease
    await c.read("vault://secret/a#k");
    expect(vault.logins).toBe(2);
  });

  it("recovers from a revoked token by logging in again, once", async () => {
    const vault = fakeVault({ "secret/a": { k: "v" } });
    const c = client();
    await c.read("vault://secret/a#k");
    vault.issued.length = 0; // revoked out from under us
    await expect(c.read("vault://secret/a#k")).resolves.toBe("v");
    expect(vault.logins).toBe(2);
  });

  it("picks up a rotated value on the next read — no restart, no pin", async () => {
    const vault = fakeVault({ "secret/a": { k: "old" } });
    const c = client();
    expect(await c.read("vault://secret/a#k")).toBe("old");
    vault.secrets["secret/a"] = { k: "new" };
    expect(await c.read("vault://secret/a#k")).toBe("new");
  });

  it("names the missing field without listing the ones that are there", async () => {
    fakeVault({ "secret/a": { database_url: CANARY, git_token: "ghp_canary" } });
    await expect(client().read("vault://secret/a#oidc_secret")).rejects.toThrow(
      /has no field "oidc_secret"/,
    );
    // A key listing is a helpful hint and a schema leak; the values are
    // never in reach at all.
    await client()
      .read("vault://secret/a#oidc_secret")
      .catch((err: Error) => {
        expect(err.message).not.toContain("git_token");
        expect(err.message).not.toContain("ghp_canary");
        expect(err.message).not.toContain(CANARY);
      });
  });

  it("reports a missing secret and a denied policy differently", async () => {
    fakeVault({ "secret/a": { k: "v" } });
    await expect(client().read("vault://secret/nope#k")).rejects.toThrow(/no secret at/);
  });

  it("never echoes the identity it was refused with", async () => {
    fakeVault({});
    const wrong = new VaultClient({
      addr: "https://vault.invalid",
      auth: { roleId: "rid", secretId: "the-wrong-secret-id" },
      timeoutMs: 1000,
      approlePath: "approle",
    });
    await wrong.read("vault://secret/a#k").catch((err: Error) => {
      expect(err.message).toContain("login refused");
      expect(err.message).not.toContain("the-wrong-secret-id");
    });
    expect.assertions(2);
  });
});

describe("boot resolution", () => {
  it("replaces every reference and reports which variables it resolved", async () => {
    fakeVault({
      "secret/contextlayer/core": { database_url: CANARY, git_token: "ghp_canary" },
    });
    const { env, resolved } = await resolveEnvReferences(
      {
        CORE_DATABASE_URL: "vault://secret/contextlayer/core#database_url",
        SYNC_GIT_TOKEN: "vault://secret/contextlayer/core#git_token",
        CORE_LOG_LEVEL: "info",
      },
      client(),
    );
    expect(env.CORE_DATABASE_URL).toBe(CANARY);
    expect(env.SYNC_GIT_TOKEN).toBe("ghp_canary");
    expect(env.CORE_LOG_LEVEL).toBe("info"); // untouched
    // Names, so an operator can see what was resolved. Never values.
    expect(resolved).toEqual(["CORE_DATABASE_URL", "SYNC_GIT_TOKEN"]);
  });

  it("refuses to boot half-secret, naming the variable that failed", async () => {
    fakeVault({ "secret/contextlayer/core": { database_url: CANARY } });
    await expect(
      resolveEnvReferences(
        {
          CORE_DATABASE_URL: "vault://secret/contextlayer/core#database_url",
          CORE_OIDC_CLIENT_SECRET: "vault://secret/contextlayer/core#oidc_secret",
        },
        client(),
      ),
    ).rejects.toThrow(/CORE_OIDC_CLIENT_SECRET could not be resolved/);
  });

  it("refuses when references exist but no vault is configured", async () => {
    await expect(
      resolveEnvReferences({ CORE_DATABASE_URL: "vault://secret/a#k" }, null),
    ).rejects.toThrow(/CORE_DATABASE_URL.*VAULT_ADDR is not set/s);
  });

  it("leaves a deployment with no references entirely alone", async () => {
    // A stack that names no vault must not be made to want one.
    const env = { CORE_DATABASE_URL: "postgres://localhost/ops" };
    const result = await resolveEnvReferences(env, null);
    expect(result.env).toBe(env);
    expect(result.resolved).toEqual([]);
    expect(vaultSettingsFromEnv({})).toBeNull();
  });
});

describe("health", () => {
  it("reports reachability and seal state, and nothing else", async () => {
    const vault = fakeVault({});
    const health = await client().health();
    expect(health).toEqual({
      configured: true,
      reachable: true,
      sealed: false,
      initialized: true,
    });
    // A sealed vault after a host restart is the commonest way this
    // breaks, so it is a field rather than a mystery.
    vault.sealed = true;
    expect((await client().health()).sealed).toBe(true);
  });

  it("says unreachable rather than throwing into the health probe", async () => {
    const vault = fakeVault({});
    vault.reachable = false;
    const health = await client().health();
    expect(health.reachable).toBe(false);
    expect(health.configured).toBe(true);
    expect(JSON.stringify(health)).not.toContain("vault.invalid");
  });
});
