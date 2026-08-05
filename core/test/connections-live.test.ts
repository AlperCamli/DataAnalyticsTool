/**
 * A-3's live clause: the **existing pilot rows** are readable and
 * testable through the new API, unchanged.
 *
 * Env-gated, and skipped by default — it talks to whatever stack
 * `CL_LIVE_API` names, with whatever identity `CL_LIVE_TOKEN` carries.
 * Every other suite in this directory builds its own world; this one
 * deliberately does not, because the clause is about rows that were
 * written years of checkpoints ago by a different code path, against a
 * registry nobody migrated.
 *
 *   CL_LIVE_API=http://127.0.0.1:8100 \
 *   CL_LIVE_TOKEN=$(…ops identity's access token…) \
 *     npx vitest run test/connections-live.test.ts
 *
 * `CL_LIVE_TEST=1` additionally runs the probe against each connection.
 * That one reaches real sources, so it is opt-in beyond the read: an
 * `auth_error` from it is a true statement about a credential, and this
 * file reports it as a finding rather than an assertion failure.
 */

import { describe, expect, it } from "vitest";

const API = process.env.CL_LIVE_API?.replace(/\/$/, "") ?? "";
const TOKEN = process.env.CL_LIVE_TOKEN ?? "";
const RUN_PROBES = process.env.CL_LIVE_TEST === "1";

/** The five the pilot has carried since M3 (CLAUDE.md, "Live pilot case"). */
const PILOT = ["supabase", "ga4", "gsc", "looker_studio", "powerbi"];

interface Health {
  status: string;
  reason: string;
  freshness: string;
  snapshot: { age_s: number; object_count: number } | null;
  last_job: { type: string; state: string } | null;
}

interface Connection {
  system: string;
  connector: { name: string };
  credentials: { key: string | null; ref: string | null }[];
  config: Record<string, unknown>;
  health: Health;
}

async function api(path: string, method = "GET"): Promise<{ status: number; json: any }> {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: { authorization: `Bearer ${TOKEN}` },
  });
  const text = await response.text();
  return { status: response.status, json: text ? JSON.parse(text) : {} };
}

const live = API && TOKEN ? describe : describe.skip;

live("A-3 live: the pilot's own connections through the new API", () => {
  it("lists every pilot row, with health, unchanged", async () => {
    const listing = await api("/v1/dashboard/connections");
    expect(listing.status, JSON.stringify(listing.json)).toBe(200);
    expect(listing.json.role_scope).toBe("write");

    const connections = listing.json.connections as Connection[];
    const bySystem = Object.fromEntries(connections.map((c) => [c.system, c]));
    for (const system of PILOT) {
      expect(Object.keys(bySystem), `pilot row ${system} is missing`).toContain(system);
      const conn = bySystem[system]!;
      expect(conn.connector.name).toBeTruthy();
      expect(conn.health.status).toMatch(/^(green|amber|red|unknown)$/);
      // Health is a statement with a reason, always.
      expect(conn.health.reason.length).toBeGreaterThan(0);
    }

    // Read as prose so a failure here is legible in CI output, and so a
    // human running this sees the estate rather than a boolean.
    for (const conn of connections) {
      const snap = conn.health.snapshot;
      console.log(
        `${conn.system.padEnd(15)} ${conn.connector.name.padEnd(14)} ` +
          `${conn.health.status.padEnd(8)} ${conn.health.freshness.padEnd(18)} ` +
          `${snap ? `${snap.age_s}s / ${snap.object_count} objects` : "no snapshot"} — ${conn.health.reason}`,
      );
    }
  }, 60_000);

  it("serves references and no credential material", async () => {
    const listing = await api("/v1/dashboard/connections");
    const connections = listing.json.connections as Connection[];
    for (const conn of connections) {
      for (const credential of conn.credentials) {
        // Every reference is a reference. If a legacy row ever held
        // material, this is where it would surface — and it is exactly
        // what the write path now refuses to create.
        expect(credential.ref, `${conn.system}: credential is not a reference`).toMatch(
          /^(env|vault):\/\//,
        );
      }
    }
    const body = JSON.stringify(listing.json);
    expect(body).not.toMatch(/[a-z][a-z0-9+.-]*:\/\/[^/\s@"]*:[^@/\s"]+@/i);
    expect(body).not.toContain("BEGIN PRIVATE KEY");
  }, 60_000);

  it("reads each pilot row individually", async () => {
    for (const system of PILOT) {
      const one = await api(`/v1/dashboard/connections/${system}`);
      expect(one.status, `${system}: ${JSON.stringify(one.json)}`).toBe(200);
      expect((one.json.connection as Connection).system).toBe(system);
    }
  }, 60_000);

  (RUN_PROBES ? it : it.skip)(
    "probes each pilot row, and reports what it found",
    async () => {
      const findings: string[] = [];
      for (const system of PILOT) {
        const result = await api(`/v1/dashboard/connections/${system}/test`, "POST");
        expect([200, 202], `${system}: ${JSON.stringify(result.json)}`).toContain(result.status);
        const outcome = result.json.outcome as string;
        const unprobed = (result.json.unprobed ?? []) as string[];
        const error = result.json.error as { code?: string } | undefined;
        console.log(
          `${system.padEnd(15)} ${outcome.padEnd(8)} ` +
            `${error?.code ?? ""} ${unprobed.length ? `unprobed: ${unprobed.join(",")}` : ""}`,
        );
        if (outcome !== "pass") {
          findings.push(`${system}: ${outcome}${error?.code ? ` (${error.code})` : ""}`);
        }
        if (error?.code === "auth_error") {
          // The gate clause, live: a refused credential names its
          // reference and never its value.
          const reauth = result.json.reauth as { credential_refs: string[] } | undefined;
          expect(reauth, `${system}: auth_error with no re-auth prompt`).toBeTruthy();
          for (const ref of reauth!.credential_refs) expect(ref).toMatch(/^(env|vault):\/\//);
        }
      }
      // Findings are printed, not thrown: a real credential that has
      // rotated is an estate fact for the operator's write-up, and a
      // test that failed on it would be reporting the wrong thing.
      if (findings.length > 0) {
        console.log(`\nnot green: ${findings.join("; ")}`);
      }
    },
    600_000,
  );
});
