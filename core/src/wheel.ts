/**
 * Vendored-wheel maintenance (sync spec §10). When the platform
 * release's wheel version differs from the KB's provenance manifest, the
 * next sync PR leads with a wheel-update commit: new wheel + rewritten
 * manifest (version, sha256, platform commit) — so the PR's own KB CI
 * run validates with the wheel that will govern after merge.
 *
 * **The carry never touches a workflow file** (R-6 option (b), ruling
 * D-96 task 2). It used to repoint `kb-ci.yml`'s install line at the new
 * wheel filename, which meant the sync identity needed `workflow` write
 * scope on the customer's repo — a token that can rewrite CI is a token
 * that can rewrite the thing checking the work. `kb-ci.yml` now reads
 * `wheel:` (and the runtime dep pins) out of `VENDOR-MANIFEST.yaml` at
 * job time, so the manifest is the single pin and the workflow is
 * static. The D-46 exception boundary narrows accordingly: wheel +
 * manifest, nothing else.
 *
 * The bootstrapped `kb-ci.yml` must therefore read the manifest. A KB
 * whose workflow still hardcodes a wheel filename keeps working (the
 * install line just names a file that is no longer there — a loud CI
 * failure, not a silent stale-wheel validation), but it must be migrated;
 * the platform emits the manifest-reading form.
 */

import { createHash } from "node:crypto";
import { copyFile, readFile, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { parse as parseYaml } from "yaml";
import type { SyncConfig } from "./config.js";

export const MANIFEST_PATH = ".github/vendor/VENDOR-MANIFEST.yaml";

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
    `runtime_deps_pinned_in: ${keep("runtime_deps_pinned_in", "this file (runtime_deps)")}`,
  ];
  // `runtime_deps` is KB-owned data the carry must not silently drop: the
  // workflow installs exactly this list, so losing it would leave CI with
  // no dependency pins at all. Preserved verbatim, never rewritten here.
  const deps = manifest?.fields.runtime_deps;
  if (Array.isArray(deps)) {
    fields.push("runtime_deps:");
    for (const dep of deps) fields.push(`  - ${String(dep)}`);
  }
  await writeFile(path.join(kbDir, MANIFEST_PATH), header + fields.join("\n") + "\n");
  touched.push(MANIFEST_PATH);

  // R-6(b): no workflow file is touched. kb-ci.yml reads `wheel:` from
  // the manifest at job time, so the manifest is the only pin and the
  // sync identity needs no `workflow` write scope.
  return touched;
}
