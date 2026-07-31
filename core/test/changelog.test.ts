/**
 * F4 (security review #1 / D-66 point 2): snapshot-derived strings — object
 * and column names, view-diff detail — are attacker-influenceable, and the
 * sync PR they compose is trusted by a human reviewer. A crafted object name
 * carrying a backtick, an @mention, and a newline + heading must render inert
 * in the composed title/body, and ordinary content must pass through
 * byte-unchanged (the deterministic-changelog / golden guarantee, exercised
 * end-to-end by SO-4's byte-exact changelog in sync-drill.test.ts).
 */

import { describe, expect, it } from "vitest";
import {
  buildBody,
  buildTitle,
  type ChangelogInput,
  type FinalizedDiff,
  type ScanResult,
} from "../src/changelog.js";

// backtick (code-span breakout) + @mention + newline-heading injection.
const EVIL_NAME = "evil`@everyone\n## PWNED";

function diff(overrides: Partial<FinalizedDiff> = {}): FinalizedDiff {
  return {
    system: "sys",
    empty: false,
    added: [],
    removed: [],
    changed_structural: [],
    changed_metadata_only: [],
    ...overrides,
  };
}

function emptyScan(overrides: Partial<ScanResult> = {}): ScanResult {
  return {
    contaminated: [],
    stale: [],
    undeclared_references: [],
    breaking: {},
    additive_changed: [],
    ...overrides,
  };
}

describe("F4: snapshot-derived strings are neutralized in the sync PR", () => {
  it("defuses a malicious object name in a code span and a malicious breaking detail (raw)", () => {
    const input: ChangelogInput = {
      diffs: [
        diff({
          added: [
            { identity: { kind: "table", schema: "public", name: EVIL_NAME }, classification: "added" },
          ],
        }),
      ],
      scan: emptyScan({
        breaking: {
          "sys.public.orders": { change: "definition_changed", detail: "dropped @team\n## HEADING" },
        },
      }),
      wheel: null,
      excluded: [],
    };

    const body = buildBody(input);

    // no live control sequences survive
    expect(body).not.toContain("@everyone");
    expect(body).not.toContain("@team");
    expect(body).not.toContain("evil`"); // the payload backtick can't close the span
    expect(body).not.toContain("\n## PWNED"); // newline collapsed → no forged heading
    expect(body).not.toContain("\n## HEADING");

    // and the neutralized-but-visible forms are present, in place
    expect(body).toContain("evil'&#64;everyone ## PWNED");
    expect(body).toContain("dropped &#64;team ## HEADING");

    // the legitimate structural headings are untouched
    expect(body).toContain("## Breaking");
  });

  it("neutralizes a malicious system name in the title", () => {
    const title = buildTitle({
      diffs: [diff({ system: "s`@x", added: [{ identity: { kind: "table", schema: "public", name: "ok" }, classification: "added" }] })],
      scan: emptyScan(),
      wheel: null,
      excluded: [],
    });
    expect(title).not.toContain("@x");
    expect(title).toContain("across s'&#64;x");
  });

  it("is a strict no-op on ordinary identifiers (golden determinism)", () => {
    const input: ChangelogInput = {
      diffs: [
        diff({
          added: [
            { identity: { kind: "table", schema: "shop", name: "order_items" }, classification: "added" },
          ],
        }),
      ],
      scan: emptyScan(),
      wheel: null,
      excluded: [],
    };
    const body = buildBody(input);
    expect(body).toContain("- `sys.shop.order_items` — added (table)");
    expect(body).not.toContain("&#"); // no entity encoding introduced for clean input
  });
});

/**
 * D-97.1. A graph-only run (CP-7 F-4: publish attestations carried into
 * `lineage/graph.json`, no snapshot moved) used to fall through to the
 * wheel-only branch, so KB PR #30 — the one PR that records report
 * lineage entering the KB — told its reviewer it was a wheel carry, and
 * named no wheel. Content right, description wrong.
 */
describe("graph-only runs describe themselves (D-97.1)", () => {
  const graphOnly = (
    wheel: ChangelogInput["wheel"] = null,
  ): ChangelogInput => ({ diffs: [], scan: null, wheel, excluded: [], graphOnly: true });

  it("names the lineage carry in the title and body, and no wheel", () => {
    const input = graphOnly();
    expect(buildTitle(input)).toBe("sync: 0 breaking, 0 additive (report lineage only)");
    const body = buildBody(input);
    expect(body).toContain("Graph-only run");
    expect(body).toContain("lineage/graph.json");
    expect(body).not.toContain("Wheel-only"); // the PR #30 defect
    expect(body).not.toContain("wheel update");
  });

  it("names BOTH when a wheel rides along — the case inference would miss", () => {
    const input = graphOnly({ fromVersion: "0.5.0", toVersion: "0.6.0" });
    expect(buildTitle(input)).toBe(
      "sync: 0 breaking, 0 additive (report lineage + wheel update to 0.6.0)",
    );
    const body = buildBody(input);
    expect(body).toContain("0.5.0 → 0.6.0"); // the wheel banner still leads
    expect(body).toContain("Graph-only run"); // …and the graph carry is still stated
  });

  it("leaves a genuine wheel-only run exactly as it was", () => {
    const input: ChangelogInput = {
      diffs: [],
      scan: null,
      wheel: { fromVersion: "0.5.0", toVersion: "0.6.0" },
      excluded: [],
    };
    expect(buildTitle(input)).toBe(
      "sync: 0 breaking, 0 additive (wheel-only update to 0.6.0)",
    );
    expect(buildBody(input)).toContain("Wheel-only run: no drift pending");
  });
});
