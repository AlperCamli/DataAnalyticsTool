/**
 * Profile compilation (platform-architecture §5): the core compiles a
 * profile into a one-line Claude Code setup — remote MCP config + skills
 * bundle + CLAUDE.md fragment.
 *
 * Two rules the implementation exists to hold:
 *
 * 1. **Compiled config is a convenience, never a grant.** Everything
 *    emitted here is client-side. The MCP server recomputes the allow-set
 *    from the token's roles on every call (M-3, MCP-R2/R4), so a
 *    hand-widened `.mcp.json` buys the holder nothing. The emitted
 *    tool list is therefore documentation of what the profile permits,
 *    not the thing that permits it.
 *
 * 2. **Skills come from the core image, never the KB clone** (HLR §7.4,
 *    ruling D-75.1). Skills are fixed product artifacts, identical across
 *    customers, versioned with the core and upgraded on the release path.
 *    A `skills/` directory committed to a customer KB is ignored here —
 *    `compileProfile` is not given the KB workspace at all, which is the
 *    structural way to guarantee non-shadowing rather than a check that
 *    could rot.
 */

import { existsSync } from "node:fs";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** Skills ship at `core/skills/<name>/SKILL.md`, beside the built `dist/`. */
export function defaultSkillsRoot(): string {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "skills");
}

export interface CompiledSkill {
  name: string;
  content: string;
}

export interface CompiledSetup {
  profile: string;
  displayName: string;
  /** `.mcp.json` — the Claude Code remote-MCP entry. */
  mcpConfig: Record<string, unknown>;
  /** `CLAUDE.md` — the profile's fragment plus the compiled preamble. */
  claudeMd: string;
  skills: CompiledSkill[];
  /** Non-fatal problems the operator should see (missing skills, etc.). */
  warnings: string[];
}

export interface CompileOptions {
  /** Public base URL of the core, e.g. `https://ctx.acme.internal`. */
  publicUrl: string;
  /** Override for tests; defaults to the core image's skills dir. */
  skillsRoot?: string;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/**
 * Read a skill's SKILL.md from the core image. Returns null (and a
 * warning upstream) when the profile names a skill this release does not
 * ship — an unknown skill must not fail the whole setup, since the rest
 * of the profile is still usable.
 */
async function readSkill(skillsRoot: string, name: string): Promise<CompiledSkill | null> {
  // Defend the path join: a profile is customer-editable data, and
  // `skills: ["../../etc/passwd"]` must not read outside the skills root.
  const dir = path.resolve(skillsRoot, name);
  if (dir !== path.join(skillsRoot, name)) return null;
  const file = path.join(dir, "SKILL.md");
  if (!existsSync(file)) return null;
  return { name, content: await readFile(file, "utf-8") };
}

export async function listShippedSkills(skillsRoot = defaultSkillsRoot()): Promise<string[]> {
  if (!existsSync(skillsRoot)) return [];
  const entries = await readdir(skillsRoot, { withFileTypes: true });
  return entries
    .filter((e) => e.isDirectory() && existsSync(path.join(skillsRoot, e.name, "SKILL.md")))
    .map((e) => e.name)
    .sort();
}

/**
 * Compile one profile. `raw` is the parsed profile YAML — note that the
 * KB workspace is deliberately *not* a parameter (rule 2 above).
 */
export async function compileProfile(
  name: string,
  raw: Record<string, unknown>,
  opts: CompileOptions,
): Promise<CompiledSetup> {
  const skillsRoot = opts.skillsRoot ?? defaultSkillsRoot();
  const warnings: string[] = [];

  const tools = raw.tools as { allow?: unknown } | undefined;
  const allow = stringList(tools?.allow);
  const displayName = typeof raw.name === "string" ? raw.name : name;

  const skills: CompiledSkill[] = [];
  for (const skillName of stringList(raw.skills)) {
    const skill = await readSkill(skillsRoot, skillName);
    if (skill) skills.push(skill);
    else warnings.push(`profile names skill "${skillName}", which this core release does not ship`);
  }

  const base = opts.publicUrl.replace(/\/+$/, "");
  const mcpConfig = {
    mcpServers: {
      contextlayer: {
        type: "http",
        url: `${base}/mcp?profile=${encodeURIComponent(name)}`,
      },
    },
  };

  const context = raw.context as { claude_md_fragment?: unknown } | undefined;
  const fragment = typeof context?.claude_md_fragment === "string" ? context.claude_md_fragment.trim() : "";
  const limits = (raw.limits ?? {}) as { row_cap?: number; timeout_s?: number };

  const claudeMd = [
    `# ${displayName}`,
    "",
    typeof raw.description === "string" ? raw.description : "",
    "",
    "Compiled from the Context Layer profile of the same name. Your data",
    "access runs through the `contextlayer` MCP server; the server checks",
    "your identity and this profile on every call, so what you can reach is",
    "decided there, not by this file or by your local config.",
    "",
    "## Tools this profile permits",
    "",
    ...allow.map((t) => `- \`${t}\``),
    "",
    limits.row_cap || limits.timeout_s
      ? `Query guardrails are injected server-side: row cap ${limits.row_cap ?? "—"}, timeout ${limits.timeout_s ?? "—"}s. ` +
        "Anything your client sends for these is discarded."
      : "",
    "",
    ...(skills.length
      ? ["## Skills", "", ...skills.map((s) => `- \`${s.name}\` — see \`.claude/skills/${s.name}/SKILL.md\``), ""]
      : []),
    ...(fragment ? ["## From your profile", "", fragment, ""] : []),
  ]
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trimEnd();

  return { profile: name, displayName, mcpConfig, claudeMd, skills, warnings };
}

/**
 * Write a compiled setup into `outDir` as the layout Claude Code reads:
 * `.mcp.json`, `CLAUDE.md`, `.claude/skills/<name>/SKILL.md`. Returns the
 * relative paths written, sorted — the caller prints them.
 */
export async function writeSetup(setup: CompiledSetup, outDir: string): Promise<string[]> {
  const written: string[] = [];

  await mkdir(outDir, { recursive: true });
  await writeFile(path.join(outDir, ".mcp.json"), `${JSON.stringify(setup.mcpConfig, null, 2)}\n`);
  written.push(".mcp.json");

  await writeFile(path.join(outDir, "CLAUDE.md"), `${setup.claudeMd}\n`);
  written.push("CLAUDE.md");

  for (const skill of setup.skills) {
    const dir = path.join(outDir, ".claude", "skills", skill.name);
    await mkdir(dir, { recursive: true });
    await writeFile(path.join(dir, "SKILL.md"), skill.content);
    written.push(`.claude/skills/${skill.name}/SKILL.md`);
  }

  return written.sort();
}
