# Conventions

Bootstrapped skeleton (KB ruling K-7): completed at customer bootstrap
(task 1.6, playbook step 2) and human-owned from then on — the generator
never rewrites this file.

## System classes & dialects

| System | Class | Dialect / query surface |
|---|---|---|
| `supabase` | SQL | PostgreSQL **17** (Supabase-hosted; `server_version: 17.6` in the snapshot envelope). Queried via `execute_sql:supabase`, `SELECT` only. |
| `ga4` | API | GA4 Data API `runReport` — dimensions/metrics as documented in `systems/ga4/`. No SQL surface. |
| `gsc` | API | Search Console Search Analytics API `searchanalytics.query` — fixed dimension/metric set, see `systems/gsc/`. No SQL surface. |

View SQL in machine docs is **engine-canonical**: definitions are
captured via `pg_get_viewdef` (the engine's own deparse), so the SQL you
read in a `*.schema.md` "View definition" section is Postgres-canonical
form, not the migration author's original text. Lineage derivation and
`validate_sql` parse exactly that canonical form as Postgres dialect.

## Query guardrails per system

Reports run **directly on production OLTP** (no warehouse, no replica on
the current tier) — the guardrails below are mandatory from the first
query, not tunable per session (phase-1 plan §1 mandate).

**`supabase`** — execution policy:

- Connections use the **read-only role**; `SELECT` statements only.
- `statement_timeout`: **60 s**, enforced engine-side on every connection.
- Row cap: **50 000** rows per result (fetch-limited; oversized results
  return truncated with `truncated: true`, never silently).
- **Reporting-views pattern:** report-grade SQL that will back a Looker
  Studio data source is materialized as a view in the `reporting` schema
  via migration PR — never run ad-hoc against production for a recurring
  report.
- A read replica is preferred the moment the customer's tier provides
  one; until then the caps above are the only thing between an agent
  and production load.

**`ga4`, `gsc`** — no SQL; the row cap applies to API pagination (fetch
stops at the cap). Quota behavior is in "Quota notes" below.

## Trust-status behaviors

Machine docs (`status: machine`) carry introspected facts verbatim.
Statuses on human-owned docs (KB spec §5):

- `verified` — use freely.
- `draft` / `stale` — use, but warn the user explicitly.
- `contaminated` — refuse to build on it unless the user explicitly
  overrides, and say why (the broken reference is named in front-matter).

## Naming conventions

FQNs are `system.schema.name` (SQL) or `system.group.name` (API), always
backticked in doc bodies. Entities and metrics are referenced by path
(`entities/<entity>.md`), never by prose title.

## Quota notes for API sources

**GA4 (Data API).** Quota is property-scoped tokens; exhaustion is a
real failure mode on this API.

- **Session-caching convention (risk register, CP-2):** within one agent
  session, `runReport` results are cached and reused — a repeated or
  refined question re-slices the session's earlier result rather than
  re-issuing the API call. Only a genuinely new dimension/metric/date
  combination spends quota.
- Quota exhaustion surfaces as a **deferral** (job protocol J-5): the
  job comes back with a retry-after; it is never an error. Agents should
  tell the user the answer is delayed, not failed.
- Custom definitions change rarely; metadata re-snapshots are nightly —
  never re-pull metadata inside a session.

**GSC (Search Analytics API).** Modest quotas; one query per report
request is the norm. No session-scale quota risk, but the same
session-caching convention applies — don't re-issue identical queries.

**GSC data freshness (`dataState`).** The snapshot records the request
vocabulary (`data_freshness.data_states: [all, final]` in
`systems/gsc/`); what it *means* (D-31 — prose semantics live here, not
in snapshots):

- `dataState=final` returns only **finalized** rows — stable numbers
  that will not change, lagging roughly 2–3 days behind today.
- `dataState=all` additionally returns the **fresh-but-provisional**
  tail — recent rows that may still change until finalized.
- Convention for agents: use `final` for anything certified or
  recurring (reports, metric implementations); use `all` only when the
  user explicitly wants the freshest numbers, and say in the answer
  that the most recent days are provisional.

## Machine-readable guardrails

```yaml
# validate_sql per-system checks (MCP §6.6); populated at bootstrap.
supabase:
  dialect: postgres
  engine_version: 17
  statement_class: select-only
  timeout_s: 60
  row_cap: 50000
  reporting_views_schema: reporting
ga4:
  dialect: api
  operation: runReport
  row_cap: 50000
  session_cache: required
gsc:
  dialect: api
  operation: searchanalytics.query
  row_cap: 50000
  data_state_default: final
```
