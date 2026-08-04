/**
 * Profile compilation (platform-architecture §5, CP-5 deliverable 1) and
 * the D-75.1 non-shadowing rule: skills come from the core image, never
 * from the customer KB.
 *
 * These are pure-function tests — compilation needs no database and no
 * running core, which is itself part of the design: the one-line setup is
 * generated from the profile YAML plus this release's skills, nothing else.
 */

import { describe, expect, it } from "vitest";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import YAML from "yaml";
import {
  compileProfile,
  defaultSkillsRoot,
  listShippedSkills,
  MissingSkillError,
  writeSetup,
} from "../src/compile.js";
import { BENCHMARK_PROFILE, REPORTER_PROFILE, STEWARD_PROFILE } from "./mcp-helpers.js";

const REPORTER = `
name: Reporter
description: Read the context estate and produce validated SQL / API requests
roles: [reporter]
skills: [report]
tools:
  allow: [search_context, get_entity, get_table, get_metric, validate_sql,
          execute_sql:supabase, flag_gap]
context:
  claude_md_fragment: |
    Prefer certified metrics from metrics/. Warn on stale or draft docs.
limits: { row_cap: 50000, timeout_s: 60 }
`;

async function scratchSkills(skills: Record<string, string>): Promise<string> {
  const root = await mkdtemp(path.join(tmpdir(), "cl-skills-"));
  for (const [name, body] of Object.entries(skills)) {
    await mkdir(path.join(root, name), { recursive: true });
    await writeFile(path.join(root, name, "SKILL.md"), body);
  }
  return root;
}

describe("profile compilation", () => {
  it("emits an MCP config that binds the profile by name", async () => {
    const skillsRoot = await scratchSkills({ report: "# report\nbody\n" });
    const setup = await compileProfile("reporter", YAML.parse(REPORTER), {
      publicUrl: "https://ctx.acme.internal/",
      skillsRoot,
    });

    const server = (setup.mcpConfig as { mcpServers: Record<string, { url: string; type: string }> })
      .mcpServers.contextlayer;
    expect(server.type).toBe("http");
    // Trailing slash on publicUrl must not double up.
    expect(server.url).toBe("https://ctx.acme.internal/mcp?profile=reporter");
  });

  it("bundles the named skill and carries the profile's CLAUDE.md fragment", async () => {
    const skillsRoot = await scratchSkills({ report: "# report\nthe skill body\n" });
    const setup = await compileProfile("reporter", YAML.parse(REPORTER), {
      publicUrl: "https://ctx.acme.internal",
      skillsRoot,
    });

    expect(setup.skills.map((s) => s.name)).toEqual(["report"]);
    expect(setup.skills[0].content).toContain("the skill body");
    expect(setup.claudeMd).toContain("Prefer certified metrics");
    // The tool list is documentation of what the profile permits.
    expect(setup.claudeMd).toContain("`execute_sql:supabase`");
    // Server-injected guardrails are stated as server-injected.
    expect(setup.claudeMd).toContain("row cap 50000");
    expect(setup.claudeMd).toMatch(/discarded/);
    expect(setup.warnings).toEqual([]);
  });

  it("writes the layout Claude Code reads", async () => {
    const skillsRoot = await scratchSkills({ report: "# report\n" });
    const setup = await compileProfile("reporter", YAML.parse(REPORTER), {
      publicUrl: "https://ctx.acme.internal",
      skillsRoot,
    });
    const out = await mkdtemp(path.join(tmpdir(), "cl-setup-"));
    const written = await writeSetup(setup, out);

    expect(written).toEqual([".claude/skills/report/SKILL.md", ".mcp.json", "CLAUDE.md"]);
    const cfg = JSON.parse(await readFile(path.join(out, ".mcp.json"), "utf-8"));
    expect(cfg.mcpServers.contextlayer.url).toContain("profile=reporter");
  });

  it("F-7: fails the compile when a profile names a skill this release does not ship", async () => {
    // Was warn-and-proceed until the CP-8 review (F-7). A bundle's
    // CLAUDE.md is read by the session as the statement of what it may
    // do, so a bundle missing a skill ships a quietly smaller product
    // than the profile describes. Emitting nothing is the honest outcome.
    const skillsRoot = await scratchSkills({ report: "# report\n" });
    const raw = YAML.parse(REPORTER) as Record<string, unknown>;
    raw.skills = ["report", "clairvoyance"];

    await expect(
      compileProfile("reporter", raw, { publicUrl: "https://ctx.acme.internal", skillsRoot }),
    ).rejects.toThrow(MissingSkillError);

    const err = await compileProfile("reporter", raw, {
      publicUrl: "https://ctx.acme.internal",
      skillsRoot,
    }).catch((e: unknown) => e as MissingSkillError);

    expect(err.missing).toEqual(["clairvoyance"]);
    expect(err.shipped).toEqual(["report"]);
    // The message must name the profile, the gap, and what does ship —
    // an operator reading only stderr has to be able to act on it.
    expect(err.message).toContain("reporter");
    expect(err.message).toContain("clairvoyance");
    expect(err.message).toContain("report");
  });
});

describe("D-75.1 — skills come from the core image, never the KB", () => {
  it("ignores a skills/ directory committed to the customer KB (AS-15 non-shadowing)", async () => {
    // A KB that tries to shadow the shipped skill with its own version.
    const kb = await mkdtemp(path.join(tmpdir(), "cl-kb-"));
    for (const rel of [
      path.join(".contextlayer", "skills", "report"),
      path.join("skills", "report"),
    ]) {
      await mkdir(path.join(kb, rel), { recursive: true });
      await writeFile(path.join(kb, rel, "SKILL.md"), "# report\nSHADOWED BY THE KB\n");
    }

    const skillsRoot = await scratchSkills({ report: "# report\nFROM THE CORE IMAGE\n" });
    const setup = await compileProfile("reporter", YAML.parse(REPORTER), {
      publicUrl: "https://ctx.acme.internal",
      skillsRoot,
    });

    expect(setup.skills[0].content).toContain("FROM THE CORE IMAGE");
    expect(setup.skills[0].content).not.toContain("SHADOWED");
  });

  it("does not read outside the skills root even when the profile asks it to", async () => {
    // Profiles are customer-editable data; a traversal in `skills:` must
    // not turn compilation into an arbitrary-file read. Since F-7 it is
    // also fatal — the traversal resolves to no skill, which is the same
    // failure as naming one that does not exist, and nothing is written.
    const skillsRoot = await scratchSkills({ report: "# report\n" });
    const raw = YAML.parse(REPORTER) as Record<string, unknown>;
    raw.skills = ["../../../etc"];

    const err = await compileProfile("reporter", raw, {
      publicUrl: "https://ctx.acme.internal",
      skillsRoot,
    }).catch((e: unknown) => e as MissingSkillError);

    expect(err).toBeInstanceOf(MissingSkillError);
    expect(err.missing).toEqual(["../../../etc"]);
  });

  it("ships the CP-5 skills in the core image", async () => {
    // The release's actual skills root, not a fixture: what a compiled
    // setup would really carry.
    const shipped = await listShippedSkills(defaultSkillsRoot());
    expect(shipped).toContain("report");
    expect(shipped).toContain("enrich");
    expect(shipped).toContain("review-sync"); // C-2 closed, Track A-1
  });
});

/**
 * R-8 (D-79 watch-note, amended to a test by the CP-8 review). The watch
 * note said "fixture profiles must track product profiles" and was held
 * twice by discipline and once by luck. This is its mechanical form.
 *
 * The failure it exists to catch: a profile — fixture or product — names
 * a skill the core does not ship, and nothing notices. That is exactly
 * how `review-sync` was specified (skill spec §7, AS-7), written into
 * both the shipped steward profile and its fixture twin, and never built.
 */
describe("R-8 — every skill named by a shipped profile exists in the core image", () => {
  /**
   * Skills a profile may name that the core does not yet ship. Every
   * entry is a KNOWN, RULED gap with an owner and an exit — never a
   * convenience. The list is asserted to be exhausted below, so an entry
   * whose skill has shipped fails the suite and forces its own removal.
   */
  // C-2 closed at Track A-1 (D-98): `review-sync` shipped and its entry
  // came out, as the exhaustion test below demanded. Empty is the goal
  // state; a new entry needs a ruling, an owner, and an exit.
  const KNOWN_UNSHIPPED: Record<string, string> = {};

  const skillsOf = (yaml: string): string[] =>
    stringList((YAML.parse(yaml) as { skills?: unknown }).skills);

  function stringList(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  }

  it("holds for every fixture profile the conformance rigs ship", async () => {
    const shipped = new Set(await listShippedSkills(defaultSkillsRoot()));
    const profiles: Record<string, string> = {
      reporter: REPORTER_PROFILE,
      steward: STEWARD_PROFILE,
      benchmark: BENCHMARK_PROFILE,
    };

    const gaps: string[] = [];
    for (const [profile, yaml] of Object.entries(profiles)) {
      for (const skill of skillsOf(yaml)) {
        if (shipped.has(skill)) continue;
        if (skill in KNOWN_UNSHIPPED) continue;
        gaps.push(`${profile} names "${skill}" (shipped: ${[...shipped].sort().join(", ")})`);
      }
    }
    expect(gaps, `profiles name skills this core release does not ship:\n${gaps.join("\n")}`)
      .toEqual([]);
  });

  it("forces every known-unshipped entry to be removed once its skill ships", async () => {
    // Without this, the exception list silently becomes permanent — the
    // failure mode that made R-8 a watch-note nobody actioned.
    const shipped = await listShippedSkills(defaultSkillsRoot());
    const stale = Object.keys(KNOWN_UNSHIPPED).filter((s) => shipped.includes(s));
    expect(stale, `these skills now ship — delete their KNOWN_UNSHIPPED entries: ${stale.join(", ")}`)
      .toEqual([]);
  });

  it("would have caught C-2: an unlisted missing skill fails, and compile refuses it", async () => {
    // The counterfactual, run for real. A profile naming an unshipped
    // skill that is NOT a ruled exception must be a hard failure at both
    // levels: this test's inventory check, and the compile itself (F-7).
    const skillsRoot = await scratchSkills({ enrich: "# enrich\n" });
    const raw = YAML.parse(STEWARD_PROFILE) as Record<string, unknown>;

    const err = await compileProfile("steward", raw, {
      publicUrl: "https://ctx.acme.internal",
      skillsRoot,
    }).catch((e: unknown) => e as MissingSkillError);

    expect(err).toBeInstanceOf(MissingSkillError);
    expect(err.missing).toEqual(["review-sync"]);
  });
});
