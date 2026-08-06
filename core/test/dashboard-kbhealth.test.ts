/**
 * B-1 KB Health: the freshness map, doc-status counts, the contaminated
 * set with its lineage paths, the drift-PR queue, and the lineage
 * explorer's read view (dashboard spec §3, DT-9, §7.3).
 *
 * The load-bearing tests here are the two that assert *absences*: DT-9's
 * configured-but-disabled state must be reported rather than looking
 * like a healthy estate, and §7.3's no-merge rule must hold as a
 * property of the code rather than as an absent button.
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { apiGet, login, setupDashboardRig, type BrowserSession, type DashboardRig } from "./dashboard-helpers.js";
import { callTool } from "./mcp-helpers.js";

const CORE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** A policy for the scratch KB's two systems, with a threshold `drill`'s
 * fixture snapshot is comfortably inside and `ga4`'s is not. */
const SYNC_POLICY = `systems:
  drill:
    freshness_threshold: 30d
    triggers:
      schedule: 1h
  ga4:
    freshness_threshold: 1s
    triggers:
      manual: true
`;

interface KbHealthBody {
  kb: { ref: string; render_failed: boolean };
  sync: {
    enabled: boolean;
    configured_systems: number;
    policy_readable: boolean;
    configured_but_disabled: boolean;
  };
  sources: {
    system: string;
    in_policy: boolean;
    age_s: number | null;
    threshold_s: number | null;
    stale: boolean;
    trigger_mode: string | null;
  }[];
  docs: { counts: Record<string, number>; total: number; scope_note: string };
  contamination: {
    doc: string;
    source_object: string | null;
    change: string | null;
    path: string[] | null;
    path_source: string;
  }[];
  drift_prs: { available: boolean; reason: string | null; prs: { number: number; title: string }[] };
}

describe("B-1 KB Health (§3)", () => {
  let rig: DashboardRig;
  let steward: BrowserSession;
  let reporter: BrowserSession;

  beforeAll(async () => {
    rig = await setupDashboardRig();
    // The estate is *configured* to sync: a policy at HEAD naming both
    // systems. Whether the engine is on is the other half, and DT-9 is
    // about the gap between them.
    await writeFile(path.join(rig.kb.seedClone, ".contextlayer", "sync-policy.yaml"), SYNC_POLICY);
    rig.kb.commitAll("b-1: sync policy");
    steward = await login(rig, "steward");
    reporter = await login(rig, "reporter");
  }, 240_000);

  afterAll(async () => {
    await rig?.stop();
  });

  const health = async (session: BrowserSession): Promise<KbHealthBody> => {
    const res = await apiGet(rig, session, "/v1/dashboard/kb-health");
    expect(res.status).toBe(200);
    return res.json as unknown as KbHealthBody;
  };

  // -- freshness -------------------------------------------------------------

  it("maps every source against the policy at HEAD, and says which are stale", async () => {
    const body = await health(steward);
    const bySystem = Object.fromEntries(body.sources.map((s) => [s.system, s]));

    // A 30d threshold the fixture snapshot is inside.
    expect(bySystem.drill!.in_policy).toBe(true);
    expect(bySystem.drill!.threshold_s).toBe(30 * 86400);
    expect(bySystem.drill!.trigger_mode).toBe("schedule");
    expect(bySystem.drill!.stale).toBe(false);

    // A 1s threshold nothing can be inside — the stale verdict, computed
    // server-side against the policy rather than eyeballed from a date.
    expect(bySystem.ga4!.stale).toBe(true);
    expect(bySystem.ga4!.threshold_s).toBe(1);
    expect(bySystem.ga4!.trigger_mode).toBe("manual");
    expect(bySystem.ga4!.age_s).toBeGreaterThan(1);
  });

  it("a source outside sync-policy.yaml is reported as not-a-sync-source, never as fresh", async () => {
    // The B-2 health-model correction, carried here: freshness is not a
    // publish target's verdict, and calling it green would be a claim
    // about a snapshot that is not expected to exist.
    await writeFile(
      path.join(rig.kb.seedClone, ".contextlayer", "sync-policy.yaml"),
      `systems:\n  drill:\n    freshness_threshold: 30d\n    triggers:\n      schedule: 1h\n`,
    );
    rig.kb.commitAll("b-1: policy without ga4");

    const body = await health(steward);
    const ga4 = body.sources.find((s) => s.system === "ga4")!;
    expect(ga4.in_policy).toBe(false);
    expect(ga4.threshold_s).toBeNull();
    // Not stale, because staleness is measured against a threshold and
    // this source has none — a different answer from "fresh".
    expect(ga4.stale).toBe(false);

    await writeFile(path.join(rig.kb.seedClone, ".contextlayer", "sync-policy.yaml"), SYNC_POLICY);
    rig.kb.commitAll("b-1: restore policy");
  });

  it("a policy that does not parse is reported as unreadable, not as no-thresholds", async () => {
    await writeFile(
      path.join(rig.kb.seedClone, ".contextlayer", "sync-policy.yaml"),
      "systems: [this is a list, not a map]\n",
    );
    rig.kb.commitAll("b-1: broken policy");

    const body = await health(steward);
    expect(body.sync.policy_readable).toBe(false);
    // The distinction that matters: "nothing is configured" and "the
    // configuration is broken" are different diagnoses.
    expect(body.sync.configured_systems).toBe(0);
    expect(body.sources.every((s) => !s.in_policy)).toBe(true);

    await writeFile(path.join(rig.kb.seedClone, ".contextlayer", "sync-policy.yaml"), SYNC_POLICY);
    rig.kb.commitAll("b-1: restore policy again");
  });

  // -- DT-9 ------------------------------------------------------------------

  describe("DT-9: sync configured but disabled (SO-F, the two-silent-days shape)", () => {
    it("renders the warning state, and reports the same value /healthz does", async () => {
      // Enabled: the estate is configured and the engine runs, so there
      // is nothing to warn about.
      expect(rig.core.cfg.sync.enabled).toBe(true);
      const on = await health(steward);
      expect(on.sync.enabled).toBe(true);
      expect(on.sync.configured_systems).toBe(2);
      expect(on.sync.configured_but_disabled).toBe(false);

      const healthzOn = (await (await fetch(`${rig.base}/healthz`)).json()) as {
        instance: { sync_enabled: boolean };
      };
      // D-114.3: one value, two renderings. If these could differ, the
      // dashboard would be a second source for a fact /healthz owns.
      expect(healthzOn.instance.sync_enabled).toBe(on.sync.enabled);

      // Disabled with the policy still at HEAD: the failure shape. No
      // trigger will fire and every threshold above will be crossed in
      // silence — which is exactly what cost two days once.
      rig.core.cfg.sync.enabled = false;
      try {
        const off = await health(steward);
        expect(off.sync.enabled).toBe(false);
        expect(off.sync.configured_systems).toBe(2);
        expect(off.sync.configured_but_disabled).toBe(true);

        const healthzOff = (await (await fetch(`${rig.base}/healthz`)).json()) as {
          instance: { sync_enabled: boolean };
        };
        expect(healthzOff.instance.sync_enabled).toBe(false);
        expect(healthzOff.instance.sync_enabled).toBe(off.sync.enabled);

        // And the drift queue says it is *unknown*, not empty: with the
        // engine off, "no open PRs" would be a claim nothing checked.
        expect(off.drift_prs.available).toBe(false);
        expect(off.drift_prs.reason).toBeTruthy();
        expect(off.drift_prs.prs).toEqual([]);
      } finally {
        rig.core.cfg.sync.enabled = true;
      }
    });

    it("a configured-but-disabled state needs a policy to be about", async () => {
      // Sync off and nothing configured is a deployment that does not
      // sync, which is not a fault and must not raise the warning.
      const stashed = await readFile(
        path.join(rig.kb.seedClone, ".contextlayer", "sync-policy.yaml"),
        "utf-8",
      );
      execFileSync("git", ["rm", "-q", ".contextlayer/sync-policy.yaml"], { cwd: rig.kb.seedClone });
      rig.kb.commitAll("b-1: no policy");
      rig.core.cfg.sync.enabled = false;
      try {
        const body = await health(steward);
        expect(body.sync.configured_systems).toBe(0);
        expect(body.sync.configured_but_disabled).toBe(false);
      } finally {
        rig.core.cfg.sync.enabled = true;
        await writeFile(path.join(rig.kb.seedClone, ".contextlayer", "sync-policy.yaml"), stashed);
        rig.kb.commitAll("b-1: policy back");
      }
    });
  });

  // -- doc status ------------------------------------------------------------

  it("counts doc status over the docs this caller can see, and says the count is theirs", async () => {
    const asSteward = await health(steward);
    expect(asSteward.docs.total).toBeGreaterThan(0);
    expect(asSteward.docs.counts.contaminated).toBeGreaterThanOrEqual(1);
    expect(asSteward.docs.scope_note).toContain("your roles can see");

    // M-4 consistently applied: a narrower role legitimately reads a
    // smaller total, and each total is true for its reader. The counts
    // are not zeroed for hidden docs — the docs are absent.
    const restricted = await login(rig, "restricted");
    const theirs = await health(restricted);
    expect(theirs.docs.total).toBeLessThan(asSteward.docs.total);
  });

  it("agrees with the report_freshness tool, because both call one computation (D-114.2)", async () => {
    const body = await health(steward);
    const tool = await callTool(rig, rig.token("steward"), "steward", "report_freshness", {});
    expect(tool.isError).toBe(false);

    const toolCounts = tool.payload.doc_status_counts as Record<string, number>;
    expect(toolCounts).toEqual(body.docs.counts);

    const toolSystems = tool.payload.systems as { system: string; freshness_threshold: number | null }[];
    for (const row of toolSystems) {
      const mine = body.sources.find((s) => s.system === row.system)!;
      expect(mine.threshold_s).toBe(row.freshness_threshold);
    }
  });

  // -- contamination ---------------------------------------------------------

  it("lists contaminated docs with how the contamination reached them", async () => {
    const body = await health(steward);
    expect(body.contamination.length).toBeGreaterThanOrEqual(1);
    const legacy = body.contamination.find((c) => c.doc.includes("legacy_sessions"))!;
    expect(legacy).toBeDefined();
    expect(legacy.source_object).toBe("drill.shop.legacy_sessions");
    expect(legacy.change).toBe("removed");
    // The fixture's contaminating object is the doc's own subject, so
    // the path is a self-hop and says so rather than claiming a chain.
    expect(legacy.path_source).toBe("self");
    expect(legacy.path).toEqual(["drill.shop.legacy_sessions"]);
  });

  it("a path the KB cannot establish is null, never an empty list", async () => {
    // An empty list reads as "no hops"; null reads as "unknown", and the
    // difference is a triage fact — a doc contaminated by something it
    // never declared is worth looking at for that reason alone.
    const docPath = path.join(rig.kb.seedClone, "systems", "drill", "shop", "order_items.md");
    const original = await readFile(docPath, "utf-8");
    await writeFile(
      docPath,
      original
        .replace(/^status: .*$/m, "status: contaminated")
        .replace(
          /^contamination: .*$/m,
          'contamination: { object: "drill.shop.nowhere_at_all", change: "removed", detail: "undeclared" }',
        ),
    );
    rig.kb.commitAll("b-1: contamination with no declared path");
    try {
      const body = await health(steward);
      const row = body.contamination.find((c) => c.doc.includes("order_items.md"))!;
      expect(row).toBeDefined();
      expect(row.path).toBeNull();
      expect(row.path_source).toBe("unknown");
    } finally {
      await writeFile(docPath, original);
      rig.kb.commitAll("b-1: restore orders");
    }
  });

  // -- DT-3 ------------------------------------------------------------------

  it("DT-3: a payload in an object name renders inert on this screen", async () => {
    // The F4 lesson: object names are attacker-influenceable, and this
    // screen prints them beside doc paths and change reasons.
    const docPath = path.join(rig.kb.seedClone, "systems", "drill", "shop", "customers.md");
    const original = await readFile(docPath, "utf-8");
    await writeFile(
      docPath,
      original
        .replace(/^status: .*$/m, "status: contaminated")
        .replace(
          /^contamination: .*$/m,
          'contamination: { object: "<script>alert(1)</script>", change: "**bold**", detail: "[x](http://evil.example)" }',
        ),
    );
    rig.kb.commitAll("b-1: nasty contamination payload");
    try {
      const body = await health(steward);
      const row = body.contamination.find((c) => c.doc.includes("customers.md"))!;
      expect(row.source_object).not.toContain("<script");
      expect(row.source_object).toContain("&lt;script");
      expect(row.change).not.toContain("**");
      expect(row.detail).not.toContain("](");
    } finally {
      await writeFile(docPath, original);
      rig.kb.commitAll("b-1: restore customers");
    }
  });

  // -- drift PRs -------------------------------------------------------------

  it("routes drift PRs to the provider and offers no way to merge one (§7.3)", async () => {
    const body = await health(steward);
    expect(body.drift_prs.available).toBe(true);
    for (const pr of body.drift_prs.prs) {
      expect(typeof pr.number).toBe("number");
    }

    // The absence, asserted as a property of the code rather than of a
    // rendering: no dashboard route mutates a PR, and the shipped bundle
    // holds no path that could reach one. A merge button is not the
    // risk — a code path is (UI-6, D-114.4).
    const serverSources = ["kbhealth.ts", "dashboard.ts", "ops.ts", "connections.ts", "spa.ts"]
      .map((f) => readFileSync(path.join(CORE_DIR, "src", f), "utf-8"))
      .join("\n");
    for (const forbidden of ["mergePr", "merge_method", "closePr(", "listMergedPrs("]) {
      expect(serverSources).not.toContain(forbidden);
    }

    const bundle = readFileSync(path.join(CORE_DIR, "web", "dist", "app.js"), "utf-8");
    for (const forbidden of ["/merge", "merge_method", "mergePr"]) {
      expect(bundle).not.toContain(forbidden);
    }
  });

  // -- lineage explorer (U-15) ----------------------------------------------

  it("serves the lineage graph as a read view, node-by-node visibility filtered", async () => {
    const mine = await apiGet(rig, steward, "/v1/dashboard/lineage");
    expect(mine.status).toBe(200);
    const graph = mine.json as unknown as {
      available: boolean;
      nodes: { id: string; status: string | null }[];
      edges: { source: string; target: string }[];
    };
    expect(graph.available).toBe(true);
    expect(graph.nodes.length).toBeGreaterThan(0);

    // MCP-R11: a hidden node is omitted and so is every edge touching
    // it — filtering edges alone would leak the hidden node's name
    // through the endpoints of the edges that survived.
    const restricted = await login(rig, "restricted");
    const theirs = await apiGet(rig, restricted, "/v1/dashboard/lineage");
    expect(theirs.status).toBe(200);
    const narrow = theirs.json as unknown as {
      nodes: { id: string }[];
      edges: { source: string; target: string }[];
    };
    const visible = new Set(narrow.nodes.map((n) => n.id));
    for (const edge of narrow.edges) {
      expect(visible.has(edge.source)).toBe(true);
      expect(visible.has(edge.target)).toBe(true);
    }
    expect(narrow.nodes.length).toBeLessThanOrEqual(graph.nodes.length);
  });

  it("refuses an unauthenticated read of either endpoint", async () => {
    for (const path_ of ["/v1/dashboard/kb-health", "/v1/dashboard/lineage"]) {
      const res = await fetch(`${rig.base}${path_}`);
      expect(res.status).toBe(401);
    }
    // And a reporter reads it — KB Health is not steward-only; what
    // differs is how much of the KB their scopes cover.
    const asReporter = await apiGet(rig, reporter, "/v1/dashboard/kb-health");
    expect(asReporter.status).toBe(200);
  });
});
