"""Catalog introspection: one open connection → snapshot objects.

This module is the single introspector both modes share (plan §3.1): it
reads pg_catalog only, and every emitted string is the engine's own
rendering (`format_type`, `pg_get_expr`, `pg_get_viewdef`,
`pg_get_indexdef`) — nothing is parsed, trimmed, or synthesized on this
side (S-8). View definitions are carried exactly as `pg_get_viewdef`
returns them: they are the input to lineage derivation (task 1.9).

Determinism rules that make C-2/C-3 byte-testable (DECISIONS.md D-19):

- The session search_path is pinned empty (pg_dump's own guard), so
  deparsed SQL qualifies every non-builtin name identically no matter
  how the source database's default search_path is customized.
- Column `ordinal` is the dense rank among non-dropped columns, not raw
  attnum: a live table that ever had a dropped column keeps attnum gaps
  its logical DDL replay does not, and S-4 promises invariance over the
  *logical* state.
- `row_estimate` is omitted while `reltuples = -1` (never analyzed —
  every fresh ddl-file container); the eventual ddl→live switch adds
  estimates as a metadata-only diff, which is expected fresh
  information, never a spurious structural change (hash-excluded).
- `stats.indexes` and `stats.checks` are sorted lexicographically here
  (the §4.5 registered form); every other ordering is the 1.1
  canonicalizer's job. `pg_constraint` order in particular is not stable
  across dump/restore, so C-2 byte-identity depends on that sort.
"""

from collections import defaultdict

# Session pins, applied before any catalog read. Read-only + timeout are
# the plan-§1 day-one mandates for touching production; applied in both
# modes so the introspector behaves identically everywhere.
SESSION_SETUP = (
    "SELECT pg_catalog.set_config('search_path', '', false)",
    "SET default_transaction_read_only = on",
    "SET statement_timeout = '60s'",
)

KIND_BY_RELKIND = {"r": "table", "p": "table", "v": "view", "m": "materialized_view"}

_OBJECTS_SQL = """
SELECT c.oid, n.nspname, c.relname, c.relkind::text,
       CASE WHEN c.reltuples >= 0 THEN c.reltuples::bigint END AS row_estimate,
       pg_catalog.obj_description(c.oid, 'pg_class') AS description,
       CASE WHEN c.relkind IN ('v', 'm')
            THEN pg_catalog.pg_get_viewdef(c.oid, true) END AS definition
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm')
  AND NOT c.relispartition
  AND n.nspname <> 'information_schema'
  AND n.nspname NOT LIKE 'pg\\_%%'
  AND (%(schemas)s::text[] IS NULL OR n.nspname = ANY(%(schemas)s::text[]))
"""

_COLUMNS_SQL = """
SELECT a.attrelid, a.attnum, a.attname,
       pg_catalog.format_type(a.atttypid, a.atttypmod) AS type,
       NOT a.attnotnull AS nullable,
       CASE WHEN a.attidentity = '' AND a.attgenerated = ''
            THEN pg_catalog.pg_get_expr(ad.adbin, ad.adrelid) END AS "default",
       pg_catalog.col_description(a.attrelid, a.attnum) AS description
FROM pg_catalog.pg_attribute a
LEFT JOIN pg_catalog.pg_attrdef ad
       ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
WHERE a.attrelid = ANY(%(relids)s::oid[])
  AND a.attnum > 0 AND NOT a.attisdropped
"""

_CONSTRAINTS_SQL = """
SELECT con.conrelid, con.contype::text, con.conkey, con.confrelid, con.confkey
FROM pg_catalog.pg_constraint con
WHERE con.conrelid = ANY(%(relids)s::oid[]) AND con.contype IN ('p', 'u', 'f')
"""

_REL_NAMES_SQL = """
SELECT c.oid, n.nspname, c.relname
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.oid = ANY(%(relids)s::oid[])
"""

_ATTNAMES_SQL = """
SELECT a.attrelid, a.attnum, a.attname
FROM pg_catalog.pg_attribute a
WHERE a.attrelid = ANY(%(relids)s::oid[]) AND a.attnum > 0 AND NOT a.attisdropped
"""

# Constraint-backing indexes are omitted: those facts ride `keys`, and a
# bare unique index is deliberately a hash-excluded physical artifact
# until promoted to a declared constraint (§4.5 registration record).
_INDEXES_SQL = """
SELECT i.indrelid, pg_catalog.pg_get_indexdef(i.indexrelid) AS definition
FROM pg_catalog.pg_index i
WHERE i.indrelid = ANY(%(relids)s::oid[])
  AND i.indisvalid AND i.indislive
  AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint con
                  WHERE con.conindid = i.indexrelid)
"""

# SS-5 capture (spec §4.5 registration record, ruling D-96.3d). Verbatim
# `pg_get_constraintdef` output — the engine's own rendering of its own
# constraint, never parsed into a vocabulary here (S-8).
#
# `contype = 'c'` is the whole filter, and it does the scope work by
# construction rather than by convention: NOT NULL arrives as 'n' on
# PG17+ and is already carried by `columns[].nullable`; PRIMARY KEY /
# UNIQUE / FOREIGN KEY ('p'/'u'/'f') ride `keys`; exclusion constraints
# ('x') and domain constraints stay dropped as SS-6/SS-7 territory.
#
# `conrelid <> 0` excludes domain constraints, which live in pg_constraint
# with contypid set and conrelid zero — they would otherwise attach to
# whatever table oid 0 sorts against.
_CHECKS_SQL = """
SELECT con.conrelid, pg_catalog.pg_get_constraintdef(con.oid, true) AS definition
FROM pg_catalog.pg_constraint con
WHERE con.conrelid = ANY(%(relids)s::oid[])
  AND con.contype = 'c'
  AND con.conrelid <> 0
"""

_SERVER_VERSION_SQL = "SELECT current_setting('server_version_num')::int"


def _columns_by_rel(conn, relids: list[int]) -> dict[int, list[dict]]:
    if not relids:
        return {}
    raw = defaultdict(list)
    for relid, attnum, name, type_, nullable, default, descr in conn.execute(
        _COLUMNS_SQL, {"relids": relids}
    ):
        raw[relid].append((attnum, name, type_, nullable, default, descr))
    out: dict[int, list[dict]] = {}
    for relid, rows in raw.items():
        rows.sort(key=lambda r: r[0])  # attnum order; ordinal = dense rank
        out[relid] = [
            {
                "name": name,
                "type": type_,
                "nullable": nullable,
                "default": default,
                "ordinal": i,
                "description": descr,
            }
            for i, (_, name, type_, nullable, default, descr) in enumerate(rows, start=1)
        ]
    return out


def _keys_by_rel(conn, relids: list[int]) -> dict[int, dict]:
    if not relids:
        return {}
    cons = conn.execute(_CONSTRAINTS_SQL, {"relids": relids}).fetchall()

    # FK targets may live outside the selected relids (even outside the
    # selected schemas — `ref` still names them, S-1 identity is intact).
    ref_relids = sorted({confrelid for _, ctype, _, confrelid, _ in cons if ctype == "f"})
    lookup_ids = sorted(set(relids) | set(ref_relids))
    rel_names = {
        oid: f"{nsp}.{rel}"
        for oid, nsp, rel in conn.execute(_REL_NAMES_SQL, {"relids": lookup_ids})
    }
    attnames: dict[int, dict[int, str]] = defaultdict(dict)
    for relid, attnum, name in conn.execute(_ATTNAMES_SQL, {"relids": lookup_ids}):
        attnames[relid][attnum] = name

    out: dict[int, dict] = defaultdict(lambda: {"primary": [], "unique": [], "foreign": []})
    for relid, ctype, conkey, confrelid, confkey in cons:
        names = [attnames[relid][n] for n in conkey]  # source-declared order (§6 rule 5)
        if ctype == "p":
            out[relid]["primary"] = names
        elif ctype == "u":
            out[relid]["unique"].append(names)
        elif ctype == "f":
            out[relid]["foreign"].append(
                {
                    "columns": names,
                    "ref": rel_names[confrelid],
                    "ref_columns": [attnames[confrelid][n] for n in confkey],
                }
            )

    # Fully deterministic emission order (the §6 canonicalizer sorts
    # foreign by (columns, ref) only, and its stable sort then preserves
    # whatever order ties arrive in), and empty arrays omitted — D-4:
    # `{}` vs `{"primary": []}` hash differently, so pick one form ever.
    keys: dict[int, dict] = {}
    for relid, k in out.items():
        k["unique"].sort()
        k["foreign"].sort(key=lambda fk: (fk["columns"], fk["ref"], fk["ref_columns"]))
        keys[relid] = {name: v for name, v in k.items() if v}
    return keys


def _indexes_by_rel(conn, relids: list[int]) -> dict[int, list[str]]:
    if not relids:
        return {}
    out = defaultdict(list)
    for relid, definition in conn.execute(_INDEXES_SQL, {"relids": relids}):
        out[relid].append(definition)
    return {relid: sorted(defs) for relid, defs in out.items()}


def _checks_by_rel(conn, relids: list[int]) -> dict[int, list[str]]:
    """SS-5: CHECK definitions per relation, lexicographically sorted.

    Sorted here rather than left to the catalog: `pg_constraint` order is
    not stable across dump/restore, and S-3 requires the same source state
    to produce a byte-identical canonical body. Duplicates are impossible
    (constraint names are unique per relation), so no dedupe is needed.
    """
    if not relids:
        return {}
    out = defaultdict(list)
    for relid, definition in conn.execute(_CHECKS_SQL, {"relids": relids}):
        out[relid].append(definition)
    return {relid: sorted(defs) for relid, defs in out.items()}


def introspect_connection(conn, schemas: list[str] | None) -> tuple[list[dict], dict]:
    """Introspect one open psycopg connection into (objects, source_properties)."""
    for statement in SESSION_SETUP:
        conn.execute(statement)

    rels = conn.execute(_OBJECTS_SQL, {"schemas": schemas}).fetchall()
    relids = [oid for oid, *_ in rels]
    columns = _columns_by_rel(conn, relids)
    keys = _keys_by_rel(conn, relids)
    indexes = _indexes_by_rel(conn, relids)
    checks = _checks_by_rel(conn, relids)

    objects = []
    for oid, nsp, rel, relkind, row_estimate, description, definition in rels:
        kind = KIND_BY_RELKIND[relkind]
        stats: dict = {}
        if definition is not None:
            stats["definition"] = definition
        if kind in ("table", "materialized_view"):
            if row_estimate is not None:
                stats["row_estimate"] = row_estimate
            if oid in indexes:
                stats["indexes"] = indexes[oid]
        # SS-5: `table` only — §4.5 registers `checks` on that kind alone.
        # Omitted entirely when there are none: `{}` and `{"checks": []}`
        # hash differently, so there is exactly one form (D-4).
        if kind == "table" and oid in checks:
            stats["checks"] = checks[oid]
        objects.append(
            {
                "kind": kind,
                "schema": nsp,
                "name": rel,
                "description": description,
                "columns": columns.get(oid, []),
                "keys": keys.get(oid, {}),
                "stats": stats,
            }
        )

    version_num = conn.execute(_SERVER_VERSION_SQL).fetchone()[0]
    server_version = f"{version_num // 10000}.{version_num % 100}"
    return objects, {"server_version": server_version}
