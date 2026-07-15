"""Object FQN identity, resolution, and scored-set extraction (R4).

A canonical object FQN is ``{system}.{schema}.{name}`` for every system
(snapshot identity S-1): ``supabase.public.users``, ``gsc.standard.query``,
``ga4.standard.keyEvents:purchase``. Resolution of a suite
``expected_object`` is membership in the union of snapshot object FQNs — no
string-splitting, so a name carrying a ``:`` (GA4 ``keyEvents:*``) is never
mis-parsed.

The *scored* object set (R4) is extracted from the final executed
statement(s), never from the agent's self-declared set:

* **SQL** — table references via sqlglot, resolved against the snapshot
  inventory exactly as ``lineage/parser.py`` does (qualified names bind
  directly; an unqualified name binds iff exactly one relation carries it;
  CTE names are not base relations and are excluded). Multiple statements
  (a ``SET`` guard then a ``SELECT``) are each parsed; non-relational
  statements contribute nothing.
* **API** — GA4 names its dimensions and metrics in the request body, so
  they map straight to FQNs. GSC's ``searchanalytics`` names only
  dimensions; it returns its four standard metrics (clicks, impressions,
  ctr, position) by contract on every call, so a GSC search-analytics
  request's retrieved set includes them regardless of the body. The
  contract metric set is derived from the snapshot, not hard-coded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from lineage.parser import RELATION_KINDS

logger = logging.getLogger(__name__)

API_KINDS = frozenset({"api_dimension", "api_metric", "api_event"})


def object_fqn(system: str, schema: str, name: str) -> str:
    return f"{system}.{schema}.{name}"


@dataclass(frozen=True)
class ExtractedObjects:
    """The scored object set pulled from one executed statement (R4)."""

    fqns: frozenset[str]
    parse_ok: bool
    note: str = ""


class SnapshotInventory:
    """Object identity over the pinned snapshot set (all systems).

    Built once per suite run from the snapshots the suite resolves
    against; the union of object FQNs is the resolution authority, and the
    per-system indexes drive SQL/API scored-set extraction.
    """

    def __init__(self, snapshots: Iterable[Mapping[str, Any]]):
        self.fqns: set[str] = set()
        # SQL: {system: {relation name: [schemas]}} for unqualified binding.
        self._sql_relations: dict[str, dict[str, list[str]]] = {}
        # API: {system: {object name: fqn}}.
        self._api_names: dict[str, dict[str, str]] = {}
        # GSC-style contract metrics: {system: {metric fqns always returned}}.
        self._contract_metrics: dict[str, set[str]] = {}

        for snap in snapshots:
            system = snap["system"]
            for obj in snap["objects"]:
                kind = obj["kind"]
                schema = obj["schema"]
                name = obj["name"]
                fqn = object_fqn(system, schema, name)
                self.fqns.add(fqn)
                if kind in RELATION_KINDS:
                    self._sql_relations.setdefault(system, {}).setdefault(
                        name, []
                    ).append(schema)
                elif kind in API_KINDS:
                    self._api_names.setdefault(system, {})[name] = fqn
                    if kind == "api_metric":
                        self._contract_metrics.setdefault(system, set()).add(fqn)

    # -- resolution --------------------------------------------------------

    def resolves(self, fqn: str) -> bool:
        return fqn in self.fqns

    def unresolved(self, fqns: Iterable[str]) -> list[str]:
        return [f for f in fqns if f not in self.fqns]

    # -- scored-set extraction (R4) ---------------------------------------

    def extract(self, system: str, request: Mapping[str, Any]) -> ExtractedObjects:
        """Extract the scored object set from one executed request."""
        dialect = request.get("dialect")
        if dialect == "sql":
            return self._extract_sql(system, request.get("statement", ""))
        if dialect == "api":
            return self._extract_api(system, request)
        return ExtractedObjects(frozenset(), parse_ok=False, note=f"unknown dialect {dialect!r}")

    def _extract_sql(self, system: str, statement: str) -> ExtractedObjects:
        try:
            parsed = sqlglot.parse(statement, read="postgres")
        except ParseError as exc:
            return ExtractedObjects(frozenset(), parse_ok=False, note=f"parse error: {exc}")
        fqns: set[str] = set()
        for stmt in parsed:
            if stmt is None:
                continue
            cte_aliases = {cte.alias_or_name for cte in stmt.find_all(exp.CTE)}
            for table in stmt.find_all(exp.Table):
                schema = table.db or None
                name = table.name
                if schema is None and name in cte_aliases:
                    continue  # a CTE reference, not a base relation
                fqns.add(self._resolve_sql_relation(system, schema, name))
        return ExtractedObjects(frozenset(fqns), parse_ok=True)

    def _resolve_sql_relation(self, system: str, schema: str | None, name: str) -> str:
        if schema is not None:
            return object_fqn(system, schema, name)
        schemas = self._sql_relations.get(system, {}).get(name, [])
        if len(schemas) == 1:
            return object_fqn(system, schemas[0], name)
        if len(schemas) > 1:
            logger.warning(
                "unqualified relation %r ambiguous across %s in %s; not guessing",
                name, sorted(schemas), system,
            )
        # Unresolved: the two-part FQN cannot match a real object, which is
        # the honest reading (the reference does not bind to the inventory).
        return f"{system}.{name}"

    def _extract_api(self, system: str, request: Mapping[str, Any]) -> ExtractedObjects:
        body = request.get("body", {}) or {}
        operation = str(request.get("operation", ""))
        fqns: set[str] = set()

        dimensions = body.get("dimensions", []) or []
        for dim in dimensions:
            name = dim["name"] if isinstance(dim, Mapping) else dim
            fqns.add(self._resolve_api_name(system, str(name)))
        for metric in body.get("metrics", []) or []:
            name = metric["name"] if isinstance(metric, Mapping) else metric
            fqns.add(self._resolve_api_name(system, str(name)))

        # GSC search-analytics returns its standard metrics on every call
        # regardless of the body; the retrieved set includes them.
        if operation.startswith("searchanalytics"):
            fqns |= self._contract_metrics.get(system, set())

        return ExtractedObjects(frozenset(fqns), parse_ok=True)

    def _resolve_api_name(self, system: str, name: str) -> str:
        resolved = self._api_names.get(system, {}).get(name)
        if resolved is not None:
            return resolved
        # Not in the snapshot: a bogus/unknown dim or metric. Emit a
        # standard-schema FQN so it is visible and (correctly) matches no
        # real expected object.
        return object_fqn(system, "standard", name)
