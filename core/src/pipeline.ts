/**
 * The drift-run pipeline (sync spec §5, failure semantics §6, SY-1..6).
 *
 * The TypeScript here is orchestration only (ruling C2): pinning, stage
 * sequencing, git/PR mechanics, supersede, run records, health. Every
 * deterministic artifact — diff, severity finalization, lineage
 * re-derivation, contamination scan, renders, front-matter status
 * writes — is produced by the Python package's CLI entry points against
 * the pinned clone; this module never parses stage outputs except to
 * route control flow.
 *
 * Two recorded interpretive rulings (DECISIONS D-64):
 *
 * - the diff baseline is the snapshot pinned at KB merged HEAD
 *   (`.contextlayer/snapshots/<system>.json` in the stage-1 clone), not
 *   merely the previous ops-store acceptance — SY-3's "complete
 *   currently-true picture versus merged KB HEAD" and SO-7's restatement
 *   semantics only hold under that reading;
 * - front-matter status writes (§5.9) are applied to the worktree before
 *   the machine renders (§5.8): index rows render the human sibling's
 *   status, so KB-8 at the PR head is only satisfiable when the renders
 *   see the final statuses. Both land in the same atomic PR; no
 *   externally observable artifact differs from the spec's numbering.
 */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import pg from "pg";
import {
  buildBody,
  buildLabels,
  buildTitle,
  type ChangelogInput,
  type FinalizedDiff,
  type ScanResult,
} from "./changelog.js";
import type { CoreConfig } from "./config.js";
import { withTransaction } from "./db.js";
import {
  cloneKb,
  commitAll,
  deleteRemoteBranch,
  git,
  pushBranch,
  remoteHeadSha,
  type PrInfo,
  type PrProvider,
} from "./gitkb.js";
import { recordHealthEvent } from "./health.js";
import { parsePolicy } from "./policy.js";
import { getJob } from "./queue.js";
import { getSnapshotBody } from "./snapshots.js";
import {
  consumePending,
  hasPending,
  remarkPending,
  type PendingSystem,
} from "./triggers.js";
import { ulid } from "./ulid.js";
import { applyWheelCarry, planWheelCarry } from "./wheel.js";

const SYNC_LOCK_KEY = 7312024; // deployment-global single-flight (SY-6)
const DEFINITION_KINDS = new Set(["view", "materialized_view"]);

export interface RunDeps {
  pool: pg.Pool;
  cfg: CoreConfig;
  provider: PrProvider;
  log: (msg: string, err?: unknown) => void;
}

class StageFailure extends Error {
  constructor(
    readonly stage: string,
    message: string,
    readonly severity: "error" | "warning" = "error",
    readonly extra: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

// ---------------------------------------------------------------------------
// run loop entry: single-flight + coalescing (§7)

/**
 * Acquire the deployment-global run lock and drain pending triggers —
 * each iteration is one run; triggers landing mid-run coalesce into
 * exactly one follow-up (SY-6). Returns the number of runs executed.
 */
export async function runPendingRuns(deps: RunDeps): Promise<number> {
  const client = await deps.pool.connect();
  let runs = 0;
  try {
    const { rows } = await client.query<{ ok: boolean }>(
      `SELECT pg_try_advisory_lock($1) AS ok`,
      [SYNC_LOCK_KEY],
    );
    if (!rows[0]!.ok) return 0;
    try {
      while (await hasPending(deps.pool)) {
        await executeRun(deps);
        runs += 1;
      }
    } finally {
      await client.query(`SELECT pg_advisory_unlock($1)`, [SYNC_LOCK_KEY]);
    }
  } finally {
    client.release();
  }
  return runs;
}

/** Crash recovery: a deployment restart marks torso runs failed. */
export async function failStaleRunningRuns(pool: pg.Pool): Promise<void> {
  const { rows } = await pool.query<{ run_id: string }>(
    `UPDATE runs SET outcome = 'failed', finished_at = now(),
            detail = detail || '{"stage": "interrupted"}'::jsonb
      WHERE outcome = 'running'
      RETURNING run_id`,
  );
  for (const row of rows) {
    await recordHealthEvent(pool, {
      kind: "sync_run_failed",
      severity: "error",
      detail: { run_id: row.run_id, stage: "interrupted", message: "deployment restarted mid-run" },
    });
  }
}

// ---------------------------------------------------------------------------
// stage plumbing

function runCli(
  argv: string[],
  cwd: string,
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(argv[0]!, argv.slice(1), {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
    child.stderr.on("data", (d: Buffer) => (stderr += d.toString()));
    child.on("error", (err) => reject(new Error(`cannot spawn ${argv[0]}: ${err.message}`)));
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

async function pythonStage(
  deps: RunDeps,
  stage: string,
  args: string[],
  extra: Record<string, unknown> = {},
): Promise<string> {
  const argv = [...deps.cfg.sync.pythonCmd, ...args];
  const { code, stdout, stderr } = await runCli(argv, deps.cfg.sync.workdir);
  if (code !== 0) {
    throw new StageFailure(stage, stderr.trim() || `exited ${code}`, "error", {
      product_bug: true,
      ...extra,
    });
  }
  return stdout;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

interface AcquiredSystem {
  system: string;
  jobId: string;
  snapshotId: string;
  triggers: PendingSystem["triggers"];
  snapshotFile: string;
}

// ---------------------------------------------------------------------------
// the run (§5 stages 1–11)

export async function executeRun(deps: RunDeps): Promise<string> {
  const { pool, cfg, provider, log } = deps;
  const runId = ulid();
  const branch = `sync/${runId}`;
  const startedAt = new Date();
  const workdir = path.join(cfg.sync.workdir, `run-${runId}`);
  const kbDir = path.join(workdir, "kb");

  // ---- stage 1: pin -------------------------------------------------------
  const pending = await withTransaction(pool, (client) => consumePending(client));
  if (pending.length === 0) return "no-op";
  await pool.query(
    `INSERT INTO runs (run_id, triggers, systems, kb_ref, snapshot_refs, outcome, started_at)
     VALUES ($1, $2::jsonb, $3::jsonb, '', '{}'::jsonb, 'running', $4)`,
    [
      runId,
      JSON.stringify(pending.map((p) => ({ system: p.system, triggers: p.triggers }))),
      JSON.stringify({ included: pending.map((p) => p.system), excluded: [] }),
      startedAt,
    ],
  );

  const finish = async (
    outcome: string,
    fields: {
      prUrl?: string;
      detail?: Record<string, unknown>;
      systems?: Record<string, unknown>;
      kbRef?: string;
      snapshotRefs?: Record<string, unknown>;
      counts?: Record<string, unknown>;
      contaminated?: unknown[];
    } = {},
  ) => {
    await pool.query(
      `UPDATE runs SET outcome = $2, pr_url = $3, kb_ref = COALESCE($4, kb_ref),
              snapshot_refs = COALESCE($5::jsonb, snapshot_refs),
              classification_counts = $6::jsonb, contaminated_docs = $7::jsonb,
              systems = COALESCE($8::jsonb, systems),
              detail = detail || $9::jsonb,
              finished_at = now(),
              duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::integer
        WHERE run_id = $1`,
      [
        runId,
        outcome,
        fields.prUrl ?? null,
        fields.kbRef ?? null,
        fields.snapshotRefs ? JSON.stringify(fields.snapshotRefs) : null,
        fields.counts ? JSON.stringify(fields.counts) : null,
        fields.contaminated ? JSON.stringify(fields.contaminated) : null,
        fields.systems ? JSON.stringify(fields.systems) : null,
        JSON.stringify({ branch, ...fields.detail }),
      ],
    );
    log(`sync run ${runId}: ${outcome}${fields.prUrl ? ` — ${fields.prUrl}` : ""}`);
    return outcome;
  };

  try {
    await mkdir(workdir, { recursive: true });
    const kbRef = await cloneKb(cfg.sync, kbDir);

    let budgetS = cfg.sync.acquisitionBudgetS;
    try {
      const policy = parsePolicy(
        await readFile(path.join(kbDir, ".contextlayer", "sync-policy.yaml"), "utf-8"),
      );
      if (policy.acquisitionBudgetS !== null) budgetS = policy.acquisitionBudgetS;
    } catch {
      // no policy in this KB: config default stands (SO-D)
    }

    // ---- stage 2: acquire (SY-6 exclusion locality) -----------------------
    const deadline = startedAt.getTime() + budgetS * 1000;
    const included: AcquiredSystem[] = [];
    const excluded: { system: string; reason: string }[] = [];
    const exclude = async (system: string, reason: string, jobId?: string | null) => {
      excluded.push({ system, reason });
      await recordHealthEvent(pool, {
        kind: "sync_system_excluded",
        severity: "warning",
        system,
        jobId: jobId ?? null,
        detail: { run_id: runId, reason },
      });
    };
    for (const p of pending) {
      if (!p.job_id) {
        await exclude(p.system, "trigger enqueued no snapshot job");
        continue;
      }
      for (;;) {
        const job = await getJob(pool, p.job_id);
        if (!job) {
          await exclude(p.system, `snapshot job ${p.job_id} vanished`, p.job_id);
          break;
        }
        if (job.state === "succeeded") {
          const snapshotId = (job.result_meta as { snapshot_id?: string } | null)
            ?.snapshot_id;
          if (!snapshotId) {
            await exclude(p.system, "job succeeded without a snapshot", p.job_id);
            break;
          }
          const body = await getSnapshotBody(pool, snapshotId);
          if (!body) {
            await exclude(p.system, `accepted snapshot ${snapshotId} pruned`, p.job_id);
            break;
          }
          const file = path.join(workdir, `new-${p.system}.json`);
          await writeFile(file, body);
          included.push({
            system: p.system,
            jobId: p.job_id,
            snapshotId,
            triggers: p.triggers,
            snapshotFile: file,
          });
          break;
        }
        if (job.state === "dead_lettered" || job.state === "cancelled") {
          await exclude(p.system, `snapshot job ${job.state}`, p.job_id);
          break;
        }
        if (Date.now() > deadline) {
          await exclude(
            p.system,
            `acquisition timed out after ${budgetS}s (job ${job.state})`,
            p.job_id,
          );
          break;
        }
        await sleep(cfg.sync.acquirePollMs);
      }
    }
    if (included.length === 0) {
      await recordHealthEvent(pool, {
        kind: "sync_run_failed",
        severity: "error",
        detail: { run_id: runId, stage: "acquire", message: "no system survived acquisition" },
      });
      return await finish("failed_acquisition", {
        systems: { included: [], excluded },
        kbRef,
      });
    }

    // SY-3 restatement: the PR must state the complete currently-true
    // picture versus merged HEAD — supersede would otherwise drop the
    // unmerged drift of systems this run was not triggered for. Any
    // configured system whose latest accepted snapshot differs from its
    // HEAD pin rides along on its stored acceptance (no new job).
    const restated: string[] = [];
    const { rows: configured } = await pool.query<{ system: string }>(
      `SELECT system FROM sync_systems ORDER BY system`,
    );
    for (const { system } of configured) {
      if (included.some((s) => s.system === system)) continue;
      const { rows } = await pool.query<{ snapshot_id: string; sha256: string }>(
        `SELECT snapshot_id, sha256 FROM accepted_snapshots
          WHERE system = $1 ORDER BY accepted_at DESC, snapshot_id DESC LIMIT 1`,
        [system],
      );
      if (!rows[0]) continue;
      const pin = await readFile(
        path.join(kbDir, ".contextlayer", "snapshots", `${system}.json`),
      ).catch(() => null);
      if (pin && createHash("sha256").update(pin).digest("hex") === rows[0].sha256) {
        continue; // HEAD already reflects this acceptance
      }
      const body = await getSnapshotBody(pool, rows[0].snapshot_id);
      if (!body) continue;
      const file = path.join(workdir, `new-${system}.json`);
      await writeFile(file, body);
      included.push({
        system,
        jobId: "",
        snapshotId: rows[0].snapshot_id,
        triggers: [],
        snapshotFile: file,
      });
      restated.push(system);
    }
    const systemsRecord = {
      included: included.map((s) => s.system),
      excluded,
      restated,
    };

    // ---- stage 3: diff vs the HEAD-pinned baseline ------------------------
    const diffs = new Map<string, FinalizedDiff>();
    const diffFiles = new Map<string, string>();
    const snapshotRefs: Record<string, unknown> = {};
    for (const s of included) {
      const pinPath = path.join(kbDir, ".contextlayer", "snapshots", `${s.system}.json`);
      let baselineFile = pinPath;
      let baselinePinned = true;
      try {
        await readFile(pinPath);
      } catch {
        baselineFile = path.join(workdir, `baseline-${s.system}.json`);
        await writeFile(baselineFile, JSON.stringify({ system: s.system, objects: [] }));
        baselinePinned = false;
      }
      const stdout = await pythonStage(
        deps,
        "diff",
        ["-m", "snapshot.diff", baselineFile, s.snapshotFile],
        { system: s.system },
      );
      const diffFile = path.join(workdir, `diff-${s.system}.json`);
      await writeFile(diffFile, stdout);
      diffs.set(s.system, JSON.parse(stdout) as FinalizedDiff);
      diffFiles.set(s.system, diffFile);
      snapshotRefs[s.system] = {
        snapshot_id: s.snapshotId,
        job_id: s.jobId,
        baseline: baselinePinned ? `${s.system}.json@${kbRef}` : null,
      };
    }
    const changed = included.filter((s) => !diffs.get(s.system)!.empty);

    // ---- gateway attestations (CP-7, F-3/F-4) -----------------------------
    // Publishes since the last regeneration are graph inputs in their own
    // right: any attestation whose edge is not in the HEAD graph makes a
    // regeneration pending, even when no snapshot moved.
    const gatewayRows = await gatewayAttestations(deps.pool);
    const gatewayPending = await (async () => {
      if (gatewayRows.length === 0) return false;
      const headText = await readFile(path.join(kbDir, "lineage", "graph.json"), "utf-8")
        .catch(() => null);
      const headEdges = headText
        ? ((JSON.parse(headText) as { edges?: { id?: string }[] }).edges ?? [])
        : [];
      const ids = new Set(headEdges.map((e) => e.id));
      return gatewayRows.some((row) => !ids.has(gatewayEdgeId(row)));
    })();

    // ---- wheel plan + no-op short-circuit (§5.3, §10) ---------------------
    const wheelCarry = await planWheelCarry(cfg.sync, kbDir);
    const manual = pending.some((p) => p.triggers.some((t) => t.kind === "manual"));
    if (changed.length === 0 && !(wheelCarry && manual) && !gatewayPending) {
      return await finish("no-op", {
        systems: systemsRecord,
        kbRef,
        snapshotRefs,
        counts: countClassifications(diffs),
      });
    }

    let scan: ScanResult | null = null;
    if (changed.length > 0) {
      // ---- pin updates: the PR's own render/CI inputs (KB §3, D-49) ------
      for (const s of changed) {
        const pinPath = path.join(kbDir, ".contextlayer", "snapshots", `${s.system}.json`);
        await mkdir(path.dirname(pinPath), { recursive: true });
        await writeFile(pinPath, await readFile(s.snapshotFile));
      }

      // ---- stage 5: lineage re-derivation (SY-4) -------------------------
      const graphPath = path.join(kbDir, "lineage", "graph.json");
      const headGraph = await readFile(graphPath, "utf-8").catch(() => null);
      const headGraphFile = path.join(workdir, "head-graph.json");
      await writeFile(
        headGraphFile,
        headGraph ?? JSON.stringify({ graph_version: "1", nodes: [], edges: [] }),
      );
      const required =
        lineageRequired(
          [...diffs.values()],
          headGraph ? (JSON.parse(headGraph) as { nodes: { id: string }[] }) : null,
        ) || gatewayPending;
      if (required) {
        const pinDir = path.join(kbDir, ".contextlayer", "snapshots");
        const inputs = (await readdir(pinDir))
          .filter((f) => f.endsWith(".json"))
          .sort()
          .map((f) => path.join(pinDir, f));
        const argv = ["-m", "lineage", ...inputs, "--kb", kbDir,
          ...(await attestationArgs(gatewayRows, workdir))];
        const { code, stderr } = await runCli(
          [...cfg.sync.pythonCmd, ...argv],
          cfg.sync.workdir,
        );
        if (code !== 0) {
          // §6: named failing definition; HEAD graph untouched (clone only)
          throw new StageFailure("lineage", stderr.trim() || `exited ${code}`, "error", {
            named_definition: stderr.trim().slice(0, 500),
          });
        }
      }

      // ---- stage 6: severity finalization (§7 note ³) --------------------
      const finalFiles: string[] = [];
      for (const s of changed) {
        const finalFile = path.join(workdir, `final-${s.system}.json`);
        const args = ["-m", "lineage.severity", diffFiles.get(s.system)!, "--out", finalFile];
        if (required) args.push("--old-graph", headGraphFile, "--new-graph", graphPath);
        await pythonStage(deps, "severity", args, { system: s.system });
        finalFiles.push(finalFile);
        diffs.set(
          s.system,
          JSON.parse(await readFile(finalFile, "utf-8")) as FinalizedDiff,
        );
      }

      // ---- stage 7: contamination scan (SY-4: never PR without it) -------
      const scanGraphFile = (await readFile(graphPath).catch(() => null))
        ? graphPath
        : headGraphFile;
      const scanFile = path.join(workdir, "scan.json");
      const scanArgs = ["-m", "lineage.scan", "--kb", kbDir, "--graph", scanGraphFile,
        "--out", scanFile];
      for (const f of finalFiles) scanArgs.push("--diff", f);
      await pythonStage(deps, "scan", scanArgs);
      scan = JSON.parse(await readFile(scanFile, "utf-8")) as ScanResult;

      // ---- stage 9 writes, then stage 8 renders (see module docstring) ---
      const instructions = [
        ...scan.contaminated.map((c) => ({
          doc: c.doc,
          status: "contaminated",
          contamination: c.contamination,
        })),
        ...scan.stale.map((s) => ({ doc: s.doc, status: "stale" })),
      ];
      const instrFile = path.join(workdir, "statuses.json");
      await writeFile(instrFile, JSON.stringify(instructions, null, 2));
      await pythonStage(deps, "statuses", ["-m", "generator.statuses", "--kb", kbDir, instrFile]);

      const renderInputs = changed.map((s) =>
        path.join(kbDir, ".contextlayer", "snapshots", `${s.system}.json`),
      );
      await pythonStage(deps, "regenerate", ["-m", "generator.render", ...renderInputs, "--out", kbDir]);
      // KB-8 in-run self-check: a second render must be a byte no-op
      await git(cfg.sync, ["add", "-A"], kbDir);
      await pythonStage(deps, "regenerate", ["-m", "generator.render", ...renderInputs, "--out", kbDir]);
      const drift = await git(cfg.sync, ["diff", "--name-only"], kbDir);
      if (drift.trim() !== "") {
        throw new StageFailure(
          "regenerate",
          `KB-8 in-run self-check failed — second render changed: ${drift.trim()}`,
          "error",
          { product_bug: true },
        );
      }
    } else if (gatewayPending) {
      // ---- graph-only regeneration (CP-7, F-4) --------------------------
      // No snapshot moved, but publishes happened since the last graph:
      // land the report nodes and gateway edges as their own PR. No
      // contamination scan or renders — there is no diff to scan and no
      // machine doc to re-render; the additive BI-side nodes cannot
      // contaminate anything.
      const pinDir = path.join(kbDir, ".contextlayer", "snapshots");
      const inputs = (await readdir(pinDir).catch(() => [] as string[]))
        .filter((f) => f.endsWith(".json"))
        .sort()
        .map((f) => path.join(pinDir, f));
      if (inputs.length > 0) {
        const argv = ["-m", "lineage", ...inputs, "--kb", kbDir,
          ...(await attestationArgs(gatewayRows, workdir))];
        const { code, stderr } = await runCli([...cfg.sync.pythonCmd, ...argv], cfg.sync.workdir);
        if (code !== 0) {
          throw new StageFailure("lineage", stderr.trim() || `exited ${code}`, "error", {
            named_definition: stderr.trim().slice(0, 500),
          });
        }
      }
    }

    // ---- stage 10: wheel commit first, then content, then push + PR ------
    const input: ChangelogInput = {
      diffs: [...diffs.values()].sort((a, b) => (a.system < b.system ? -1 : 1)),
      scan,
      wheel: wheelCarry
        ? { fromVersion: wheelCarry.fromVersion, toVersion: wheelCarry.toVersion }
        : null,
      excluded,
      graphOnly: changed.length === 0 && gatewayPending,
    };
    const title = buildTitle(input);

    if (wheelCarry) {
      const touched = await applyWheelCarry(cfg.sync, kbDir, wheelCarry);
      await git(cfg.sync, ["add", "-A", "--", ...touched], kbDir);
      // pathspec-limited commit: the §5.8 self-check staged the whole
      // tree, and the wheel commit must lead with *only* its files (§10)
      await git(
        cfg.sync,
        [
          "-c", `user.name=${cfg.sync.committerName}`,
          "-c", `user.email=${cfg.sync.committerEmail}`,
          "commit", "--quiet", "-m",
          `sync: vendored validation wheel ${wheelCarry.toVersion} (platform ${cfg.sync.platformCommit ?? "unknown"})`,
          "--", ...touched,
        ],
        kbDir,
      );
    }
    const committed = await commitAll(cfg.sync, kbDir, title);
    if (!committed && !wheelCarry) {
      return await finish("no-op", {
        systems: systemsRecord, kbRef, snapshotRefs,
        counts: countClassifications(diffs),
        detail: { note: "diff non-empty but produced no byte changes" },
      });
    }

    let prInfo: PrInfo | null = null;
    let lastError: unknown = null;
    for (let attempt = 1; attempt <= cfg.sync.prRetries; attempt += 1) {
      const remote = await remoteHeadSha(cfg.sync).catch((err) => {
        lastError = err;
        return null;
      });
      if (remote === null) {
        await sleep(cfg.sync.prRetryBaseMs * attempt);
        continue;
      }
      if (remote !== kbRef) {
        // HEAD moved mid-run: never rebase computed artifacts (§5) —
        // coalesce a fresh run against the new HEAD.
        await remarkPending(pool, pending);
        await recordHealthEvent(pool, {
          kind: "sync_head_moved",
          severity: "info",
          detail: { run_id: runId, pinned: kbRef, head: remote },
        });
        return await finish("retry_head_moved", {
          systems: systemsRecord, kbRef, snapshotRefs,
          counts: countClassifications(diffs),
        });
      }
      try {
        await pushBranch(cfg.sync, kbDir, branch);
        prInfo = await provider.openPr({
          branch,
          title,
          body: buildBody(input),
          labels: buildLabels(input),
        });
        break;
      } catch (err) {
        lastError = err;
        await sleep(cfg.sync.prRetryBaseMs * attempt);
      }
    }
    if (!prInfo) {
      await deleteRemoteBranch(cfg.sync, branch);
      throw new StageFailure(
        "pr",
        `git/provider failure after ${cfg.sync.prRetries} attempts: ${(lastError as Error)?.message}`,
        "warning",
      );
    }

    // SY-3 supersede: only after successful PR creation (§6)
    const priors = (await provider.listOpenSyncPrs()).filter(
      (pr) => pr.number !== prInfo!.number,
    );
    for (const prior of priors) {
      await provider.closePr(
        prior,
        `Superseded by ${prInfo.url} (\`${branch}\`): that PR restates the complete ` +
          `currently-true drift picture versus merged HEAD — snapshots are absolute ` +
          `states, so nothing from this PR is lost (SY-3).`,
      );
      await deleteRemoteBranch(cfg.sync, prior.branch);
    }

    // ---- stage 11: record -------------------------------------------------
    return await finish("succeeded", {
      prUrl: prInfo.url,
      systems: systemsRecord,
      kbRef,
      snapshotRefs,
      counts: countClassifications(diffs),
      contaminated: scan?.contaminated.map((c) => ({ doc: c.doc, contamination: c.contamination })) ?? [],
      detail: {
        superseded: priors.map((p) => p.url),
        ...(wheelCarry ? { wheel: wheelCarry.toVersion } : {}),
        // D-98 task 0 (flagged at D-97.1): a run with no snapshot drift is
        // not necessarily a wheel carry — say which shape it actually was,
        // because `runs` is read by ops and the future U-10 view.
        ...(changed.length === 0
          ? { wheel_only: !!wheelCarry, graph_only: gatewayPending }
          : {}),
      },
    });
  } catch (err) {
    const failure =
      err instanceof StageFailure
        ? err
        : new StageFailure("internal", (err as Error).message ?? String(err));
    await recordHealthEvent(pool, {
      kind: failure.stage === "lineage" ? "sync_lineage_failed"
        : failure.stage === "pr" ? "sync_git_failed"
        : "sync_run_failed",
      severity: failure.severity,
      detail: {
        run_id: runId,
        stage: failure.stage,
        message: failure.message.slice(0, 2000),
        ...failure.extra,
      },
    });
    return await finish("failed", {
      detail: { stage: failure.stage, error: failure.message.slice(0, 2000) },
    });
  } finally {
    await rm(workdir, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------------------

interface GatewayAttestationRow {
  source_fqn: string;
  target_fqn: string;
  operation: string;
  evidence: Record<string, unknown>;
  source_meta: Record<string, unknown> | null;
  target_meta: Record<string, unknown> | null;
}

/** Ordered export of the publish-gateway attestations (F-3/F-4). */
async function gatewayAttestations(pool: pg.Pool): Promise<GatewayAttestationRow[]> {
  const { rows } = await pool.query<GatewayAttestationRow>(
    `SELECT source_fqn, target_fqn, operation, evidence, source_meta, target_meta
       FROM lineage_attestations
      ORDER BY source_fqn, target_fqn, operation`,
  );
  return rows;
}

/** F-1 edge id, TS side — must match lineage/graph.py `edge_id`. */
function gatewayEdgeId(row: GatewayAttestationRow): string {
  const digest = createHash("sha256")
    .update(`${row.source_fqn}\n${row.target_fqn}\n${row.operation}`, "utf-8")
    .digest("hex");
  return `sha256:${digest}`;
}

/** Write the attestation export and return the `--attestations` argv. */
async function attestationArgs(rows: GatewayAttestationRow[], workdir: string): Promise<string[]> {
  if (rows.length === 0) return [];
  const file = path.join(workdir, "gateway-attestations.json");
  await writeFile(
    file,
    JSON.stringify(
      rows.map((row) => ({
        source: row.source_fqn,
        target: row.target_fqn,
        operation: row.operation,
        evidence: row.evidence,
        ...(row.source_meta ? { source_meta: row.source_meta } : {}),
        ...(row.target_meta ? { target_meta: row.target_meta } : {}),
      })),
    ),
  );
  return ["--attestations", file];
}

/** §5.5: re-derivation required iff a hash-included definition changed,
 * or an object participating in the current graph was added/removed
 * (definition-bearing kinds always participate on arrival/departure). */
export function lineageRequired(
  diffs: FinalizedDiff[],
  headGraph: { nodes: { id: string }[] } | null,
): boolean {
  const nodeIds = new Set((headGraph?.nodes ?? []).map((n) => n.id));
  for (const diff of diffs) {
    for (const obj of diff.changed_structural ?? []) {
      if ((obj.sub_diffs ?? []).some((s) => s.change === "definition_changed")) {
        return true;
      }
    }
    for (const obj of [...(diff.added ?? []), ...(diff.removed ?? [])]) {
      if (DEFINITION_KINDS.has(obj.identity.kind)) return true;
      if (nodeIds.has(`${diff.system}.${obj.identity.schema}.${obj.identity.name}`)) {
        return true;
      }
    }
  }
  return false;
}

function countClassifications(diffs: Map<string, FinalizedDiff>): Record<string, unknown> {
  const counts: Record<string, unknown> = {};
  for (const [system, diff] of [...diffs.entries()].sort()) {
    const structural = diff.changed_structural ?? [];
    counts[system] = {
      added: (diff.added ?? []).length,
      removed: (diff.removed ?? []).length,
      changed_structural: structural.length,
      changed_metadata_only: (diff.changed_metadata_only ?? []).length,
      breaking:
        (diff.removed ?? []).length +
        structural.filter((o) => o.severity === "breaking").length,
      additive:
        (diff.added ?? []).length +
        structural.filter((o) => o.severity === "additive").length,
      additive_with_note: structural.filter((o) => o.severity === "additive-with-note")
        .length,
    };
  }
  return counts;
}
