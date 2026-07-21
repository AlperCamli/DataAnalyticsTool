/**
 * CP-5 baseline v1, the `no-kb` condition (ruling D-74.4b/4c).
 *
 * The condition is realized as a core instance whose KB is a scratch repo
 * holding **only profile files**, served to a profile granting validate +
 * execute and no content tools. Two properties have to hold, and the
 * second is the dangerous one:
 *
 * 1. The condition still validates. D-71.1 made `validate_sql`
 *    visibility-governed, and the validation surface comes from the
 *    accepted snapshots in ops Postgres — *not* from the KB repo — so a
 *    content-free KB does not starve it. With no `roles.yaml` committed,
 *    the visibility map is absent and the full surface is visible.
 *
 * 2. If it ever stops validating, the operator can tell. A `roles.yaml`
 *    present with no entry for the condition's role yields **nothing
 *    visible**, and every statement is refused with the ordinary "no such
 *    object" finding — deliberately indistinguishable from absence, to
 *    the caller. That would silently destroy the condition: the baseline
 *    would record a no-kb agent that cannot write valid SQL, which is
 *    exactly the headline number the experiment exists to produce
 *    honestly. The audit record is the operator's tell, and this suite
 *    asserts it fires.
 */

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { auditRows, callTool, listTools, setupMcpRig, type McpRig } from "./mcp-helpers.js";

const CUSTOMERS_QUERY = "SELECT id FROM shop.customers LIMIT 10";

describe("no-kb condition: scratch KB with no roles.yaml", () => {
  let rig: McpRig;

  beforeAll(async () => {
    rig = await setupMcpRig({ rolesYaml: null });
  }, 120_000);

  afterAll(async () => {
    await rig?.stop();
  });

  it("validates a statement against a example estate table (D-74.4b)", async () => {
    const res = await callTool(rig, rig.token("nokb"), "nokb", "validate_sql", {
      system: "drill",
      request: { dialect: "sql", statement: CUSTOMERS_QUERY },
    });

    expect(res.isError).toBe(false);
    expect(res.payload.verdict).toBe("pass");
    // A pass issues the token; without it execution is impossible (M-2),
    // so "validates" and "can run the condition" are the same claim.
    expect(typeof res.payload.validation_token).toBe("string");
  });

  it("serves no content tools — the condition is live discovery only", async () => {
    // Hidden from tools/list, and denied on direct call anyway (M-3):
    // the condition's boundary does not depend on the client behaving.
    const listed = await listTools(rig, rig.token("nokb"), "nokb");
    expect(listed.names).not.toContain("get_table");
    expect(listed.names).toContain("validate_sql");

    const res = await callTool(rig, rig.token("nokb"), "nokb", "get_table", {
      fqn: "drill.shop.customers",
    });
    // Denied by the profile allowlist, not by visibility — a tool-level
    // error on a 200, which is how the MCP surface reports refusals.
    expect(res.isError).toBe(true);
    expect(res.payload.code).toBe("permission_denied");
  });

  it("records no visibility filtering, because there is no map to filter by", async () => {
    await callTool(rig, rig.token("nokb"), "nokb", "validate_sql", {
      system: "drill",
      request: { dialect: "sql", statement: CUSTOMERS_QUERY },
    });
    const rows = await auditRows(rig, { tool: "validate_sql" });
    const filtered = rows.filter((r) => r.decision === "filtered");
    expect(filtered).toHaveLength(0);
  });
});

describe("no-kb condition: a roles.yaml without an entry for the role", () => {
  let rig: McpRig;

  // A map that covers the suite's other roles but says nothing about
  // `nokb` — the realistic mistake, since it is what copying the
  // production map into the scratch repo would produce.
  const MAP_WITHOUT_NOKB = `roles:
  R1:
    profile: reporter
    oidc_group: reporter
    visibility: ["**"]
`;

  beforeAll(async () => {
    rig = await setupMcpRig({ rolesYaml: MAP_WITHOUT_NOKB });
  }, 120_000);

  afterAll(async () => {
    await rig?.stop();
  });

  it("refuses the statement, and the caller cannot tell hidden from absent (D-71.1)", async () => {
    const res = await callTool(rig, rig.token("nokb"), "nokb", "validate_sql", {
      system: "drill",
      request: { dialect: "sql", statement: CUSTOMERS_QUERY },
    });

    expect(res.payload.verdict).toBe("fail");
    // The response carries the ordinary unresolved-object finding and no
    // hint that a visibility map was involved — that is the D-71.1 design,
    // and it is precisely why the operator needs the audit signal below.
    expect(JSON.stringify(res.payload)).not.toMatch(/hidden|visibility/i);
    expect(res.payload.validation_token).toBeUndefined();
  });

  it("fires a named, operator-visible signal in the audit — never silent attrition", async () => {
    await callTool(rig, rig.token("nokb"), "nokb", "validate_sql", {
      system: "drill",
      request: { dialect: "sql", statement: CUSTOMERS_QUERY },
    });

    const rows = await auditRows(rig, { tool: "validate_sql" });
    const filtered = rows.filter((r) => r.decision === "filtered");
    expect(filtered.length).toBeGreaterThan(0);

    // The record names the objects that were hidden, so a baseline run
    // that quietly scores zero can be diagnosed rather than believed.
    const meta = filtered[0].result_meta as { hidden_objects?: string[] };
    expect(meta.hidden_objects ?? []).toContain("drill.shop.customers");
    expect(filtered[0].decision_reason).toMatch(/visibility/i);
  });
});
