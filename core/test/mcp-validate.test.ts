/**
 * validate_sql + validation tokens (MCP spec §5/§6.6): MT-3, MT-4, MT-8
 * and MCP-R5/R6/R7 — token issuance at validate and the verification
 * library the CP-6 gateway re-verifies with (enforcement at an executor
 * is CP-6; the binding checks are testable now, and MT-3's "never
 * executes" half holds because execute_sql is profile-denied/stubbed).
 * MCP-R14 (rate limits) lives here on a rig with a tiny validate limit.
 */

import { createHash } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { verifyValidationToken } from "../src/vtoken.js";
import {
  auditRows,
  callTool,
  setupMcpRig,
  type McpRig,
} from "./mcp-helpers.js";

let rig: McpRig;

beforeAll(async () => {
  rig = await setupMcpRig({ limits: { validatePerMin: 20 } });
}, 240_000);

afterAll(async () => {
  await rig.stop();
});

const sha256 = (s: string) => createHash("sha256").update(s).digest("hex");

function validate(user: "reporter" | "steward", statement: string) {
  return callTool(rig, rig.token(user), user === "steward" ? "steward" : "reporter", "validate_sql", {
    system: "drill",
    request: { dialect: "sql", statement },
  });
}

describe("validate_sql — SQL dialect (M-1, §6.6)", () => {
  it("a clean SELECT passes and issues a validation token (MCP-R5 issuance)", async () => {
    const result = await validate("steward", "SELECT id, email FROM shop.customers");
    expect(result.isError).toBe(false);
    expect(result.payload.verdict).toBe("pass");
    expect(typeof result.payload.validation_token).toBe("string");
    expect(typeof result.payload.token_expires_at).toBe("string");
  });

  it("MCP-R6: a two-statement batch is refused — no token", async () => {
    const result = await validate("steward", "SELECT 1; DROP TABLE shop.customers");
    expect(result.payload.verdict).toBe("fail");
    expect(result.payload.validation_token).toBeUndefined();
    const codes = (result.payload.findings as { code: string }[]).map((f) => f.code);
    expect(codes).toContain("multi_statement");
  });

  it("MCP-R7: a CTE-wrapped write is refused by the parser", async () => {
    const result = await validate(
      "steward",
      "WITH x AS (DELETE FROM shop.orders RETURNING id) SELECT count(*) FROM x",
    );
    expect(result.payload.verdict).toBe("fail");
    const codes = (result.payload.findings as { code: string }[]).map((f) => f.code);
    expect(codes).toContain("statement_class");
  });

  it("MCP-R7: FOR UPDATE and side-effecting functions are refused", async () => {
    const locked = await validate("steward", "SELECT id FROM shop.orders FOR UPDATE");
    expect((locked.payload.findings as { code: string }[]).map((f) => f.code)).toContain("locking_clause");
    const fn = await validate("steward", "SELECT pg_read_file('/etc/passwd')");
    expect((fn.payload.findings as { code: string }[]).map((f) => f.code)).toContain("denied_function");
  });

  it("MT-8: a dropped/unknown column fails, citing the object", async () => {
    const result = await validate("steward", "SELECT ghost_column FROM shop.customers");
    expect(result.payload.verdict).toBe("fail");
    const finding = (result.payload.findings as { code: string; ref: string }[])[0]!;
    expect(finding.code).toBe("unknown_column");
    expect(finding.ref).toBe("drill.shop.customers");
  });

  it("M-1: dialect must match the system's class", async () => {
    const wrongForSql = await callTool(rig, rig.token("steward"), "steward", "validate_sql", {
      system: "drill",
      request: { dialect: "api", operation: "runReport", body: {} },
    });
    expect(wrongForSql.payload.code).toBe("invalid_argument");
    const wrongForApi = await callTool(rig, rig.token("steward"), "steward", "validate_sql", {
      system: "ga4",
      request: { dialect: "sql", statement: "SELECT 1" },
    });
    expect(wrongForApi.payload.code).toBe("invalid_argument");
  });
});

describe("validate_sql — API dialect (MT-8, CI-6)", () => {
  it("MT-8: an undocumented GA4 dimension is rejected, citing it", async () => {
    const result = await callTool(rig, rig.token("steward"), "steward", "validate_sql", {
      system: "ga4",
      request: {
        dialect: "api",
        operation: "runReport",
        body: { dimensions: [{ name: "country" }, { name: "notARealDimension" }], metrics: [{ name: "activeUsers" }] },
      },
    });
    expect(result.payload.verdict).toBe("fail");
    const finding = (result.payload.findings as { code: string; ref: string }[])[0]!;
    expect(finding.code).toBe("unknown_dimension");
    expect(finding.ref).toBe("ga4.notARealDimension");
  });

  it("a documented request passes and issues a token", async () => {
    const result = await callTool(rig, rig.token("steward"), "steward", "validate_sql", {
      system: "ga4",
      request: {
        dialect: "api",
        operation: "runReport",
        body: { dimensions: [{ name: "country" }], metrics: [{ name: "activeUsers" }] },
      },
    });
    expect(result.payload.verdict).toBe("pass");
    expect(typeof result.payload.validation_token).toBe("string");
  });

  it("an operation outside the conventions guardrail block is rejected", async () => {
    const result = await callTool(rig, rig.token("steward"), "steward", "validate_sql", {
      system: "ga4",
      request: { dialect: "api", operation: "runRealtimeReport", body: {} },
    });
    expect(result.payload.verdict).toBe("fail");
    expect((result.payload.findings as { code: string }[]).map((f) => f.code)).toContain("unknown_operation");
  });
});

describe("MT-3 / MT-4 / MCP-R5 — the §5 token binding, via the verification library", () => {
  const STATEMENT = "SELECT id, email FROM shop.customers";

  async function issue(): Promise<string> {
    const result = await validate("steward", STATEMENT);
    expect(result.payload.verdict).toBe("pass");
    return result.payload.validation_token as string;
  }

  function expected(overrides: Partial<Parameters<typeof verifyValidationToken>[2]> = {}) {
    return {
      statementSha256: sha256(STATEMENT),
      system: "drill",
      subject: "alper-steward",
      currentSnapshotRef: `sha256:${rig.drill.verdict.canonical_body_sha256}`,
      // Steward sees `**`; the D-71.1 allow-set recheck has its own
      // cases in mcp-visibility.test.ts.
      visible: () => true,
      ...overrides,
    };
  }

  it("a fresh token verifies against the exact statement, subject, system, and snapshot", async () => {
    const verdict = await verifyValidationToken(rig.core.pool, await issue(), expected());
    expect(verdict.ok).toBe(true);
  });

  it("MT-3: a tampered statement → revalidate_required (hash binding)", async () => {
    const verdict = await verifyValidationToken(
      rig.core.pool,
      await issue(),
      expected({ statementSha256: sha256("SELECT id, email FROM shop.customers -- smuggled") }),
    );
    expect(verdict).toMatchObject({ ok: false, code: "revalidate_required" });
  });

  it("MT-3: a different subject → revalidate_required (not transferable)", async () => {
    const verdict = await verifyValidationToken(
      rig.core.pool,
      await issue(),
      expected({ subject: "rene-reporter" }),
    );
    expect(verdict).toMatchObject({ ok: false, code: "revalidate_required" });
  });

  it("MT-3: an expired token → revalidate_required (300 s TTL, MC-2)", async () => {
    const token = await issue();
    const verdict = await verifyValidationToken(rig.core.pool, token, expected(), Date.now() + 301_000);
    expect(verdict).toMatchObject({ ok: false, code: "revalidate_required" });
  });

  it("MT-3: a forged signature → revalidate_required", async () => {
    const token = await issue();
    const parts = token.split(".");
    const forged = `${parts[0]}.${parts[1]}.${Buffer.from("forged-signature-bytes-here-1234").toString("base64url")}`;
    const verdict = await verifyValidationToken(rig.core.pool, forged, expected());
    expect(verdict).toMatchObject({ ok: false, code: "revalidate_required" });
  });

  it("MT-4: a snapshot accepted after validation → revalidate_required", async () => {
    const verdict = await verifyValidationToken(
      rig.core.pool,
      await issue(),
      expected({ currentSnapshotRef: "sha256:different-snapshot-now" }),
    );
    expect(verdict).toMatchObject({ ok: false, code: "revalidate_required" });
  });

  it("MT-3: the reporter passes the profile gate on execute (CP-6 grant); token binding still holds", async () => {
    // Execution was granted to the reporter at CP-6/M2, so the profile
    // gate now opens for it exactly as for the steward. The token still
    // binds the exact statement, so this empty request — which does not
    // match the token issued by `issue()` — is turned away at the token
    // layer, not the permission layer. `permission_denied` here would mean
    // the fixture reporter had drifted back to its M1 read-only shape.
    const reporter = await callTool(rig, rig.token("reporter"), "reporter", "execute_sql", {
      system: "drill",
      request: {},
      validation_token: await issue(),
    });
    expect(reporter.payload.code).not.toBe("permission_denied");
    expect(reporter.payload.code).toBe("revalidate_required");
  });
});

describe("MCP-R14 — per-identity rate limits (§7)", () => {
  it("exceeding the validate limit → rate_limited, audited as denied", async () => {
    // The rig caps validate at 20/min per identity; the reporter has
    // spent none — burn the budget and hit the wall.
    let last: Awaited<ReturnType<typeof callTool>> | null = null;
    for (let i = 0; i < 22; i += 1) {
      last = await callTool(rig, rig.token("reporter"), "reporter", "validate_sql", {
        system: "drill",
        request: { dialect: "sql", statement: "SELECT id FROM shop.customers" },
      });
      if (last.isError && last.payload.code === "rate_limited") break;
    }
    expect(last!.payload.code).toBe("rate_limited");
    expect(typeof last!.payload.retry_after_s).toBe("number");
    const denied = await auditRows(rig, { tool: "validate_sql", decision: "denied" });
    expect(denied.at(-1)!.decision_reason).toBe("rate_limited");
  });
});
