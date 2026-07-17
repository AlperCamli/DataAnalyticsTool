/**
 * Git + PR mechanics (CP-3b ruling D2): shell git plus a provider REST
 * API behind a two-operation interface — push branch / open+close PR.
 *
 * Auth is a fine-grained PAT for the contextlayer-sync machine account,
 * injected per git invocation through GIT_CONFIG_* environment variables
 * (an `http.extraheader` Authorization header) so the token never lands
 * in argv or in any .git/config on disk. Provider REST uses the same
 * token as a Bearer header.
 *
 * Two providers: `github` (real deployments) and `local` (a bare repo on
 * the filesystem with a JSON PR store beside it) — the drill fixture and
 * the SO conformance tests run the identical pipeline against `local`.
 */

import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import type { SyncConfig } from "./config.js";

export class GitError extends Error {}
export class ProviderError extends Error {}

// ---------------------------------------------------------------------------
// shell git

export function gitEnv(cfg: SyncConfig): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...process.env };
  if (cfg.gitToken && /^https?:\/\//.test(cfg.gitRemote)) {
    const basic = Buffer.from(`x-access-token:${cfg.gitToken}`).toString("base64");
    env.GIT_CONFIG_COUNT = "1";
    env.GIT_CONFIG_KEY_0 = "http.extraheader";
    env.GIT_CONFIG_VALUE_0 = `AUTHORIZATION: basic ${basic}`;
  }
  return env;
}

export function git(
  cfg: SyncConfig,
  args: string[],
  cwd?: string,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn("git", args, { cwd, env: gitEnv(cfg), stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
    child.stderr.on("data", (d: Buffer) => (stderr += d.toString()));
    child.on("error", (err) => reject(new GitError(`git ${args[0]}: ${err.message}`)));
    child.on("close", (code) => {
      if (code === 0) resolve(stdout);
      else reject(new GitError(`git ${args.join(" ")} exited ${code}: ${stderr.slice(0, 4000)}`));
    });
  });
}

/** Clone the KB at the base branch; returns the pinned HEAD sha (§5.1). */
export async function cloneKb(cfg: SyncConfig, dest: string): Promise<string> {
  await git(cfg, ["clone", "--no-tags", "--branch", cfg.baseBranch, cfg.gitRemote, dest]);
  return (await git(cfg, ["rev-parse", "HEAD"], dest)).trim();
}

export async function remoteHeadSha(cfg: SyncConfig): Promise<string> {
  const out = await git(cfg, ["ls-remote", cfg.gitRemote, `refs/heads/${cfg.baseBranch}`]);
  const sha = out.split(/\s/)[0];
  if (!sha) throw new GitError(`no ${cfg.baseBranch} branch at ${cfg.gitRemote}`);
  return sha;
}

/**
 * Read one file from remote HEAD without keeping a checkout — the E2
 * "policy from KB HEAD once per tick" read. A bare cache repo under the
 * workdir holds the fetched objects.
 */
export async function readRemoteFile(
  cfg: SyncConfig,
  relPath: string,
): Promise<{ sha: string; text: string }> {
  const cache = path.join(cfg.workdir, "kb-cache.git");
  await mkdir(cfg.workdir, { recursive: true });
  try {
    await git(cfg, ["rev-parse", "--is-bare-repository"], cache);
  } catch {
    await git(cfg, ["init", "--bare", "--quiet", cache]);
  }
  await git(cfg, ["fetch", "--quiet", cfg.gitRemote, cfg.baseBranch], cache);
  const sha = (await git(cfg, ["rev-parse", "FETCH_HEAD"], cache)).trim();
  const text = await git(cfg, ["cat-file", "-p", `${sha}:${relPath}`], cache);
  return { sha, text };
}

/** Stage everything and commit as the sync identity; false = nothing to commit. */
export async function commitAll(
  cfg: SyncConfig,
  workdir: string,
  message: string,
): Promise<boolean> {
  await git(cfg, ["add", "-A"], workdir);
  const staged = await git(cfg, ["status", "--porcelain"], workdir);
  if (staged.trim() === "") return false;
  await git(
    cfg,
    [
      "-c", `user.name=${cfg.committerName}`,
      "-c", `user.email=${cfg.committerEmail}`,
      "commit", "--quiet", "-m", message,
    ],
    workdir,
  );
  return true;
}

export async function pushBranch(
  cfg: SyncConfig,
  workdir: string,
  branch: string,
): Promise<void> {
  await git(cfg, ["push", "--quiet", "origin", `HEAD:refs/heads/${branch}`], workdir);
}

export async function deleteRemoteBranch(cfg: SyncConfig, branch: string): Promise<void> {
  await git(cfg, ["push", "--quiet", cfg.gitRemote, `:refs/heads/${branch}`]).catch(() => {
    // best-effort cleanup: the branch may never have been pushed
  });
}

// ---------------------------------------------------------------------------
// PR provider (the REST half of D2)

export interface OpenPrArgs {
  branch: string;
  title: string;
  body: string;
  labels: string[];
}

export interface PrInfo {
  number: number;
  url: string;
  branch: string;
}

export interface MergedPr {
  number: number;
  url: string;
  branch: string;
  body: string;
  mergedAt: string;
}

export interface PrProvider {
  openPr(args: OpenPrArgs): Promise<PrInfo>;
  /** Open PRs whose head branch is the orchestrator's own (`sync/…`). */
  listOpenSyncPrs(): Promise<PrInfo[]>;
  closePr(pr: PrInfo, comment: string): Promise<void>;
  /** Merged PRs (any branch) newer than the cursor — the CL-Resolves
   * loop-closure input (ledger spec §9, LED-R4). */
  listMergedPrs(sinceIso: string | null): Promise<MergedPr[]>;
}

export function createProvider(cfg: SyncConfig): PrProvider {
  return cfg.gitProvider === "github" ? new GithubProvider(cfg) : new LocalProvider(cfg);
}

class GithubProvider implements PrProvider {
  private readonly repo: string; // owner/name

  constructor(private readonly cfg: SyncConfig) {
    const match = /^https?:\/\/[^/]+\/([^/]+\/[^/]+?)(?:\.git)?\/?$/.exec(cfg.gitRemote);
    if (!match) throw new ProviderError(`cannot parse owner/repo from ${cfg.gitRemote}`);
    this.repo = match[1]!;
  }

  private async api(
    method: string,
    apiPath: string,
    body?: unknown,
  ): Promise<{ status: number; json: unknown }> {
    const response = await fetch(`${this.cfg.gitApiBase}${apiPath}`, {
      method,
      headers: {
        authorization: `Bearer ${this.cfg.gitToken}`,
        accept: "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
        ...(body !== undefined ? { "content-type": "application/json" } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    const text = await response.text();
    return { status: response.status, json: text ? JSON.parse(text) : null };
  }

  async openPr(args: OpenPrArgs): Promise<PrInfo> {
    const { status, json } = await this.api("POST", `/repos/${this.repo}/pulls`, {
      title: args.title,
      head: args.branch,
      base: this.cfg.baseBranch,
      body: args.body,
    });
    if (status !== 201) {
      throw new ProviderError(`open PR failed (${status}): ${JSON.stringify(json)}`);
    }
    const pr = json as { number: number; html_url: string };
    if (args.labels.length > 0) {
      await this.api("POST", `/repos/${this.repo}/issues/${pr.number}/labels`, {
        labels: args.labels,
      });
    }
    return { number: pr.number, url: pr.html_url, branch: args.branch };
  }

  async listOpenSyncPrs(): Promise<PrInfo[]> {
    const { status, json } = await this.api(
      "GET",
      `/repos/${this.repo}/pulls?state=open&base=${this.cfg.baseBranch}&per_page=100`,
    );
    if (status !== 200) {
      throw new ProviderError(`list PRs failed (${status}): ${JSON.stringify(json)}`);
    }
    return (json as { number: number; html_url: string; head: { ref: string } }[])
      .filter((pr) => pr.head.ref.startsWith("sync/"))
      .map((pr) => ({ number: pr.number, url: pr.html_url, branch: pr.head.ref }));
  }

  async closePr(pr: PrInfo, comment: string): Promise<void> {
    await this.api("POST", `/repos/${this.repo}/issues/${pr.number}/comments`, {
      body: comment,
    });
    const { status } = await this.api("PATCH", `/repos/${this.repo}/pulls/${pr.number}`, {
      state: "closed",
    });
    if (status !== 200) throw new ProviderError(`close PR #${pr.number} failed (${status})`);
  }

  async listMergedPrs(sinceIso: string | null): Promise<MergedPr[]> {
    const { status, json } = await this.api(
      "GET",
      `/repos/${this.repo}/pulls?state=closed&base=${this.cfg.baseBranch}&sort=updated&direction=desc&per_page=50`,
    );
    if (status !== 200) {
      throw new ProviderError(`list merged PRs failed (${status}): ${JSON.stringify(json)}`);
    }
    return (
      json as { number: number; html_url: string; head: { ref: string }; body: string | null; merged_at: string | null }[]
    )
      .filter((pr) => pr.merged_at !== null && (sinceIso === null || pr.merged_at > sinceIso))
      .map((pr) => ({
        number: pr.number,
        url: pr.html_url,
        branch: pr.head.ref,
        body: pr.body ?? "",
        mergedAt: pr.merged_at!,
      }));
  }
}

/**
 * Local provider: PRs live in `<remote minus .git>.prs.json` beside the
 * bare repo. Same observable semantics as the GitHub provider so the
 * pipeline under test is byte-for-byte the deployed pipeline.
 */
interface LocalPrRecord {
  number: number;
  url: string;
  branch: string;
  title: string;
  body: string;
  labels: string[];
  state: "open" | "closed" | "merged";
  merged_at?: string;
  comments: string[];
}

class LocalProvider implements PrProvider {
  private readonly store: string;

  constructor(cfg: SyncConfig) {
    this.store = cfg.gitRemote.replace(/\/$/, "").replace(/\.git$/, "") + ".prs.json";
  }

  private async load(): Promise<{ next: number; prs: LocalPrRecord[] }> {
    try {
      return JSON.parse(await readFile(this.store, "utf-8"));
    } catch {
      return { next: 1, prs: [] };
    }
  }

  private async save(data: { next: number; prs: LocalPrRecord[] }): Promise<void> {
    await writeFile(this.store, JSON.stringify(data, null, 2) + "\n");
  }

  async openPr(args: OpenPrArgs): Promise<PrInfo> {
    const data = await this.load();
    const record: LocalPrRecord = {
      number: data.next,
      url: `local-pr://${data.next}`,
      branch: args.branch,
      title: args.title,
      body: args.body,
      labels: args.labels,
      state: "open",
      comments: [],
    };
    data.next += 1;
    data.prs.push(record);
    await this.save(data);
    return { number: record.number, url: record.url, branch: record.branch };
  }

  async listOpenSyncPrs(): Promise<PrInfo[]> {
    const data = await this.load();
    return data.prs
      .filter((pr) => pr.state === "open" && pr.branch.startsWith("sync/"))
      .map((pr) => ({ number: pr.number, url: pr.url, branch: pr.branch }));
  }

  async closePr(pr: PrInfo, comment: string): Promise<void> {
    const data = await this.load();
    const record = data.prs.find((p) => p.number === pr.number);
    if (!record) throw new ProviderError(`no local PR #${pr.number}`);
    record.state = "closed";
    record.comments.push(comment);
    await this.save(data);
  }

  async listMergedPrs(sinceIso: string | null): Promise<MergedPr[]> {
    const data = await this.load();
    return data.prs
      .filter((pr) => pr.state === "merged" && (sinceIso === null || (pr.merged_at ?? "") > sinceIso))
      .map((pr) => ({
        number: pr.number,
        url: pr.url,
        branch: pr.branch,
        body: pr.body,
        mergedAt: pr.merged_at ?? "",
      }));
  }
}
