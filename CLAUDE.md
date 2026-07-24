# Context Layer — Platform Repo

## What this is
Metadata/knowledge platform: connectors introspect data sources into
normalized snapshots; a deterministic generator renders a git-based KB;
a sync engine keeps it fresh; an MCP server serves it to agents with
trust signals. First deployment: Supabase + GA4 + GSC → Looker Studio.

## Source of truth
- `specs/` is the authoritative v1.0 spec set. Read `specs/spec-index.md`
  first for the document map and reading order.
- Never contradict a spec silently. If implementation reveals a spec
  problem, stop and surface it — changes go through the amendment
  process (upstream spec is amended first).
- Open questions live in `specs/master-open-decisions-register.md`.
  If a decision is Open, implement its stated default. Never invent a
  resolution; propose a new register item instead.
- Sequence: `plans/context-layer-development-plan-v1.md`
  (checkpoints CP-0..CP-8). Current position: CP-7 (M3, "the report
  ships"); platform work commits directly to `main` (D-82 — local-only
  repo, no remote); `main` is current through M2 + CP-5
  (CP-5 closed by amendment, D-80; landing `b663434`). Task 7.0
  (reporting views over RLS, D-80.3/D-81): delta DDL drafted in
  `deploy/reporting-views.sql`, awaiting operator apply as customer
  DBA (we never run DDL against the customer estate), then manual
  sync → additive drift PR → lineage → enrich-the-hot-views. The
  publisher stack is BUILT and fixture-green (D-83): SDK publish
  capability, Looker Studio template-link adapter, `publish_report`
  in the MCP server (MT-10/F-7/F-5/F-4), report-skill S7; live path
  gated on the 7.0 views + operator template creation + connection
  registration + KB PR #23 (reporter publish grant). M1's live-demo
  gate remains open (PR-CP4-M1.md); M2's pending two-machine demo
  happens as part of the M3 gate demo, through these views.

## Engineering norms
- Conformance tests are the definition of done. Snapshot work is done
  when the C-tests (snapshot spec §8) pass, not before.
- Determinism is a contract: same source state → byte-identical
  canonical snapshot body (S-3). Generator: deterministic, idempotent,
  zero model calls.
- Evolution is additive-only within a version (S-7). Unknown `kind`s
  are skipped with a logged warning, never an error (S-5).
- Snapshots carry facts verbatim — never synthesize prose (S-8).
- Snapshots are all-or-nothing per system (S-6); partial introspection
  is a failed job.
- Small, reviewable diffs; everything lands as a PR.

## Layout
- `specs/` — spec set · `plans/` — dev plan
- `snapshot/` — schema, canonicalization, hashing, diff (task 1.1)
- `connectors/` — sdk/ (shared harness: manifest, providers, emission,
  local CLI), static_demo/ (reference connector), postgres/, ga4/, gsc/
  (tasks 1.2–1.4)
- `generator/` — templates + renderer (task 1.5)
- `fixtures/` — snapshot fixtures per system

## Live example case (this machine only)
An example estate is wired up for live testing: **example-estate.com**
(supabase + gsc pulls verified end-to-end; ga4 pending a property id).
Credentials, ready-to-run configs, and the runbook are in
`.secrets/connections.md` — git-ignored, local only; never commit or
echo its contents (JC-8). Convention: the rendered KB the user reviews
lives at `~/Desktop/kb` (snapshots at `~/Desktop/kb-snapshots/`);
re-render it after changes that affect generator or connector output.
Since task 1.6, `~/Desktop/kb` is the clone of the customer KB repo
`github.com/AlperCamli/DataAnalyticsTool` (public by ruling D-47;
main protected: KB CI + code-owner review required; changes go via
PR, steward merges). KB CI runs the validation library from a wheel
vendored at `.github/vendor/` there — after any validation-library
change, rebuild the wheel and PR it with its manifest (D-46; a stale
wheel silently validates against old rules).

## Stack
Python 3.12 + jsonschema (Draft 2020-12) + PyYAML + pytest + hypothesis.
Venv at `.venv/`; run tests with `.venv/bin/python -m pytest`.
(Choice recorded in DECISIONS.md D-8, amended D-15.)