/**
 * Vendored-wheel maintenance (sync spec §10). When the platform
 * release's wheel version differs from the KB's provenance manifest, the
 * next sync PR leads with a wheel-update commit: new wheel + rewritten
 * manifest (version, sha256, platform commit) + the kb-ci.yml install
 * line repointed — so the PR's own KB CI run validates with the wheel
 * that will govern after merge. The D-46 exception boundary is
 * unchanged: wheel + manifest + the CI pin, nothing else.
 */

import { createHash } from "node:crypto";
import { copyFile, readFile, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { parse as parseYaml } from "yaml";
import type { SyncConfig } from "./config.js";

export const MANIFEST_PATH = ".github/vendor/VENDOR-MANIFEST.yaml";
export const KB_CI_PATH = ".github/workflows/kb-ci.yml";

export interface WheelCarry {
  fromVersion: string | null;
  toVersion: string;
  wheelBasename: string;
  oldWheelBasename: string | null;
}

export class WheelError extends Error {}

async function readManifest(
  kbDir: string,
): Promise<{ raw: string; fields: Record<string, unknown> } | null> {
  try {
    const raw = await readFile(path.join(kbDir, MANIFEST_PATH), "utf-8");
    return { raw, fields: (parseYaml(raw) ?? {}) as Record<string, unknown> };
  } catch {
    return null;
  }
}

/** null = nothing to carry (no wheel configured, or versions match). */
export async function planWheelCarry(
  cfg: SyncConfig,
  kbDir: string,
): Promise<WheelCarry | null> {
  if (!cfg.wheelPath || !cfg.wheelVersion) return null;
  const manifest = await readManifest(kbDir);
  const current = manifest?.fields.version;
  if (current === cfg.wheelVersion) return null;
  return {
    fromVersion: typeof current === "string" ? current : null,
    toVersion: cfg.wheelVersion,
    wheelBasename: path.basename(cfg.wheelPath),
    oldWheelBasename:
      typeof manifest?.fields.wheel === "string" ? manifest.fields.wheel : null,
  };
}

/** Returns the repo-relative paths the wheel commit must stage. */
export async function applyWheelCarry(
  cfg: SyncConfig,
  kbDir: string,
  carry: WheelCarry,
): Promise<string[]> {
  if (!cfg.wheelPath) throw new WheelError("no wheel configured");
  const vendorDir = path.dirname(path.join(kbDir, MANIFEST_PATH));
  const touched: string[] = [];

  const wheelDest = path.join(vendorDir, carry.wheelBasename);
  await copyFile(cfg.wheelPath, wheelDest);
  touched.push(path.posix.join(path.posix.dirname(MANIFEST_PATH), carry.wheelBasename));
  if (carry.oldWheelBasename && carry.oldWheelBasename !== carry.wheelBasename) {
    await unlink(path.join(vendorDir, carry.oldWheelBasename)).catch(() => {});
    touched.push(
      path.posix.join(path.posix.dirname(MANIFEST_PATH), carry.oldWheelBasename),
    );
  }

  const bytes = await readFile(wheelDest);
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  const manifest = await readManifest(kbDir);
  // §10 determinism (SY-1/SO-12): `built` comes from config or the wheel
  // file's own mtime — never the run's wall clock.
  const built =
    cfg.wheelBuilt ??
    (await stat(cfg.wheelPath)).mtime.toISOString().slice(0, 10);
  const keep = (key: string, fallback: string): string => {
    const value = manifest?.fields[key];
    return typeof value === "string" ? value : fallback;
  };
  // Preserve the manifest's leading comment block (its documentation is
  // KB-owned prose); rewrite only the field lines below it.
  const headerLines: string[] = [];
  for (const line of (manifest?.raw ?? "").split("\n")) {
    if (line.startsWith("#") || line.trim() === "") headerLines.push(line);
    else break;
  }
  const header = headerLines.join("\n").replace(/\n*$/, headerLines.length ? "\n\n" : "");
  const fields = [
    `package: ${keep("package", "contextlayer-snapshot")}`,
    `version: ${carry.toVersion}`,
    `wheel: ${carry.wheelBasename}`,
    `sha256: ${sha256}`,
    `platform_commit: ${cfg.platformCommit ?? "unknown"}`,
    `built: ${built}`,
    `built_by: contextlayer-sync (sync spec §10 wheel carry)`,
    `source: ${keep("source", "platform repo")}`,
    `runtime_deps_pinned_in: ${keep("runtime_deps_pinned_in", "../workflows/kb-ci.yml")}`,
  ];
  await writeFile(path.join(kbDir, MANIFEST_PATH), header + fields.join("\n") + "\n");
  touched.push(MANIFEST_PATH);

  // Repoint the KB CI install line at the new wheel filename.
  if (carry.oldWheelBasename && carry.oldWheelBasename !== carry.wheelBasename) {
    try {
      const ciPath = path.join(kbDir, KB_CI_PATH);
      const ci = await readFile(ciPath, "utf-8");
      if (ci.includes(carry.oldWheelBasename)) {
        await writeFile(
          ciPath,
          ci.split(carry.oldWheelBasename).join(carry.wheelBasename),
        );
        touched.push(KB_CI_PATH);
      }
    } catch {
      // no workflow in this KB (scratch repos) — the manifest still governs
    }
  }
  return touched;
}
