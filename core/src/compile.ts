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

import { createHash } from "node:crypto";
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
  /** Skill-local files beside SKILL.md (RA-5 tooling), bundle-relative. */
  files: { path: string; content: string }[];
}

export interface CompiledSetup {
  profile: string;
  displayName: string;
  /** `.mcp.json` — the Claude Code remote-MCP entry. */
  mcpConfig: Record<string, unknown>;
  /** `CLAUDE.md` — the profile's fragment plus the compiled preamble. */
  claudeMd: string;
  skills: CompiledSkill[];
  /**
   * The setup stamp (PA-2 / A-2): a digest of everything this bundle
   * would put on a session's disk. It rides in the compiled `.mcp.json`
   * URL, so the server sees on every connection which compile the
   * session is running and can say so when that is no longer what
   * compiling now would produce. See `setupStamp`.
   */
  stamp: string;
  /** Non-fatal problems the operator should see. */
  warnings: string[];
}

/**
 * The stamp is taken over the bundle's *contract-bearing* bytes: the
 * server URL, the CLAUDE.md the session reads as its statement of what
 * it may do, and every skill file. It deliberately does **not** cover
 * the stamp's own carrier (the `.mcp.json` URL) or anything time- or
 * requester-dependent, so two compiles of one profile state produce one
 * stamp — and any change that could narrow what a session attempts
 * produces a different one.
 */
function setupStamp(input: {
  profile: string;
  displayName: string;
  url: string;
  claudeMd: string;
  skills: CompiledSkill[];
}): string {
  const digest = (text: string) => createHash("sha256").update(text, "utf-8").digest("hex");
  const canonical = JSON.stringify({
    v: 1,
    profile: input.profile,
    display: input.displayName,
    url: input.url,
    claude_md: digest(input.claudeMd),
    skills: input.skills.map((s) => ({
      name: s.name,
      sha256: digest(s.content),
      files: s.files.map((f) => ({ path: f.path, sha256: digest(f.content) })),
    })),
  });
  return createHash("sha256").update(canonical, "utf-8").digest("hex").slice(0, 16);
}

/**
 * A profile named a skill this release does not ship (F-7).
 *
 * This is fatal, not a warning. The compiled bundle's `CLAUDE.md` is read
 * by the session as the statement of what it may do, so it acts as *de
 * facto client-side permissions* (PA-2): it cannot widen the server
 * allow-set, but it silently narrows what the session will even attempt.
 * A bundle missing a skill therefore ships a quietly smaller product than
 * the profile describes — which is exactly how the steward's half of the
 * drift loop went missing for a whole checkpoint while `compile` printed
 * a warning and exited 0 (CP-8 report C-2/F-7).
 *
 * Emitting nothing is the honest outcome: a setup that cannot be built
 * correctly should not be delivered at all.
 */
export class MissingSkillError extends Error {
  readonly profile: string;
  readonly missing: string[];
  readonly shipped: string[];

  constructor(profile: string, missing: string[], shipped: string[]) {
    super(
      `profile "${profile}" names skill${missing.length > 1 ? "s" : ""} ` +
        `${missing.map((s) => `"${s}"`).join(", ")}, which this core release does not ship. ` +
        `Shipped: ${shipped.join(", ") || "(none)"}. ` +
        `Fix the profile or install the skill — a bundle missing a skill silently ` +
        `narrows what the session will attempt.`,
    );
    this.name = "MissingSkillError";
    this.profile = profile;
    this.missing = missing;
    this.shipped = shipped;
  }
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
 * Read a skill's SKILL.md from the core image. Returns null when the
 * profile names a skill this release does not ship, or when the name
 * escapes the skills root; the caller turns that into a fatal
 * `MissingSkillError` (F-7, ruling D-96 task 2).
 */
async function readSkill(skillsRoot: string, name: string): Promise<CompiledSkill | null> {
  // Defend the path join: a profile is customer-editable data, and
  // `skills: ["../../etc/passwd"]` must not read outside the skills root.
  const dir = path.resolve(skillsRoot, name);
  if (dir !== path.join(skillsRoot, name)) return null;
  const file = path.join(dir, "SKILL.md");
  if (!existsSync(file)) return null;
  // A skill is its whole directory, not just SKILL.md: skill-local
  // tooling (report-authoring RA-5 — pbir_tool.py) must reach the
  // session machine through the same bundle, or "ships inside the
  // skill" is a sentence rather than a fact.
  const files: { path: string; content: string }[] = [];
  const walk = async (sub: string): Promise<void> => {
    for (const entry of await readdir(path.join(dir, sub), { withFileTypes: true })) {
      const rel = sub ? `${sub}/${entry.name}` : entry.name;
      if (entry.isDirectory()) await walk(rel);
      else if (rel !== "SKILL.md") {
        files.push({ path: rel, content: await readFile(path.join(dir, rel), "utf-8") });
      }
    }
  };
  await walk("");
  files.sort((a, b) => (a.path < b.path ? -1 : 1));
  return { name, content: await readFile(file, "utf-8"), files };
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
  const missing: string[] = [];
  for (const skillName of stringList(raw.skills)) {
    const skill = await readSkill(skillsRoot, skillName);
    if (skill) skills.push(skill);
    else missing.push(skillName);
  }
  // F-7 (D-96 task 2): fatal, not a warning. See MissingSkillError.
  if (missing.length > 0) {
    throw new MissingSkillError(name, missing, await listShippedSkills(skillsRoot));
  }

  const base = opts.publicUrl.replace(/\/+$/, "");
  const mcpUrl = `${base}/mcp?profile=${encodeURIComponent(name)}`;

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
    // PA-2, the July-29 lesson stated where the session will read it:
    // the tool list above is a *snapshot*, and a session that treats a
    // stale snapshot as its permissions silently ships a smaller
    // product than the profile describes.
    "## If this file and the server disagree",
    "",
    "The tool list above was compiled at a point in time. The server",
    "re-checks your identity and profile on every call, so its list is",
    "the authoritative one and it can only ever be *wider* than this",
    "file. If the server says your setup is out of date, do not narrow",
    "what you attempt — get a fresh setup in one step:",
    "",
    `    ${base}/v1/setup/bundle`,
    "",
    "(Sign in there with your own identity; the download is your own",
    "profile's, and it carries no credential.)",
    "",
  ]
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trimEnd();

  const stamp = setupStamp({ profile: name, displayName, url: mcpUrl, claudeMd, skills });
  const mcpConfig = {
    mcpServers: {
      contextlayer: {
        type: "http",
        // The stamp rides here because this URL is the one thing the
        // session sends the server on every connection (PA-2 / A-2).
        url: `${mcpUrl}&setup=${stamp}`,
      },
    },
  };

  return { profile: name, displayName, mcpConfig, claudeMd, skills, stamp, warnings };
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
    for (const file of skill.files) {
      const target = path.join(dir, ...file.path.split("/"));
      await mkdir(path.dirname(target), { recursive: true });
      await writeFile(target, file.content);
      written.push(`.claude/skills/${skill.name}/${file.path}`);
    }
  }

  return written.sort();
}
