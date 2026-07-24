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
  writeSetup,
} from "../src/compile.js";

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

  it("warns rather than fails when a profile names a skill this release does not ship", async () => {
    const skillsRoot = await scratchSkills({ report: "# report\n" });
    const raw = YAML.parse(REPORTER) as Record<string, unknown>;
    raw.skills = ["report", "clairvoyance"];

    const setup = await compileProfile("reporter", raw, {
      publicUrl: "https://ctx.acme.internal",
      skillsRoot,
    });

    // The rest of the profile is still usable — an unknown skill must not
    // cost the operator their whole setup.
    expect(setup.skills.map((s) => s.name)).toEqual(["report"]);
    expect(setup.warnings).toHaveLength(1);
    expect(setup.warnings[0]).toContain("clairvoyance");
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
    // not turn compilation into an arbitrary-file read.
    const skillsRoot = await scratchSkills({ report: "# report\n" });
    const raw = YAML.parse(REPORTER) as Record<string, unknown>;
    raw.skills = ["../../../etc"];

    const setup = await compileProfile("reporter", raw, {
      publicUrl: "https://ctx.acme.internal",
      skillsRoot,
    });

    expect(setup.skills).toEqual([]);
    expect(setup.warnings).toHaveLength(1);
  });

  it("ships the CP-5 skills in the core image", async () => {
    // The release's actual skills root, not a fixture: what a compiled
    // setup would really carry.
    const shipped = await listShippedSkills(defaultSkillsRoot());
    expect(shipped).toContain("report");
    expect(shipped).toContain("enrich");
  });
});
