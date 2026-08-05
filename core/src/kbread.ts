/**
 * The MCP read surface's view of the world (MCP spec §3 read
 * consistency): KB at the default branch's merged HEAD + the latest
 * accepted snapshot per system, materialized as a rendered workspace.
 *
 * Build recipe per (HEAD sha, snapshot set) key: clone HEAD, overwrite
 * the `.contextlayer/snapshots/` pins with the latest accepted bodies,
 * and re-run the deterministic generator — machine docs in the
 * workspace then carry facts at the *latest* snapshot merged with HEAD
 * enrichment (MC-5: snapshot is authority for facts). When the latest
 * acceptance differs from the HEAD pin, the system is in render-lag
 * (MCP-R9) and every machine doc served for it says so. KB-8 makes the
 * workspace byte-identical to HEAD when there is no lag.
 *
 * The workspace is cached on its key; HEAD is re-checked at most every
 * `kbRefreshMs` (0 = every call — the read-consistency ideal; the TTL
 * is a pilot-scale concession recorded in DECISIONS D-68).
 */

import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { mkdir, readdir, readFile, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import pg from "pg";
import YAML from "yaml";
import type { CoreConfig } from "./config.js";
import { cloneKb, remoteHeadSha } from "./gitkb.js";

export interface KbDoc {
  /** repo-relative path */
  path: string;
  docClass: string | null;
  fm: Record<string, unknown> | null;
  body: string;
  title: string;
  oneLiner: string;
}

export interface SnapshotObject {
  fqn: string;
  system: string;
  schema: string;
  name: string;
  kind: string;
  schemaHash: string;
  columns: { name: string; type: string; nullable?: boolean; description?: string | null }[];
  keys: Record<string, unknown>;
  raw: Record<string, unknown>;
}

export interface SystemState {
  system: string;
  systemClass: string;
  snapshotId: string;
  canonicalBodySha256: string;
  capturedAt: string;
  acceptedAt: string;
  objects: Map<string, SnapshotObject>;
  renderLag: boolean;
}

export interface RoleEntry {
  key: string;
  profile: string | null;
  oidcGroup: string | null;
  visibility: string[];
}

export interface KbState {
  key: string;
  headSha: string;
  workdir: string;
  builtAt: number;
  renderFailed: boolean;
  docs: Map<string, KbDoc>;
  /** machine doc facts per object FQN (roster entries included) */
  machineByFqn: Map<string, { path: string; kind: string; schemaHash: string; system: string }>;
  humanByFqn: Map<string, string>;
  systems: Map<string, SystemState>;
  roles: RoleEntry[] | null;
  profiles: Map<string, Record<string, unknown>>;
  guardrails: Record<string, Record<string, unknown>>;
  syncPolicy: Record<string, unknown> | null;
  /** `.contextlayer/dashboard.yaml` — which modules a deployment turns
   * on and which roles see them (UI-9). Null when the KB carries none,
   * which the module endpoint reports rather than papers over. */
  dashboard: Record<string, unknown> | null;
  graph: { nodes: { id: string; node_kind?: string; resolved?: boolean }[]; edges: Record<string, unknown>[] } | null;
}

function sha256hex(data: Buffer | string): string {
  return createHash("sha256").update(data).digest("hex");
}

export function parseFrontMatter(text: string): { fm: Record<string, unknown> | null; body: string } {
  if (!text.startsWith("---\n")) return { fm: null, body: text };
  const end = text.indexOf("\n---", 4);
  if (end === -1) return { fm: null, body: text };
  const raw = text.slice(4, end + 1);
  const body = text.slice(text.indexOf("\n", end + 1) + 1);
  try {
    const fm = YAML.parse(raw) as Record<string, unknown> | null;
    return { fm: fm && typeof fm === "object" ? fm : null, body };
  } catch {
    return { fm: null, body: text };
  }
}

function firstHeading(body: string, fallback: string): string {
  const match = /^#\s+(.+)$/m.exec(body);
  return match ? match[1]!.trim() : fallback;
}

function firstParagraphLine(body: string): string {
  for (const line of body.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || trimmed.startsWith("---")) continue;
    return trimmed.length > 200 ? `${trimmed.slice(0, 197)}…` : trimmed;
  }
  return "";
}

async function walkFiles(root: string, sub = ""): Promise<string[]> {
  const out: string[] = [];
  const entries = await readdir(path.join(root, sub), { withFileTypes: true });
  for (const entry of entries) {
    if (entry.name.startsWith(".git") || entry.name === ".obsidian") continue;
    const rel = sub ? `${sub}/${entry.name}` : entry.name;
    if (entry.isDirectory()) out.push(...(await walkFiles(root, rel)));
    else out.push(rel);
  }
  return out;
}

function runPy(pythonCmd: string[], args: string[], cwd: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonCmd[0]!, [...pythonCmd.slice(1), ...args], {
      cwd,
      stdio: ["ignore", "ignore", "pipe"],
    });
    let stderr = "";
    child.stderr.on("data", (d: Buffer) => (stderr += d.toString()));
    child.on("error", (err) => reject(new Error(`cannot spawn generator: ${err.message}`)));
    child.on("close", (code) =>
      code === 0 ? resolve() : reject(new Error(`generator exited ${code}: ${stderr.slice(0, 2000)}`)),
    );
  });
}

/** The machine-readable guardrail block from conventions.md (KB §7). */
function parseGuardrails(conventions: string | undefined): Record<string, Record<string, unknown>> {
  if (!conventions) return {};
  const fences = conventions.matchAll(/```yaml\n([\s\S]*?)```/g);
  for (const match of fences) {
    try {
      const parsed = YAML.parse(match[1]!) as Record<string, unknown>;
      if (parsed && typeof parsed === "object") {
        const systems = Object.entries(parsed).filter(
          ([, v]) => v && typeof v === "object" && "dialect" in (v as Record<string, unknown>),
        );
        if (systems.length > 0) {
          return Object.fromEntries(systems) as Record<string, Record<string, unknown>>;
        }
      }
    } catch {
      // not the guardrail fence; keep scanning
    }
  }
  return {};
}

export class KbReader {
  private state: KbState | null = null;
  private lastHeadCheck = 0;
  private building: Promise<KbState> | null = null;

  constructor(
    private readonly cfg: CoreConfig,
    private readonly pool: pg.Pool,
  ) {}

  /** Current workspace; re-checks HEAD/snapshots at most every kbRefreshMs. */
  async current(): Promise<KbState> {
    const now = Date.now();
    if (this.state && now - this.lastHeadCheck < this.cfg.mcp.kbRefreshMs) return this.state;
    if (this.building) return this.building;
    this.building = this.rebuildIfChanged().finally(() => {
      this.building = null;
    });
    return this.building;
  }

  private async latestSnapshots(): Promise<
    { system: string; snapshot_id: string; canonical_body_sha256: string; captured_at: Date; accepted_at: Date }[]
  > {
    const { rows } = await this.pool.query(
      `SELECT DISTINCT ON (system)
              system, snapshot_id, canonical_body_sha256, captured_at, accepted_at
         FROM accepted_snapshots
        ORDER BY system, accepted_at DESC, snapshot_id DESC`,
    );
    return rows;
  }

  private async rebuildIfChanged(): Promise<KbState> {
    const headSha = await remoteHeadSha(this.cfg.sync);
    this.lastHeadCheck = Date.now();
    const metas = await this.latestSnapshots();
    const key = sha256hex(
      `${headSha}|${metas.map((m) => `${m.system}:${m.canonical_body_sha256}`).join(",")}`,
    ).slice(0, 16);
    if (this.state && this.state.key === key) return this.state;
    const previous = this.state;
    this.state = await this.build(key, headSha, metas);
    if (previous && previous.workdir !== this.state.workdir) {
      await rm(previous.workdir, { recursive: true, force: true }).catch(() => {});
    }
    return this.state;
  }

  private async build(
    key: string,
    headSha: string,
    metas: { system: string; snapshot_id: string; canonical_body_sha256: string; captured_at: Date; accepted_at: Date }[],
  ): Promise<KbState> {
    const base = path.join(this.cfg.sync.workdir, "mcp");
    await mkdir(base, { recursive: true });
    const workdir = path.join(base, `kb-${key}`);
    await rm(workdir, { recursive: true, force: true });
    const clonedSha = await cloneKb(this.cfg.sync, workdir);

    const systems = new Map<string, SystemState>();
    const pinPaths: string[] = [];
    for (const meta of metas) {
      const { rows } = await this.pool.query<{ body: Buffer }>(
        `SELECT body FROM accepted_snapshots WHERE snapshot_id = $1`,
        [meta.snapshot_id],
      );
      const body = rows[0]?.body;
      if (!body) continue;
      const pinPath = path.join(workdir, ".contextlayer", "snapshots", `${meta.system}.json`);
      let renderLag = true;
      if (existsSync(pinPath)) {
        const headPin = await readFile(pinPath);
        renderLag = !headPin.equals(body) && headPin.toString("utf-8").trim() !== body.toString("utf-8").trim();
      }
      await mkdir(path.dirname(pinPath), { recursive: true });
      const { writeFile } = await import("node:fs/promises");
      await writeFile(pinPath, body);
      pinPaths.push(pinPath);

      const doc = JSON.parse(body.toString("utf-8")) as {
        system: string;
        system_class: string;
        objects: Record<string, unknown>[];
      };
      const objects = new Map<string, SnapshotObject>();
      for (const raw of doc.objects) {
        const schema = String(raw.schema ?? "");
        const name = String(raw.name ?? "");
        const fqn = `${meta.system}.${schema}.${name}`;
        objects.set(fqn, {
          fqn,
          system: meta.system,
          schema,
          name,
          kind: String(raw.kind ?? ""),
          schemaHash: String(raw.schema_hash ?? ""),
          columns: Array.isArray(raw.columns)
            ? (raw.columns as SnapshotObject["columns"])
            : [],
          keys: (raw.keys as Record<string, unknown>) ?? {},
          raw: raw as Record<string, unknown>,
        });
      }
      systems.set(meta.system, {
        system: meta.system,
        systemClass: doc.system_class,
        snapshotId: meta.snapshot_id,
        canonicalBodySha256: meta.canonical_body_sha256,
        capturedAt: meta.captured_at.toISOString(),
        acceptedAt: meta.accepted_at.toISOString(),
        objects,
        renderLag,
      });
    }

    // Re-render machine docs against the latest snapshots (facts
    // authority, MC-5). Failure degrades to serving the HEAD tree —
    // trust blocks still carry the render-lag signal.
    let renderFailed = false;
    if (pinPaths.length > 0) {
      try {
        await runPy(this.cfg.sync.pythonCmd, ["-m", "generator.render", ...pinPaths, "--out", workdir], workdir);
      } catch {
        renderFailed = true;
      }
    }

    const docs = new Map<string, KbDoc>();
    const machineByFqn = new Map<string, { path: string; kind: string; schemaHash: string; system: string }>();
    const humanByFqn = new Map<string, string>();
    const profiles = new Map<string, Record<string, unknown>>();
    let roles: RoleEntry[] | null = null;
    let syncPolicy: Record<string, unknown> | null = null;
    let dashboard: Record<string, unknown> | null = null;
    let graph: KbState["graph"] = null;

    for (const rel of await walkFiles(workdir)) {
      const full = path.join(workdir, rel);
      if (rel === "lineage/graph.json") {
        try {
          graph = JSON.parse(await readFile(full, "utf-8")) as KbState["graph"];
        } catch {
          graph = null;
        }
        continue;
      }
      if (rel.startsWith(".contextlayer/")) {
        if (rel === ".contextlayer/roles.yaml") {
          try {
            const parsed = YAML.parse(await readFile(full, "utf-8")) as {
              roles?: Record<string, { profile?: string; oidc_group?: string; visibility?: string[] }>;
            };
            roles = Object.entries(parsed.roles ?? {}).map(([roleKey, entry]) => ({
              key: roleKey,
              profile: entry.profile ?? null,
              oidcGroup: entry.oidc_group ?? null,
              visibility: entry.visibility ?? [],
            }));
          } catch {
            roles = null;
          }
        } else if (rel === ".contextlayer/dashboard.yaml") {
          try {
            const parsed = YAML.parse(await readFile(full, "utf-8")) as Record<string, unknown>;
            dashboard = parsed && typeof parsed === "object" ? parsed : null;
          } catch {
            // An unparseable dashboard.yaml configures nothing; the
            // module endpoint then reports the shipped default and says
            // which it used, rather than serving a half-read file.
            dashboard = null;
          }
        } else if (rel === ".contextlayer/sync-policy.yaml") {
          try {
            syncPolicy = YAML.parse(await readFile(full, "utf-8")) as Record<string, unknown>;
          } catch {
            syncPolicy = null;
          }
        } else if (rel.startsWith(".contextlayer/profiles/") && (rel.endsWith(".yaml") || rel.endsWith(".yml"))) {
          try {
            const parsed = YAML.parse(await readFile(full, "utf-8")) as Record<string, unknown>;
            const stem = path.basename(rel).replace(/\.ya?ml$/, "");
            if (parsed && typeof parsed === "object") profiles.set(stem, parsed);
          } catch {
            // an unparseable profile grants nothing
          }
        }
        continue;
      }
      if (!rel.endsWith(".md")) continue;
      const text = await readFile(full, "utf-8");
      const { fm, body } = parseFrontMatter(text);
      const stem = path.basename(rel, ".md");
      const doc: KbDoc = {
        path: rel,
        docClass: (fm?.doc_class as string | undefined) ?? null,
        fm,
        body,
        title: firstHeading(body, stem),
        oneLiner: (fm?.purpose as string | undefined) ?? firstParagraphLine(body),
      };
      docs.set(rel, doc);
      const system = rel.startsWith("systems/") ? rel.split("/")[1]! : "";
      if (doc.docClass === "machine-object" && typeof fm?.object === "string") {
        machineByFqn.set(fm.object, {
          path: rel,
          kind: String(fm.kind ?? ""),
          schemaHash: String(fm.schema_hash ?? ""),
          system,
        });
      } else if (doc.docClass === "machine-group" && Array.isArray(fm?.objects)) {
        for (const entry of fm.objects as { object?: string; kind?: string; schema_hash?: string }[]) {
          if (typeof entry.object === "string") {
            machineByFqn.set(entry.object, {
              path: rel,
              kind: String(entry.kind ?? ""),
              schemaHash: String(entry.schema_hash ?? ""),
              system,
            });
          }
        }
      } else if (
        (doc.docClass === "human-object" || doc.docClass === "human-group") &&
        typeof fm?.object === "string"
      ) {
        humanByFqn.set(fm.object, rel);
      }
    }

    const conventions = docs.get("conventions.md")?.body;

    return {
      key,
      headSha: clonedSha || headSha,
      workdir,
      builtAt: Date.now(),
      renderFailed,
      docs,
      machineByFqn,
      humanByFqn,
      systems,
      roles,
      profiles,
      guardrails: parseGuardrails(conventions),
      syncPolicy,
      dashboard,
      graph,
    };
  }
}
