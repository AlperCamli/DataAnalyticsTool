/**
 * MT-11 / MT-12 / MT-13 — the M-4 visibility map governs the execution
 * surface (D-71.1, security review #2 F2; MCP spec §3, §5 and §6.6
 * amendments).
 *
 * The property under test is not "hidden objects are refused" — that
 * would be satisfied by a `permission_denied` that announces what it is
 * protecting. It is that a caller **cannot tell the difference** between
 * an object hidden from them and one that was never there, while the
 * audit record can. So most assertions here are comparisons between two
 * responses rather than checks on one: hidden-vs-absent, and
 * restricted-vs-steward on the identical statement.
 *
 * `restricted` (oidc group `salesonly`, Reporter profile) can see
 * `systems/drill/shop/**` and nothing under `systems/drill/reporting/**`
 * or `systems/ga4/**` — the rig's roles.yaml, unchanged for these tests.
 */

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { auditRows, callTool, setupMcpRig, USERS, type McpRig, type ToolResult } from "./mcp-helpers.js";

let rig: McpRig;

beforeAll(async () => {
  rig = await setupMcpRig();
}, 240_000);

afterAll(async () => {
  await rig.stop();
});

interface Finding {
  severity: string;
  code: string;
  ref: string | null;
  message: string;
}

const findings = (result: ToolResult): Finding[] => (result.payload.findings as Finding[]) ?? [];

function validateSql(user: keyof typeof USERS, profile: string, statement: string): Promise<ToolResult> {
  return callTool(rig, rig.token(user), profile, "validate_sql", {
    system: "drill",
    request: { dialect: "sql", statement },
  });
}

function validateApi(user: keyof typeof USERS, profile: string, body: Record<string, unknown>): Promise<ToolResult> {
  return callTool(rig, rig.token(user), profile, "validate_sql", {
    system: "ga4",
    request: { dialect: "api", operation: "runReport", body },
  });
}

/** The rig's KB is a real repo; the map is a file in it (kbRefreshMs: 0). */
async function rewriteRolesYaml(edit: (yaml: string) => string, message: string): Promise<void> {
  const file = path.join(rig.kb.seedClone, ".contextlayer", "roles.yaml");
  await writeFile(file, edit(await readFile(file, "utf-8")));
  rig.kb.commitAll(message);
}

// ---------------------------------------------------------------------------

describe("MT-11 — validate_sql resolves against the caller's visible surface (§6.6)", () => {
  const HIDDEN = "SELECT customer_id, net_total FROM reporting.v_net_sales";

  it("a hidden table is refused, with no token issued", async () => {
    const result = await validateSql("restricted", "reporter", HIDDEN);
    expect(result.payload.verdict).toBe("fail");
    expect(result.payload.validation_token).toBeUndefined();
    expect(findings(result).map((f) => f.code)).toEqual(["unknown_object"]);
    expect(findings(result)[0]!.ref).toBe("drill.reporting.v_net_sales");
  });

  it("the refusal is indistinguishable from the object not existing (M-4)", async () => {
    // Same schema, same statement shape: one object exists but is hidden,
    // the other never existed. If any byte of the caller-visible response
    // differs beyond the name they themselves typed, this is an
    // enumeration oracle.
    const hidden = await validateSql("restricted", "reporter", HIDDEN);
    const absent = await validateSql(
      "restricted",
      "reporter",
      "SELECT customer_id, net_total FROM reporting.v_net_sales_absent",
    );

    const normalize = (result: ToolResult): unknown =>
      JSON.parse(
        JSON.stringify({ ...result.payload, refs: undefined }).replaceAll("v_net_sales_absent", "v_net_sales"),
      );

    expect(normalize(absent)).toEqual(normalize(hidden));
    expect(absent.isError).toBe(hidden.isError);
  });

  it("the identical statement from a caller who can see the table passes", async () => {
    const result = await validateSql("steward", "steward", HIDDEN);
    expect(result.payload.verdict).toBe("pass");
    expect(typeof result.payload.validation_token).toBe("string");
    expect(findings(result)).toEqual([]);
  });

  it("the audit records the true reason the caller was not given (M-4, M-8)", async () => {
    await validateSql("restricted", "reporter", HIDDEN);
    const filtered = (await auditRows(rig, { tool: "validate_sql", decision: "filtered" })).at(-1);
    expect(filtered).toBeDefined();
    const meta = filtered!.result_meta as { hidden_objects?: string[] };
    expect(meta.hidden_objects).toContain("drill.reporting.v_net_sales");
    expect(String(filtered!.decision_reason)).toContain("visibility map");
  });
});

describe("MT-12 — partial and API-dialect refusals (§6.6)", () => {
  it("a JOIN is refused when only one side is hidden, with no hint the rest was fine", async () => {
    const result = await validateSql(
      "restricted",
      "reporter",
      "SELECT c.id, n.net_total FROM shop.customers c " +
        "JOIN reporting.v_net_sales n ON n.customer_id = c.id",
    );
    expect(result.payload.verdict).toBe("fail");
    expect(result.payload.validation_token).toBeUndefined();
    expect(findings(result).map((f) => f.ref)).toEqual(["drill.reporting.v_net_sales"]);
    // The visible half is not reported as validated, not reported at all.
    expect(JSON.stringify(result.payload)).not.toContain("shop.customers");
  });

  it("the same JOIN passes for a caller who can see both sides", async () => {
    const result = await validateSql(
      "steward",
      "steward",
      "SELECT c.id, n.net_total FROM shop.customers c " +
        "JOIN reporting.v_net_sales n ON n.customer_id = c.id",
    );
    expect(result.payload.verdict).toBe("pass");
  });

  it("a hidden GA4 custom dimension is refused in the words an undocumented one gets", async () => {
    const hidden = await validateApi("restricted", "reporter", {
      dimensions: ["customEvent:plan_tier"],
      metrics: ["activeUsers"],
    });
    expect(hidden.payload.verdict).toBe("fail");
    expect(hidden.payload.validation_token).toBeUndefined();
    expect(findings(hidden).map((f) => f.code)).toContain("unknown_dimension");

    const undocumented = await validateApi("restricted", "reporter", {
      dimensions: ["customEvent:not_a_real_dimension"],
      metrics: ["activeUsers"],
    });
    const shape = (result: ToolResult, name: string) =>
      findings(result)
        .filter((f) => f.code === "unknown_dimension")
        .map((f) => ({ ...f, ref: f.ref?.replace(name, "X"), message: f.message.replace(name, "X") }));
    expect(shape(hidden, "customEvent:plan_tier")).toEqual(
      shape(undocumented, "customEvent:not_a_real_dimension"),
    );
  });

  it("the same GA4 request passes for a caller who can see the dimension", async () => {
    const result = await validateApi("steward", "steward", {
      dimensions: ["customEvent:plan_tier"],
      metrics: ["activeUsers"],
    });
    expect(result.payload.verdict).toBe("pass");
    expect(typeof result.payload.validation_token).toBe("string");
  });

  it("the API refusal is audited as filtered with the true reason", async () => {
    // Its own call, so the row asserted on is unambiguously this one.
    await validateApi("restricted", "reporter", { dimensions: ["customEvent:plan_tier"], metrics: [] });
    const filtered = (await auditRows(rig, { tool: "validate_sql", decision: "filtered" })).at(-1);
    const meta = filtered!.result_meta as { system?: string; hidden_objects?: string[] };
    expect(meta.system).toBe("ga4");
    expect(meta.hidden_objects).toEqual(["ga4.custom.customEvent:plan_tier"]);
  });
});

describe("MT-13 — the allow-set carries the decision to execute (§5)", () => {
  async function executeJobCount(): Promise<number> {
    const { rows } = await rig.core.pool.query<{ n: string }>(
      `SELECT count(*) AS n FROM jobs WHERE type = 'execute'`,
    );
    return Number(rows[0]!.n);
  }

  it("a token minted while the object was visible is refused once the map hides it", async () => {
    const statement = "SELECT customer_id, net_total FROM reporting.v_net_sales";

    // 1. Steward validates while `visibility: ["**"]` still holds.
    const validated = await validateSql("steward", "steward", statement);
    expect(validated.payload.verdict).toBe("pass");
    const token = validated.payload.validation_token as string;

    // 2. The map changes underneath the token — the snapshot does not.
    //    This is the point of the case: every §5 binding except the
    //    allow-set still verifies, `snapshot_ref` included.
    const snapshotBefore = await rig.core.pool.query<{ canonical_body_sha256: string }>(
      `SELECT canonical_body_sha256 FROM accepted_snapshots WHERE system = 'drill'
        ORDER BY accepted_at DESC`,
    );
    await rewriteRolesYaml(
      (yaml) =>
        yaml.replace(
          `  R2:
    profile: steward
    oidc_group: steward
    visibility: ["**"]`,
          `  R2:
    profile: steward
    oidc_group: steward
    visibility:
      - index.md
      - conventions.md
      - systems/drill/index.md
      - systems/drill/shop/**`,
        ),
      "revoke steward visibility of drill.reporting",
    );

    try {
      const before = await executeJobCount();
      const result = await callTool(rig, rig.token("steward"), "steward", "execute_sql", {
        system: "drill",
        request: { dialect: "sql", statement },
        validation_token: token,
      });

      // Refused as not_found — validation's words, per M-4 — and before
      // anything was enqueued.
      expect(result.isError).toBe(true);
      expect(result.payload.code).toBe("not_found");
      expect(String(result.payload.message)).toContain("does not exist in the latest accepted snapshot");
      expect(await executeJobCount()).toBe(before);

      // The response must not name what was hidden or why.
      expect(JSON.stringify(result.payload)).not.toContain("visibility");
      expect(JSON.stringify(result.payload)).not.toContain("hidden");

      // The snapshot never moved: `snapshot_ref` cannot have been what
      // caught this. The allow-set recheck is the only mechanism left.
      const snapshotAfter = await rig.core.pool.query<{ canonical_body_sha256: string }>(
        `SELECT canonical_body_sha256 FROM accepted_snapshots WHERE system = 'drill'
        ORDER BY accepted_at DESC`,
      );
      expect(snapshotAfter.rows).toEqual(snapshotBefore.rows);

      // The audit carries the true reason (M-4's second half).
      const filtered = (await auditRows(rig, { tool: "execute_sql", decision: "filtered" })).at(-1);
      expect(filtered).toBeDefined();
      const meta = filtered!.result_meta as { hidden_objects?: string[]; stage?: string };
      expect(meta.stage).toBe("visibility");
      expect(meta.hidden_objects).toContain("drill.reporting.v_net_sales");
    } finally {
      await rewriteRolesYaml(
        (yaml) =>
          yaml.replace(
            `  R2:
    profile: steward
    oidc_group: steward
    visibility:
      - index.md
      - conventions.md
      - systems/drill/index.md
      - systems/drill/shop/**`,
            `  R2:
    profile: steward
    oidc_group: steward
    visibility: ["**"]`,
          ),
        "restore steward visibility",
      );
    }
  });

  it("a statement over still-visible objects gets past the check (it is not a blanket refusal)", async () => {
    // Control: the recheck must not refuse everything, or the case above
    // proves nothing. `shop.customers` stays visible to the steward, so
    // this token clears the allow-set and the call dies *later* — at the
    // connection registry, which this rig deliberately leaves empty.
    // Different stage, different code: that is the discrimination under
    // test, and it needs no runner to show.
    const statement = "SELECT id, email FROM shop.customers";
    const validated = await validateSql("steward", "steward", statement);
    expect(validated.payload.verdict).toBe("pass");

    const result = await callTool(rig, rig.token("steward"), "steward", "execute_sql", {
      system: "drill",
      request: { dialect: "sql", statement },
      validation_token: validated.payload.validation_token as string,
    });
    expect(result.payload.code).toBe("config_error");
    expect(result.payload.code).not.toBe("not_found");
    const last = (await auditRows(rig, { tool: "execute_sql" })).at(-1);
    expect(last!.decision).toBe("allowed");
  });

  it("a token carrying no allow-set is not honoured (fail closed)", async () => {
    const statement = "SELECT id, email FROM shop.customers";
    const { createHash, createHmac } = await import("node:crypto");

    // A pre-amendment token, minted the way the old issuer did: every §5
    // binding correct and *properly signed with the live key*, carrying
    // no `objects` claim. Signed here rather than issued through
    // vtoken.ts so the issuer keeps the claim mandatory.
    const { rows } = await rig.core.pool.query<{ kid: string; secret: string }>(
      `SELECT kid, secret FROM signing_keys WHERE active ORDER BY created_at DESC LIMIT 1`,
    );
    const key = rows[0]!;
    const iat = Math.floor(Date.now() / 1000);
    const b64 = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64url");
    const header = b64({ alg: "HS256", kid: key.kid });
    const body = b64({
      v: 1,
      statement_sha256: createHash("sha256").update(statement).digest("hex"),
      system: "drill",
      snapshot_ref: `sha256:${rig.drill.verdict.canonical_body_sha256.replace(/^sha256:/, "")}`,
      subject: "alper-steward",
      profile: "steward",
      iat,
      exp: iat + 300,
    });
    const signature = createHmac("sha256", key.secret).update(`${header}.${body}`).digest("base64url");

    const before = await executeJobCount();
    const result = await callTool(rig, rig.token("steward"), "steward", "execute_sql", {
      system: "drill",
      request: { dialect: "sql", statement },
      validation_token: `${header}.${body}.${signature}`,
    });
    expect(result.payload.code).toBe("revalidate_required");
    expect(String(result.payload.message)).toContain("allow-set");
    expect(await executeJobCount()).toBe(before);
  });
});
