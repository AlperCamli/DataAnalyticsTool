# postgres connector

Supabase/Postgres `MetadataProvider` (task 1.2, plan §3.1). One
introspector over `pg_catalog`; two modes producing identical canonical
bodies for the same source state (S-4, C-3).

## Modes

- **`ddl-file`** — boots an ephemeral postgres container (`docker`),
  streams the configured DDL files through `psql -v ON_ERROR_STOP=1`
  inside it (the DDL is executed by real Postgres, never parsed by us),
  then introspects it exactly as if live.
- **`live`** — the same introspector against `dsn`/`dsn_env`, meant for
  a read-only role. The session is additionally pinned
  `default_transaction_read_only = on` with a 60s `statement_timeout`
  (plan §1's day-one mandate), in both modes for uniformity.

Per MP-1 there is no fallback between modes: missing Docker or an
unreachable DSN fails `source_unavailable`.

## The image rule (ddl-file mode)

`image` is **required, with no default**: its postgres major version
must match the live target's major. `pg_get_viewdef` deparsing can
differ across majors, and `stats.definition` is hash-included — a
mismatched image would manufacture spurious *breaking* diffs the moment
a customer switches from ddl-file to live mode, which is exactly what
S-4 promises never happens. Customer 2 (Supabase 15.x): `postgres:15`.

## Config

See `config.schema.json` / `config.example.json`. `system` + `mode`
always; `ddl_files` + `image` in ddl-file mode; `dsn` or `dsn_env`
(environment-variable indirection — preferred, keeps secrets out of
config files) in live mode; optional `schemas` allowlist (default:
every non-system schema). Vault-referenced credentials arrive with the
job transport (DECISIONS.md D-14).

## What is captured (mapping summary)

Tables (incl. partitioned parents), views, and materialized views, with
verbatim engine-rendered facts: `format_type` column types,
`pg_get_expr` defaults, `pg_get_viewdef(oid, true)` definitions (the
lineage input — carried untouched), `obj_description`/`col_description`
comments (S-8), PK/FK/unique constraints into `keys`, non-constraint
indexes as sorted `pg_get_indexdef` strings into `stats.indexes`
(hash-excluded, §4.5 registration record), and `reltuples` into
`stats.row_estimate` (omitted while `-1`, i.e. never analyzed).

Documented `source_properties` keys (MP-2, additive only):

| Key | Meaning |
|---|---|
| `server_version` | `major.minor`, derived from `server_version_num` |

Deliberate exclusions and their register items: partition *children*
(`relispartition` — runtime artifacts that exist live but not in
logical DDL; D-17), CHECK constraints (SS-5), enum type labels (SS-6),
identity/generated markers, schema/index comments, partition key
definitions (SS-7).

## Determinism (D-19, canonical readings for all engine connectors)

- Session `search_path` pinned empty (pg_dump's guard): deparsed SQL
  qualifies names identically regardless of database-level settings.
- Column `ordinal` = dense rank among non-dropped columns, not raw
  `attnum` (a live table with dropped-column gaps must match its
  logical DDL replay).
- All canonical ordering is the 1.1 library's; the connector only
  pre-sorts `stats.indexes` (its registered form is "sorted").

## Running locally

```sh
python -m connectors.sdk.local connectors.postgres.connector \
    --config config.example.json --out snapshot.json
```

Conformance: `tests/test_postgres_connector.py` (C-1..C-8 where
container-testable; marker `postgres`, skipped without Docker) and
`tests/test_postgres_config.py` (no Docker needed).
