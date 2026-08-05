# A-3 + B-2 — Connections are operable, and they have a face

Checkpoint A-3 (Track A) and B-2 (Track B), built together because one
is the other's API. Plus D-108.4's stamp-in-audit fix, which rode task 0.

**What ends here.** Since D-63.8 the connection registry has been written
by a vendor CLI holding a database credential — explicitly "E2's
Connections-UI stand-in". CP-8 graded playbook step 3 ASSISTED on exactly
that, and D-84's silent-failure pair (a connection reported registered
that was absent) is what it cost. Register item **E2 closes**; **U-1** is
served.

---

## 1. Task 0 — D-107/D-108 recorded, PA-3 built

`RULING D-107` and `RULING D-108` are transcribed verbatim into
DECISIONS.md. **Two of D-108's clauses arrived with unfilled
placeholders** — clause 2's one-sentence operator statement about the
room, clause 3's friction notes — and this session did not fill them.
An invented sentence about a room no session was in is the one thing a
decisions record must never contain. They stay bracketed, the two
findings they govern (A2-F1, A2-F2) are conditional on that text, and
`results/phase2/a2-field-notes/` remains an owed operator write.

**A-2 is marked CLOSED in the plan** (D-108.5's plan half) with the
evidence cited: 11 audit rows, every one `subject=eda` / `profile=reporter`
/ `allowed`, zero operator rows in the window; 8m41s sign-in to first
question. PA-1 and PA-2 close in the register.

**The PA-3 fix** (`0011_audit_setup_stamp.sql`): `audit_records` gains
`setup_stamp` — the compiled-setup stamp the session presented, or the
literal `unstamped` when it presented none. NULL is reserved for rows
predating the column, which is a different statement. Written on
denied-connection rows too, because a refused connection is the row an
investigator most wants it for. Never read to permit or deny anything:
enforcement stays `(roles ∩ profile)` per call.

`extract-audit.sh` appends it as the last field, so evidence extracted
before the column still diffs line-for-line against a fresh extraction —
and `dashboard-extract.test.ts` now states that relationship precisely
rather than being loosened.

## 2. A-3 — the Connections API

`GET|PUT|DELETE /v1/dashboard/connections[/:system]`, plus
`POST …/test` and `POST …/sync`, on B-0's session layer.

| Gate clause | How |
|---|---|
| CRUD + test, server-side role checks | ops writes (`CORE_DASHBOARD_ADMIN_ROLES`, default `ops`), steward reads, everyone else 403 — including list |
| Per-source health | latest accepted snapshot vs the policy threshold, last job outcome, freshness state; read from stores that already exist |
| `auth_error` → re-auth prompt | produced from the error code, naming the credential **reference** (never a value) and what to do about it |
| The CLI is a thin client | `cli.ts` calls the same endpoints with the operator's own token; the direct-DB registry path is **deleted**, asserted at grep level |
| Registration returns what the store holds | the read-back lives in `upsertSyncSystem`, so no caller can report a write the store did not take |

**References only.** A payload carrying credential material is refused
`raw_secret_rejected` — by field name (`config.dsn` → use `dsn_env`) and
by value shape (URI-with-password, PEM key, service-account JSON),
wherever it appears. The refusal never echoes the value. `vault://` is
already accepted, so A-4 changes the resolver and not this validation.

**The probe is real.** `test_connection` is implemented in the SDK as the
manifest's declared `health_probe: builtin`, running the preflight
surfaces that already existed — for Postgres, connecting as the
introspection role and checking it holds neither SUPERUSER nor BYPASSRLS
(D-71.2), plus the G3 execution-role wall; for GA4/GSC, the one API call
their `introspect` makes first. No new credential path: the runner
resolves references exactly as it does for a snapshot job. A capability
with no preflight is reported **`unprobed`**, never counted as a pass.

## 3. B-2 — the first pixels

A React SPA, esbuild-bundled to static assets the core serves at `/app/`
behind the D-102 session (D-103.1: no separate frontend server, no second
identity domain). The shell renders whatever `/v1/dashboard/modules`
returns — the module list is resolved from `.contextlayer/dashboard.yaml`
and the caller's roles **server-side**.

**DT-2 is asserted two ways.** The shipped bundle contains no role name
and no role-check shape; the app's own sources contain no raw-HTML escape
hatch, no browser storage, and no password input. The denied case renders
the server's own 403 — the buttons stay, because a hidden button teaches
nobody why it is hidden and means the client decided.

Component specifics (D-103's ≤5 lines): React 18 + TypeScript, esbuild,
**no router / component library / state library / CSS framework**. Five
files, one stylesheet, one `pushState` route switch.

## 4. Playbook step 3, rewritten

§6 now describes the shipped surface: sign in at `/app/`, register with
references, test, read the verdict literally, arm the policy. The
D-63.8-era vendor-CLI language is retired. Its exit is re-stated so the
three non-green states are answers rather than formatting problems.

**One health-model correction the live check forced.** A connection
absent from `sync-policy.yaml` is not a sync source, so freshness is not
its verdict — its last job is. Without it, Looker Studio and Power BI
would have sat permanently `amber / never_snapshotted` and step-3's
"health green" exit would have been unreachable for two of the pilot's
five connections. Found by running against the estate, not by reasoning
about it.

## 5. Live check (2026-08-06, the pilot stack)

`core/test/connections-live.test.ts`, env-gated, run against the rebuilt
live stack:

```
supabase        postgres       green  fresh              87506s / 38 objects
ga4             ga4            red    stale              1414094s / 466 objects   (3d threshold)
gsc             gsc            red    stale              474865s / 10 objects     (3d threshold)
looker_studio   looker_studio  green  not_a_sync_source  last test_connection job succeeded
powerbi         powerbi        green  not_a_sync_source  last test_connection job succeeded
```

All five **probe `pass`** — supabase's two role walls, one real API call
each for GA4 and GSC, `unprobed: [publish]` for the two publisher
adapters. The two `red` rows are a true statement about the estate that
this build surfaces; they are not caused by it.

`/app/` serves, `/` redirects to it, `/v1/dashboard/modules` answers
`config_source: default` (the pilot KB carries no `dashboard.yaml`).

## 5b. One defect the operator found on first read

`/app/` answered 404 while `/healthz` said `ok`. Nothing was broken: the
core had been recreated by a `docker compose up` without
`CORE_MCP_ENABLED=1`, so the dashboard was never registered. This is
**D-84.2's shape a third time** — `environment:` in `docker-compose.yml`
outranks the overlay's `env_file:`, so an unsourced env silently disarms
a surface — and the runbook's own Act 0 reproduced it by giving plain
compose lines instead of the `set -a; . .secrets/sync.env` form
`make stack-live` uses.

Both halves fixed: Act 0 now sources the env and ends with a check, and
`/healthz` reports **`dashboard_enabled`** beside `mcp_enabled` and
`sync_enabled`, for the reason SO-F gave for the latter. A surface that
can be silently off has to be checkable without reading the process
environment.

## 6. Tests

- `core/test/connections.test.ts` — 16: role gate (ops/steward/reporter,
  each refusal the server's), CSRF, `raw_secret_rejected` three ways with
  the value never echoed, read-back equality, **the D-84 shape reproduced
  with a trigger that swallows writes** → 500 `write_not_observed`,
  deletion verified, health's four states, the probe's honest `pending`,
  the CLI grep assertion, and B-2's DT-2 + module-map resolution +
  `/healthz`'s `dashboard_enabled`.
- `core/test/connections-e2e.test.ts` — 2, live Postgres + live SDK
  runner: a good credential probes green with the role facts it read; a
  wrong password yields `auth_error` and the re-auth prompt naming the
  reference, with no credential byte in the response.
- `core/test/connections-live.test.ts` — env-gated, the pilot rows.
- `core/test/setup-bundle.test.ts` — +1 for PA-3.
- `tests/test_sdk_runner.py` — +4 for the probe engine (unprobed is not a
  pass; the config gate; `auth_error` mapping; the report is scrubbed).

## 7. Flagged, not done

1. **Connection CRUD writes are not audited.** `audit_records` is
   specified as one row per MCP call (§8); a dashboard registration
   leaves no row there. The durable record today is the job's trigger
   actor, for tests and syncs only. *Recommend:* a register item, home
   dashboard spec §5.
2. **The capability spec has no `test_connection` section.** The builtin
   probe and its two preflight surfaces ship undocumented there.
   *Recommend:* an additive §7 next session.
3. **D-107.3 / D-107.4 register rows are not filed** (VERDICT HISTORY,
   JOBS RETENTION). Recorded in DECISIONS; outside this session's fence.
4. **A-2's field notes remain owed** (`results/phase2/a2-field-notes/`),
   with D-108 clauses 2 and 3.
5. **The A-3/B-2 gate demo is the operator's** —
   `results/phase2/a3-b2/GATE-RUNBOOK.md`. STOP.
