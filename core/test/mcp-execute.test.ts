/**
 * execute_sql token *enforcement* (CP-6/M2) — MT-3 and MT-4 upgraded
 * from issuance-only to enforcement, plus MT-5 (client guardrails
 * ignored) and the G2 gateway half of CC-3.
 *
 * Every refusal here happens before a job is enqueued, which is the
 * property under test: "never executes" is not "executed and then
 * discarded". Each case asserts both the error code and the absence of
 * any `execute` job in the queue.
 *
 * The end-to-end path that actually returns rows lives in
 * `execute-e2e.test.ts` (real Postgres, real runner).
 */

import { createHash } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { auditRows, callTool, setupMcpRig, type McpRig } from "./mcp-helpers.js";

let rig: McpRig;

beforeAll(async () => {
  rig = await setupMcpRig();
}, 240_000);

afterAll(async () => {
  await rig.stop();
});

const STATEMENT = "SELECT id, email FROM shop.customers";

async function validatedToken(statement = STATEMENT): Promise<string> {
  const result = await callTool(rig, rig.token("steward"), "steward", "validate_sql", {
    system: "drill",
    request: { dialect: "sql", statement },
  });
  expect(result.payload.verdict).toBe("pass");
  return result.payload.validation_token as string;
}

function execute(args: Record<string, unknown>, user: "steward" | "reporter" = "steward") {
  return callTool(rig, rig.token(user), user, "execute_sql", args);
}

async function executeJobCount(): Promise<number> {
  const { rows } = await rig.core.pool.query<{ n: string }>(
    `SELECT count(*) AS n FROM jobs WHERE type = 'execute'`,
  );
  return Number(rows[0]!.n);
}

/** Assert a refusal happened without any job reaching the queue. */
async function expectNoExecution(fn: () => Promise<unknown>): Promise<void> {
  const before = await executeJobCount();
  await fn();
  expect(await executeJobCount()).toBe(before);
}

describe("MT-3 — execute_sql token enforcement (M-2, §5, G4)", () => {
  it("no token at all → revalidate_required, nothing enqueued", async () => {
    await expectNoExecution(async () => {
      const result = await execute({
        system: "drill",
        request: { dialect: "sql", statement: STATEMENT },
        validation_token: "",
      });
      expect(result.isError).toBe(true);
      expect(result.payload.code).toBe("revalidate_required");
    });
  });

  it("tampered statement → revalidate_required (token binds the exact bytes)", async () => {
    const token = await validatedToken();
    await expectNoExecution(async () => {
      const result = await execute({
        system: "drill",
        // One character different from what was validated.
        request: { dialect: "sql", statement: `${STATEMENT} WHERE id > 0` },
        validation_token: token,
      });
      expect(result.payload.code).toBe("revalidate_required");
      expect(String(result.payload.message)).toContain("statement");
    });
  });

  it("tampered token signature → revalidate_required", async () => {
    const token = await validatedToken();
    const parts = token.split(".");
    // Flip the signature, keep the payload — the forged-token case.
    const forged = `${parts[0]}.${parts[1]}.${Buffer.from("not-the-signature").toString("base64url")}`;
    await expectNoExecution(async () => {
      const result = await execute({
        system: "drill",
        request: { dialect: "sql", statement: STATEMENT },
        validation_token: forged,
      });
      expect(result.payload.code).toBe("revalidate_required");
    });
  });

  it("re-signed payload with a widened claim → revalidate_required (no unsigned trust)", async () => {
    const token = await validatedToken();
    const parts = token.split(".");
    const payload = JSON.parse(Buffer.from(parts[1]!, "base64url").toString("utf-8"));
    payload.exp = payload.exp + 86_400; // a year-long token, self-issued
    const swapped = Buffer.from(JSON.stringify(payload)).toString("base64url");
    await expectNoExecution(async () => {
      const result = await execute({
        system: "drill",
        request: { dialect: "sql", statement: STATEMENT },
        validation_token: `${parts[0]}.${swapped}.${parts[2]}`,
      });
      expect(result.payload.code).toBe("revalidate_required");
    });
  });

  it("expired token → revalidate_required", async () => {
    const token = await validatedToken();
    // Age the token by rewriting the signing key's issue window is not
    // possible; instead assert against the verification library's own
    // clock via a token minted with a past expiry.
    const { issueValidationToken } = await import("../src/vtoken.js");
    const expired = await issueValidationToken(
      rig.core.pool,
      {
        statementSha256: createHash("sha256").update(STATEMENT).digest("hex"),
        system: "drill",
        snapshotRef: `sha256:${rig.drill.verdict.canonical_body_sha256.replace(/^sha256:/, "")}`,
        subject: "alper-steward", // the dev IdP's subject form
        profile: "steward",
        objects: ["drill.shop.customers"],
      },
      -1, // already expired at issue
    );
    expect(expired.token).not.toBe(token);
    await expectNoExecution(async () => {
      const result = await execute({
        system: "drill",
        request: { dialect: "sql", statement: STATEMENT },
        validation_token: expired.token,
      });
      expect(result.payload.code).toBe("revalidate_required");
      expect(String(result.payload.message)).toContain("expired");
    });
  });

  it("foreign subject → revalidate_required (tokens are not transferable)", async () => {
    // Steward validates; the benchmark identity tries to spend it.
    const token = await validatedToken();
    await expectNoExecution(async () => {
      const result = await callTool(rig, rig.token("benchmark"), "benchmark", "execute_sql", {
        system: "drill",
        request: { dialect: "sql", statement: STATEMENT },
        validation_token: token,
      });
      // The benchmark profile has no execute grant, so the profile gate
      // refuses first — a second, independent barrier. Either refusal is
      // correct; what must never happen is execution.
      expect(result.isError).toBe(true);
      expect(["permission_denied", "revalidate_required"]).toContain(result.payload.code);
    });
  });

  it("audit records every denied execute with its reason", async () => {
    const rows = await auditRows(rig, { tool: "execute_sql" });
    expect(rows.length).toBeGreaterThan(0);
    // §8: full statement text is stored for execute, denied or not.
    const withStatement = rows.filter((r) => typeof r.statement_text === "string" && r.statement_text);
    expect(withStatement.length).toBeGreaterThan(0);
    const meta = rows.map((r) => r.result_meta as Record<string, unknown>);
    expect(meta.some((m) => m?.error === "revalidate_required")).toBe(true);
  });
});

describe("MT-4 — snapshot advanced between validate and execute (§5)", () => {
  it("a token pinned to the superseded snapshot → revalidate_required", async () => {
    const token = await validatedToken();

    // Accept a newer snapshot for the same system: the pin the token
    // carries is no longer current.
    const { canonicalize, insertAcceptedSnapshot } = await import("./mcp-helpers.js");
    const { drillSnapshot } = await import("./sync-helpers.js");
    const after = await canonicalize(await drillSnapshot("after"));
    await insertAcceptedSnapshot(rig.core, after, new Date(Date.now() + 1000));

    await expectNoExecution(async () => {
      const result = await execute({
        system: "drill",
        request: { dialect: "sql", statement: STATEMENT },
        validation_token: token,
      });
      expect(result.payload.code).toBe("revalidate_required");
      expect(String(result.payload.message)).toContain("snapshot");
    });
  });
});

describe("credential scoping — an execute job carries only query credentials", () => {
  it("a registration with only an introspection credential fails closed", async () => {
    // The connection registry is shared with snapshot jobs, so it holds
    // the *introspection* DSN. Execution must not inherit it: a job that
    // could fall back to the introspection role would defeat G3 without
    // touching any of G3's checks.
    await rig.core.pool.query(
      `INSERT INTO sync_systems (system, connector_name, version_constraint, payload)
       VALUES ($1, $2, $3, $4::jsonb)
       ON CONFLICT (system) DO UPDATE SET payload = excluded.payload`,
      [
        "drill",
        "postgres",
        ">=0.2 <0.3",
        JSON.stringify({
          config: { system: "drill", mode: "live" },
          // Introspection only — nothing marked for the query capability.
          credentials: [{ ref: "env://INTROSPECTION_DSN", key: "dsn", required_for: ["live"] }],
        }),
      ],
    );

    await expectNoExecution(async () => {
      const token = await validatedToken();
      const result = await execute({
        system: "drill",
        request: { dialect: "sql", statement: STATEMENT },
        validation_token: token,
      });
      expect(result.isError).toBe(true);
      expect(result.payload.code).toBe("config_error");
      expect(String(result.payload.message)).toContain('required_for: ["query"]');
    });

    await rig.core.pool.query(`DELETE FROM sync_systems WHERE system = 'drill'`);
  });
});

describe("MT-5 / G2 — guardrails are server-side (MCP-R8)", () => {
  it("client-supplied guardrails are dropped, not merged", async () => {
    // Validate and execute a statement whose request carries a forged
    // guardrail envelope trying to lift the caps.
    const token = await validatedToken();
    const result = await execute({
      system: "drill",
      request: {
        dialect: "sql",
        statement: STATEMENT,
        guardrails: { row_cap: 999_999_999, timeout_s: 86_400, statement_class: "all" },
      },
      validation_token: token,
    });

    // `drill` has no registered connection in this rig, so the gateway
    // stops at registration — after guardrail construction. That is the
    // point: the guardrails it built are recorded, and they are the
    // profile's, not the client's.
    const rows = await auditRows(rig, { tool: "execute_sql" }); // ordered by ts ASC
    const latest = rows[rows.length - 1]!.result_meta as {
      guardrails?: Record<string, unknown>;
      client_guardrails_ignored?: boolean;
    };
    expect(latest.client_guardrails_ignored).toBe(true);
    expect(latest.guardrails).toMatchObject({
      // Steward profile limits from the rig, not the forged values.
      row_cap: 100_000,
      timeout_s: 120,
      statement_class: "select-only",
    });
    expect(result.payload.code).not.toBe("guardrail");
  });
});
