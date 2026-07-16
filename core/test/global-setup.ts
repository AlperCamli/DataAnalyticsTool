/**
 * One disposable postgres:16 container per vitest run (same pattern as
 * the Python suite's ephemeral containers). CORE_TEST_DATABASE_URL, when
 * set, points at an existing server instead and no container is run.
 */

import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import pg from "pg";
import type { GlobalSetupContext } from "vitest/node";

declare module "vitest" {
  export interface ProvidedContext {
    adminUrl: string;
  }
}

function docker(args: string[]): string {
  return execFileSync("docker", args, { encoding: "utf-8", timeout: 120_000 });
}

async function waitReady(url: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const client = new pg.Client({ connectionString: url, connectionTimeoutMillis: 2000 });
    try {
      await client.connect();
      await client.query("SELECT 1");
      return;
    } catch (err) {
      if (Date.now() > deadline) {
        throw new Error(`postgres not ready after ${timeoutMs}ms: ${(err as Error).message}`);
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    } finally {
      await client.end().catch(() => {});
    }
  }
}

export default async function setup({ provide }: GlobalSetupContext): Promise<(() => void) | void> {
  const external = process.env.CORE_TEST_DATABASE_URL;
  if (external) {
    provide("adminUrl", external);
    return;
  }
  const name = `cl-core-test-${randomBytes(4).toString("hex")}`;
  docker([
    "run", "-d", "--rm", "--name", name,
    "-e", "POSTGRES_PASSWORD=pg",
    "-p", "127.0.0.1:0:5432",
    "postgres:16",
  ]);
  try {
    const mapped = docker(["port", name, "5432/tcp"]).trim().split("\n")[0]!;
    const port = mapped.split(":").pop();
    const url = `postgres://postgres:pg@127.0.0.1:${port}/postgres`;
    await waitReady(url, 90_000);
    provide("adminUrl", url);
  } catch (err) {
    try {
      docker(["rm", "-f", name]);
    } catch {
      // container already gone
    }
    throw err;
  }
  return () => {
    docker(["rm", "-f", name]);
  };
}
