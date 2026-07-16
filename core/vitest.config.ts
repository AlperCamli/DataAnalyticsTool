import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    globalSetup: ["test/global-setup.ts"],
    testTimeout: 60_000,
    hookTimeout: 120_000,
    // Each test file provisions its own throwaway database (see
    // test/helpers.ts), so files can run in parallel safely; keep the
    // worker count modest so the shared Postgres container isn't a
    // connection bottleneck.
    maxWorkers: 4,
    minWorkers: 1,
  },
});
