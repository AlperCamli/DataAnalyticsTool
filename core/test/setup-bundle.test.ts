/**
 * A-2: setup delivery as a product surface (dashboard spec §3 "Setup",
 * register items PA-1 and PA-2).
 *
 * Two gate clauses live here.
 *
 * **PA-1** — an authenticated download of the requester's *own* bundle,
 * authorized server-side against their profile binding, carrying no
 * credential. The no-credential half is asserted the way JC-8 asserts
 * it for the job protocol: canary secrets are in the process
 * environment *during the compile*, and the archive's bytes are
 * searched for them.
 *
 * **PA-2** — the 2026-07-29 failure shape, repeated exactly: compile a
 * bundle, then grant the profile a tool it did not have, then connect a
 * session running the stale bundle. That day the session read its
 * CLAUDE.md, concluded it could not publish, and filed a gap instead of
 * building the report. Here the server tells it, at connection, that
 * its setup is out of date — and the fresh bundle it points at carries
 * the new grant.
 */

import { execFileSync } from "node:child_process";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { apiGet, login, setupDashboardRig, type BrowserSession, type DashboardRig } from "./dashboard-helpers.js";
import { mcpRequest, REPORTER_PROFILE } from "./mcp-helpers.js";
import { bindingFor } from "../src/setup.js";
import type { KbState } from "../src/kbread.js";

/** Canaries planted in the environment the compile runs in (JC-8 shape). */
const CANARIES = {
  CL_TEST_CANARY_VAULT: "canary-vault-secret-do-not-ship",
  CL_TEST_CANARY_PAT: "ghp_canary_do_not_ship_0000",
};

interface Archive {
  bytes: Buffer;
  /** path → content, as unpacked by the real `tar` a user would run. */
  files: Map<string, string>;
}

/** Fetch the bundle and unpack it the way the colleague's runbook does. */
async function download(
  rig: DashboardRig,
  session: BrowserSession,
  query = "",
): Promise<{ status: number; headers: Headers; archive: Archive | null; json: unknown }> {
  const res = await fetch(`${rig.base}/v1/setup/bundle${query}`, {
    headers: { cookie: session.cookie },
  });
  if (res.status !== 200) {
    return { status: res.status, headers: res.headers, archive: null, json: await res.json() };
  }
  const bytes = Buffer.from(await res.arrayBuffer());
  const dir = await mkdtemp(path.join(tmpdir(), "cl-bundle-"));
  const tarball = path.join(dir, "setup.tar.gz");
  await writeFile(tarball, bytes);
  execFileSync("tar", ["xzf", tarball, "-C", dir]);
  const listing = execFileSync("tar", ["tzf", tarball], { encoding: "utf-8" })
    .split("\n")
    .filter(Boolean);
  const files = new Map<string, string>();
  for (const name of listing) {
    files.set(name, await readFile(path.join(dir, name), "utf-8"));
  }
  return { status: res.status, headers: res.headers, archive: { bytes, files }, json: null };
}

/** Every string this deployment holds that must never reach a bundle. */
function secretsOf(rig: DashboardRig): string[] {
  const cfg = rig.core.cfg;
  return [
    ...Object.values(CANARIES),
    cfg.mcp.oidcClientSecret,
    cfg.sync.gitToken,
    ...cfg.runnerTokens.keys(),
    ...cfg.opsTokens.keys(),
    // The caller's own live credentials — the archive is a file that
    // gets copied around; it must not become a credential itself.
    ...(rig.token("reporter") ? [rig.token("reporter")] : []),
  ].filter((s) => typeof s === "string" && s.length > 0);
}

describe("A-2 setup delivery (PA-1): the requester's own bundle, no credential", () => {
  let rig: DashboardRig;
  let reporter: BrowserSession;
  let steward: BrowserSession;

  beforeAll(async () => {
    for (const [key, value] of Object.entries(CANARIES)) process.env[key] = value;
    rig = await setupDashboardRig();
    reporter = await login(rig, "reporter");
    steward = await login(rig, "steward");
  }, 240_000);

  afterAll(async () => {
    for (const key of Object.keys(CANARIES)) delete process.env[key];
    await rig?.stop();
  });

  it("serves the profile the caller's own roles are bound to, never a named one", async () => {
    const mine = await download(rig, reporter);
    expect(mine.status).toBe(200);
    expect(mine.headers.get("x-cl-setup-profile")).toBe("reporter");
    expect(mine.headers.get("content-disposition")).toContain("contextlayer-setup-reporter.tar.gz");

    const mcpJson = JSON.parse(mine.archive!.files.get(".mcp.json")!) as {
      mcpServers: { contextlayer: { url: string } };
    };
    expect(mcpJson.mcpServers.contextlayer.url).toContain("profile=reporter");

    // The steward gets the steward bundle from the same URL: the
    // binding is the identity's, not the address's.
    const theirs = await download(rig, steward);
    expect(theirs.headers.get("x-cl-setup-profile")).toBe("steward");
    expect(theirs.archive!.files.get("CLAUDE.md")).toContain("Steward");
  });

  it("refuses to let a URL carry a profile name (§3)", async () => {
    const crafted = await download(rig, reporter, "?profile=steward");
    expect(crafted.status).toBe(400);
    expect((crafted.json as { error: string }).error).toBe("profile_not_addressable");
    // Not a silently-ignored parameter: the refusal is the assertion.
    const bearer = await fetch(`${rig.base}/v1/setup/bundle?profile=steward`, {
      headers: { authorization: `Bearer ${rig.token("reporter")}` },
    });
    expect(bearer.status).toBe(400);
  });

  it("is authenticated: no session, no bundle", async () => {
    const anonymous = await fetch(`${rig.base}/v1/setup/bundle`);
    expect(anonymous.status).toBe(401);
    // …and a browser is sent to sign in rather than shown a JSON 401:
    // the address the colleague is handed is the download itself.
    const browser = await fetch(`${rig.base}/v1/setup/bundle`, {
      headers: { accept: "text/html,application/xhtml+xml" },
      redirect: "manual",
    });
    expect(browser.status).toBe(302);
    expect(browser.headers.get("location")).toBe(
      "/v1/auth/login?redirect=%2Fv1%2Fsetup%2Fbundle",
    );
    // An ops service token is not a person and gets no bundle either —
    // the surface self-authenticates as the requester (UI-2).
    const ops = await fetch(`${rig.base}/v1/setup/bundle`, {
      headers: { authorization: "Bearer test-ops-token" },
    });
    expect(ops.status).toBe(401);
  });

  it("is role-gated: an identity bound to no profile is refused, and told why", async () => {
    // `nokb` carries a real IdP role that this KB's roles.yaml binds to
    // no profile — authenticated, unbound, and told what to ask for.
    const res = await fetch(`${rig.base}/v1/setup/bundle`, {
      headers: { authorization: `Bearer ${rig.token("nokb")}` },
    });
    expect(res.status).toBe(403);
    const body = (await res.json()) as { error: string; detail: string };
    expect(body.error).toBe("no_profile_binding");
    expect(body.detail).toContain("roles.yaml");
  });

  it("refuses to guess when an identity is bound to two profiles", () => {
    // No IdP user wears two bound roles today, so this is asserted on
    // the binding rule itself: picking one silently would ship a user a
    // smaller product than their roles describe — PA-2's shape again.
    const ws = {
      roles: [
        { key: "R1", profile: "reporter", oidcGroup: "reporter", visibility: ["**"] },
        { key: "R2", profile: "steward", oidcGroup: "steward", visibility: ["**"] },
      ],
      profiles: new Map<string, Record<string, unknown>>([
        ["reporter", {}],
        ["steward", {}],
      ]),
    } as unknown as KbState;
    const two = bindingFor(ws, ["reporter", "steward"]);
    expect(two.ok).toBe(false);
    expect(two.ok === false && two.code).toBe("ambiguous_binding");
    expect(two.ok === false && two.status).toBe(409);
    const one = bindingFor(ws, ["reporter"]);
    expect(one.ok && one.profile).toBe("reporter");
  });

  it("carries no credential — canaries in the compile's environment never ship", async () => {
    const mine = await download(rig, reporter);
    const haystack = mine.archive!.bytes.toString("binary");
    const unpacked = [...mine.archive!.files.values()].join("\n");
    for (const secret of secretsOf(rig)) {
      expect(haystack).not.toContain(secret);
      expect(unpacked).not.toContain(secret);
    }
    // The canaries really were live in this process during the compile.
    expect(process.env.CL_TEST_CANARY_VAULT).toBe(CANARIES.CL_TEST_CANARY_VAULT);
  });

  it("delivers the layout Claude Code reads, skills included", async () => {
    const mine = await download(rig, reporter);
    const names = [...mine.archive!.files.keys()].sort();
    expect(names).toContain(".mcp.json");
    expect(names).toContain("CLAUDE.md");
    expect(names).toContain(".claude/skills/report/SKILL.md");
    // Skill-local tooling rides along (RA-5) — "ships inside the skill"
    // has to survive the delivery path too.
    expect(names.some((n) => n.startsWith(".claude/skills/report/") && n.endsWith(".py"))).toBe(true);
  });

  it("is byte-identical across downloads of one profile state", async () => {
    const first = await download(rig, reporter);
    const second = await download(rig, reporter);
    expect(second.archive!.bytes.equals(first.archive!.bytes)).toBe(true);
  });
});

describe("A-2 staleness (PA-2): the 2026-07-29 shape, repeated", () => {
  let rig: DashboardRig;
  let reporter: BrowserSession;

  beforeAll(async () => {
    rig = await setupDashboardRig();
    reporter = await login(rig, "reporter");
  }, 240_000);

  afterAll(async () => {
    await rig?.stop();
  });

  /** Land a profile change on the KB the way a merged PR would. */
  async function amendReporterProfile(yaml: string): Promise<void> {
    await writeFile(
      path.join(rig.kb.seedClone, ".contextlayer", "profiles", "reporter.yaml"),
      yaml,
    );
    rig.kb.commitAll("profile: grant the reporter a new tool");
  }

  async function connect(setupStamp: string | null): Promise<{ status: number; instructions: string }> {
    const { status, json } = await mcpRequest(
      rig,
      rig.token("reporter"),
      "reporter",
      "initialize",
      {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "claude-code", version: "0" },
      },
      setupStamp === null ? {} : { setup: setupStamp },
    );
    const result = (json?.result ?? {}) as { instructions?: string };
    return { status, instructions: result.instructions ?? "" };
  }

  it("a current bundle connects clean; the same bundle after a profile change is called out", async () => {
    // Step 1 — the reporter downloads their setup and starts working.
    const before = await download(rig, reporter);
    expect(before.status).toBe(200);
    const stamp = before.headers.get("x-cl-setup-stamp")!;
    const claudeMdBefore = before.archive!.files.get("CLAUDE.md")!;
    expect(claudeMdBefore).not.toContain("publish_report:sharepoint");

    const clean = await connect(stamp);
    expect(clean.status).toBe(200);
    expect(clean.instructions).toBe(""); // nothing to say: the setup is current

    // Step 2 — the operator grants the profile a new tool (July 29: it
    // was `publish_report:powerbi`, merged while the reporter's session
    // was already running on the older bundle).
    await amendReporterProfile(
      REPORTER_PROFILE.replace("publish_report:powerbi,", "publish_report:powerbi, publish_report:sharepoint,"),
    );

    // Step 3 — the session, still on the stale bundle, reconnects. On
    // 2026-07-29 nothing told it anything and it quietly declined the
    // work its profile already permitted.
    const stale = await connect(stamp);
    expect(stale.status).toBe(200);
    expect(stale.instructions).toContain("SETUP OUT OF DATE");
    expect(stale.instructions).toContain("/v1/setup/bundle");
    // The instruction that closes the failure shape: do not narrow.
    expect(stale.instructions).toMatch(/authoritative/i);
    expect(stale.instructions).toMatch(/Do not decline work/i);

    // Step 4 — one step to fresh: the same URL, no profile name, and
    // the new grant is in the bundle the user gets.
    const after = await download(rig, reporter);
    const claudeMdAfter = after.archive!.files.get("CLAUDE.md")!;
    expect(claudeMdAfter).toContain("publish_report:sharepoint");
    const freshStamp = after.headers.get("x-cl-setup-stamp")!;
    expect(freshStamp).not.toBe(stamp);

    const healed = await connect(freshStamp);
    expect(healed.instructions).toBe("");
  });

  it("an unstamped bundle — every bundle compiled before A-2 — says so rather than staying silent", async () => {
    const legacy = await connect(null);
    expect(legacy.status).toBe(200);
    expect(legacy.instructions).toContain("SETUP UNVERIFIABLE");
    expect(legacy.instructions).toContain("/v1/setup/bundle");
  });

  it("PA-3: the audit row states which setup the session presented (D-108.4)", async () => {
    // A-2's evidence could show that eleven calls happened and could
    // show what the server said about staleness; it could not show
    // which bundle made them. The stamp lived in a URL and in a notice,
    // and neither is durable. Now the row carries it.
    const fresh = await download(rig, reporter);
    const stamp = fresh.headers.get("x-cl-setup-stamp")!;

    const stamped = await mcpRequest(rig, rig.token("reporter"), "reporter", "tools/call", {
      name: "search_context",
      arguments: { query: "orders" },
    }, { setup: stamp });
    expect(stamped.status).toBe(200);

    // The same identity on a pre-A-2 bundle: no stamp on the URL at all.
    const legacy = await mcpRequest(rig, rig.token("reporter"), "reporter", "tools/call", {
      name: "search_context",
      arguments: { query: "customers" },
    });
    expect(legacy.status).toBe(200);

    // Read it back the way the extractor does — through the governed
    // audit API, not the database. If the column were absent from the
    // read shape, the evidence path would still be broken.
    const steward = await login(rig, "steward");
    const audit = await apiGet(rig, steward, "/v1/dashboard/audit?tool=search_context&limit=50");
    expect(audit.status).toBe(200);
    const rows = audit.json.rows as { args_digest: string; setup_stamp: string | null }[];
    const stamps = rows.map((r) => r.setup_stamp);
    expect(stamps).toContain(stamp);
    // Not silence, and not a guess: "we asked and it had none" is a
    // different statement from "we never asked", which is NULL.
    expect(stamps).toContain("unstamped");
    expect(stamps).not.toContain(null);
  });

  it("/v1/setup/status answers the same question for the operator's runbook", async () => {
    const fresh = await download(rig, reporter);
    const stamp = fresh.headers.get("x-cl-setup-stamp")!;

    const current = await fetch(`${rig.base}/v1/setup/status?setup=${stamp}`, {
      headers: { cookie: reporter.cookie },
    });
    const currentBody = (await current.json()) as { state: string; profile: string; notice: null };
    expect(currentBody.state).toBe("current");
    expect(currentBody.profile).toBe("reporter");
    expect(currentBody.notice).toBeNull();

    const stale = await fetch(`${rig.base}/v1/setup/status?setup=deadbeefdeadbeef`, {
      headers: { cookie: reporter.cookie },
    });
    const staleBody = (await stale.json()) as { state: string; notice: string; download: string };
    expect(staleBody.state).toBe("stale");
    expect(staleBody.notice).toContain("SETUP OUT OF DATE");
    expect(staleBody.download).toContain("/v1/setup/bundle");
  });
});
