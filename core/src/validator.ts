/**
 * The J-6 delivery gate, delegated to Python (CP-3a ruling C1): the core
 * shells out to `python -m snapshot.accept` — the same validation and
 * canonicalization library every other part of the platform uses — and
 * never parses, re-serializes, or reasons about snapshot content in
 * TypeScript. The raw request body bytes go to disk untouched; the
 * wrapper extracts `result`, validates (schema + S-1 + C-4 hashes), and
 * writes the §6 canonical serialization the core stores verbatim.
 */

import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

export interface AcceptVerdict {
  valid: boolean;
  errors?: string[];
  warnings?: string[];
  system?: string;
  snapshot_version?: string;
  source_mode?: string;
  captured_at?: string;
  connector?: { name: string; version: string };
  object_count?: number;
  sha256?: string;
  canonical_body_sha256?: string;
}

/** The gate itself failed (not the snapshot): spawn error, bad exit. */
export class ValidatorUnavailable extends Error {}

export async function acceptSnapshotDelivery(
  validatorCmd: string[],
  rawBody: Buffer,
  key: string | null = "result",
): Promise<{ verdict: AcceptVerdict; canonical: Buffer | null }> {
  const dir = await mkdtemp(path.join(tmpdir(), "cl-accept-"));
  const bodyFile = path.join(dir, "body.json");
  const outFile = path.join(dir, "canonical.json");
  try {
    await writeFile(bodyFile, rawBody);
    const argv = [
      ...validatorCmd.slice(1),
      bodyFile,
      ...(key ? ["--key", key] : []),
      "--out",
      outFile,
    ];
    const { code, stdout, stderr } = await run(validatorCmd[0]!, argv);
    if (code !== 0 && code !== 1) {
      throw new ValidatorUnavailable(
        `delivery gate exited ${code}: ${stderr.slice(0, 2000)}`,
      );
    }
    let verdict: AcceptVerdict;
    try {
      verdict = JSON.parse(stdout) as AcceptVerdict;
    } catch {
      throw new ValidatorUnavailable(
        `delivery gate produced no verdict (exit ${code}): ${stderr.slice(0, 2000)}`,
      );
    }
    if (!verdict.valid) return { verdict, canonical: null };
    const canonical = await readFile(outFile);
    return { verdict, canonical };
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function run(
  cmd: string,
  args: string[],
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
    child.stderr.on("data", (d: Buffer) => (stderr += d.toString()));
    child.on("error", (err) =>
      reject(new ValidatorUnavailable(`cannot spawn delivery gate: ${err.message}`)),
    );
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}
