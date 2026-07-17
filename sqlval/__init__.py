"""SQL-dialect validation for ``validate_sql`` (MCP spec §6.6, CP-4).

Parser-based (sqlglot — the D-38 stack choice, same engine as the
lineage parser): the refusal set is decided on the AST, never regex
(MCP-R7). One statement in, a verdict out:

- exactly one statement (MCP-R6 — multi-statement smuggling);
- the statement class is a plain query: SELECT / set operations, CTEs
  included — any DML/DDL/utility node anywhere in the tree (CTE-wrapped
  writes included) is refused, as are locking clauses
  (``SELECT … FOR UPDATE``) and ``COPY``/``DO``/other commands;
- no side-effecting or file-reading function calls (shipped denylist,
  extendable per system from the conventions guardrail block);
- every referenced object and column resolves against the latest
  accepted snapshot (MT-8: failures cite the object).

The core invokes this as a stage CLI (ruling C1/C2): JSON request file
in, JSON verdict on stdout. Exit 0 = pass, 1 = fail, 2 = internal/usage
error (the caller treats 2 as validator-unavailable, mirroring
``snapshot.accept``).
"""

from __future__ import annotations

import hashlib
from typing import Any

import sqlglot
from sqlglot import expressions as exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

# Side-effecting / environment-reaching functions refused regardless of
# statement class (MCP-R7). Lowercase; matched on the called name.
DENIED_FUNCTIONS = frozenset({
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_ls_waldir",
    "pg_stat_file",
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_rotate_logfile",
    "pg_switch_wal",
    "pg_create_restore_point",
    "pg_promote",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
    "dblink_connect",
    "pg_notify",
    "set_config",
    "query_to_xml",
    "query_to_json",
    "xpath_table",
})

# AST node classes that terminate the query-only claim wherever they
# appear (CTE-wrapped writes surface as these nodes inside the tree).
_WRITE_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Copy,
    exp.Grant,
    exp.Command,  # COPY/DO/CALL/VACUUM/... — anything sqlglot keeps opaque
    exp.Set,
    exp.Use,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)

_QUERY_ROOTS: tuple[type[exp.Expression], ...] = (exp.Select, exp.SetOperation)


def _finding(severity: str, code: str, ref: str | None, message: str) -> dict[str, Any]:
    return {"severity": severity, "code": code, "ref": ref, "message": message}


def _cte_names(tree: exp.Expression) -> set[str]:
    names: set[str] = set()
    for cte in tree.find_all(exp.CTE):
        alias = cte.alias
        if alias:
            names.add(alias.lower())
    return names


def validate_statement(request: dict[str, Any]) -> dict[str, Any]:
    """Validate one SQL statement against a snapshot-derived schema.

    Request keys: ``statement`` (str), ``engine`` (sqlglot dialect,
    default ``postgres``), ``system`` (name used in finding refs),
    ``default_schema`` (default ``public``), ``objects`` (list of
    ``{schema, name, kind, columns: [str]}``), ``denied_functions``
    (extra names, merged with the shipped denylist).
    """
    statement = request.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        return {
            "verdict": "fail",
            "findings": [_finding("error", "invalid_argument", None, "statement (non-empty string) required")],
        }
    engine = request.get("engine") or "postgres"
    system = request.get("system") or ""
    default_schema = request.get("default_schema") or "public"
    objects = request.get("objects") or []
    denied = set(DENIED_FUNCTIONS)
    for name in request.get("denied_functions") or []:
        denied.add(str(name).lower())

    findings: list[dict[str, Any]] = []

    # 1. Parse (the refusal set is AST-decided, MCP-R7).
    try:
        statements = sqlglot.parse(statement, read=engine)
    except ParseError as e:
        return {
            "verdict": "fail",
            "findings": [_finding("error", "parse_error", None, str(e).split("\n")[0])],
        }
    statements = [s for s in statements if s is not None]

    # 2. Exactly one statement (MCP-R6).
    if len(statements) != 1:
        return {
            "verdict": "fail",
            "findings": [
                _finding(
                    "error",
                    "multi_statement",
                    None,
                    f"{len(statements)} statements found; validate_sql binds exactly one",
                )
            ],
        }
    tree = statements[0]

    # 3. Root must be a query.
    if not isinstance(tree, _QUERY_ROOTS):
        findings.append(
            _finding(
                "error",
                "statement_class",
                None,
                f"statement class {type(tree).__name__} is not a SELECT query (select-only surface)",
            )
        )

    # 4. No write/utility node anywhere in the tree (CTE-wrapped writes).
    for node in tree.walk():
        if isinstance(node, _WRITE_NODES):
            findings.append(
                _finding(
                    "error",
                    "statement_class",
                    None,
                    f"{type(node).__name__} operation inside the statement; select-only surface refuses it",
                )
            )
            break

    # 5. Locking clauses (SELECT … FOR UPDATE/SHARE).
    for node in tree.find_all(exp.Lock):
        findings.append(
            _finding("error", "locking_clause", None, "locking clause (FOR UPDATE/SHARE) refused on the read surface")
        )
        break

    # 6. Function denylist.
    seen_fns: set[str] = set()
    for node in tree.find_all(exp.Func):
        name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
        if name in denied and name not in seen_fns:
            seen_fns.add(name)
            findings.append(
                _finding("error", "denied_function", name, f"function {name}() is refused on the read surface")
            )

    if findings:
        return {"verdict": "fail", "findings": findings}

    # 7. Object resolution against the snapshot surface.
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for obj in objects:
        by_key[(str(obj.get("schema", "")).lower(), str(obj.get("name", "")).lower())] = obj
    ctes = _cte_names(tree)
    referenced: list[str] = []
    for table in tree.find_all(exp.Table):
        name = table.name
        if not name:
            continue
        schema_name = table.db or ""
        if not schema_name and name.lower() in ctes:
            continue  # CTE reference, not a source object
        schema_name = schema_name or default_schema
        key = (schema_name.lower(), name.lower())
        fqn = f"{system}.{schema_name}.{name}" if system else f"{schema_name}.{name}"
        if key not in by_key:
            findings.append(
                _finding("error", "unknown_object", fqn, f"object {fqn} does not exist in the latest accepted snapshot")
            )
        elif fqn not in referenced:
            referenced.append(fqn)
    if findings:
        return {"verdict": "fail", "findings": findings}

    # 8. Column resolution (sqlglot qualify with the snapshot schema).
    schema_map: dict[str, dict[str, dict[str, str]]] = {}
    for (schema_name, name), obj in by_key.items():
        cols = {str(c): "TEXT" for c in obj.get("columns") or []}
        schema_map.setdefault(schema_name, {})[name] = cols
    try:
        qualify(
            tree.copy(),
            schema=schema_map,
            dialect=engine,
            db=default_schema,
            validate_qualify_columns=True,
        )
    except OptimizeError as e:
        ref = referenced[0] if len(referenced) == 1 else ", ".join(referenced) or None
        findings.append(_finding("error", "unknown_column", ref, str(e).split("\n")[0]))
        return {"verdict": "fail", "findings": findings}

    return {
        "verdict": "pass",
        "findings": [],
        "statement_class": "select",
        "statement_sha256": hashlib.sha256(statement.encode("utf-8")).hexdigest(),
        "referenced_objects": referenced,
    }
