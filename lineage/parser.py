"""SQL lineage parser: view/matview definitions -> edge attestations.

Input class: engine-deparsed canonical SELECTs (``pg_get_viewdef`` under
an empty search_path, D-19.2) — sqlglot's Postgres fidelity is trusted
for exactly that class and nothing wider (D-38 condition b; revisit path
on the first real-estate parse failure: libpg_query bindings).

sqlglot supplies parse + scope resolution only; extraction, snapshot-
inventory resolution, and failure semantics live here (D-38):

- a referenced FQN absent from the inventory is a *dangling* attribution
  (formats §3.6 first class, LP-3) — flagged, never dropped, never fatal;
- a definition that does not parse is a hard failure of the whole build
  (formats §3.6 second class, D-41), attributable by object FQN and
  ``view-def sha256:`` of the failing definition.

Column mappings follow D-42: ``from`` lists only the edge's source-node
columns, column-free derivations emit ``from: []``, star expansion binds
to the snapshot's recorded columns (MC-5), WHERE/JOIN/GROUP-BY-only
columns produce no mapping (FM-6), aliases resolve away everywhere.
"""

import hashlib
import logging
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import Scope, build_scope

logger = logging.getLogger(__name__)

# Kinds whose objects can appear in a FROM clause (the relation
# inventory); unknown kinds are skipped by consumers (S-5) and therefore
# resolve as dangling here, which is the honest reading.
RELATION_KINDS = frozenset({"table", "view", "materialized_view"})

# Kinds whose stats.definition feeds the parser (snapshot §4.2).
DEFINED_KINDS = frozenset({"view", "materialized_view"})

# D-42.1 operation precedence, strongest first; `rename` doubles as the
# pure-passthrough floor. ingest/business-rule are never sql-parse ops.
_OP_PRECEDENCE = ("aggregate", "dedupe", "join", "derive", "cast", "rename", "filter")


class LineageParseError(Exception):
    """A stats.definition the parser cannot parse (formats §3.6).

    Hard failure of the whole graph build — loud and attributable: the
    message names the object FQN and the view-def sha256 of the failing
    definition so the fix path is immediate.
    """

    def __init__(self, fqn: str, definition_ref: str, cause: str):
        self.fqn = fqn
        self.definition_ref = definition_ref
        super().__init__(
            f"cannot parse stats.definition of {fqn} ({definition_ref}): {cause}"
        )


def definition_ref(definition: str) -> str:
    """Evidence ref pinning exactly the parsed text (§3.3 example shape)."""
    digest = hashlib.sha256(definition.encode("utf-8")).hexdigest()
    return f"view-def sha256:{digest}"


@dataclass(frozen=True)
class _Relation:
    """A FROM-clause relation resolved against the snapshot inventory."""

    fqn: str
    schema: str | None  # None => dangling, schema not determinable
    name: str
    resolved: bool
    kind: str  # snapshot kind, or "external" when dangling (D-41)
    columns: tuple[str, ...]  # ordinal order; empty when dangling


class _Inventory:
    """Relation lookup over one snapshot (identity S-1, sql kinds only)."""

    def __init__(self, snapshot: dict):
        self.system = snapshot["system"]
        self._by_key: dict[tuple[str, str], dict] = {}
        self._by_name: dict[str, list[str]] = {}
        for obj in snapshot["objects"]:
            if obj["kind"] not in RELATION_KINDS:
                continue
            self._by_key[(obj["schema"], obj["name"])] = obj
            self._by_name.setdefault(obj["name"], []).append(obj["schema"])

    def resolve(self, schema: str | None, name: str) -> _Relation:
        """Resolve a relation reference; never guess (D-42.7).

        Qualified names resolve directly (the D-19.2 primary path).
        Unqualified names resolve iff exactly one relation-kind object
        with that name exists across the snapshot's schemas; zero or
        several matches take the D-41 dangling path (for these the FQN
        renders the reference as written, system-prefixed, since no
        honest schema exists).
        """
        if schema:
            obj = self._by_key.get((schema, name))
            if obj is None:
                return _Relation(
                    fqn=f"{self.system}.{schema}.{name}",
                    schema=schema, name=name, resolved=False,
                    kind="external", columns=(),
                )
        else:
            schemas = self._by_name.get(name, [])
            if len(schemas) != 1:
                if len(schemas) > 1:
                    logger.warning(
                        "unqualified relation %r is ambiguous across schemas %s; "
                        "not guessing (D-42.7) — marking dangling", name, sorted(schemas),
                    )
                return _Relation(
                    fqn=f"{self.system}.{name}",
                    schema=None, name=name, resolved=False,
                    kind="external", columns=(),
                )
            obj = self._by_key[(schemas[0], name)]
        return _Relation(
            fqn=f"{self.system}.{obj['schema']}.{obj['name']}",
            schema=obj["schema"], name=obj["name"], resolved=True,
            kind=obj["kind"],
            columns=tuple(
                c["name"] for c in sorted(obj["columns"], key=lambda c: c["ordinal"])
            ),
        )


def snapshot_attestations(snapshot: dict) -> list[dict]:
    """Parse every view/matview definition into edge attestations.

    Returns capability-LP-shaped entries extended with the target's
    resolution facts the graph builder needs::

        {"source": <fqn>, "target": <fqn>, "operation": <taxonomy>,
         "columns": [{"from": [...], "to": ...}] | absent,
         "evidence": {"tier": "sql-parse", "ref": "view-def sha256:..."},
         "source_meta": {...}, "target_meta": {...}}

    Raises LineageParseError on the first unparseable definition —
    formats §3.6: the build is all-or-nothing, no partial edge sets.
    """
    inventory = _Inventory(snapshot)
    attestations: list[dict] = []
    for obj in sorted(
        snapshot["objects"], key=lambda o: (o["kind"], o["schema"], o["name"])
    ):
        if obj["kind"] not in DEFINED_KINDS:
            continue
        definition = obj.get("stats", {}).get("definition")
        if definition is None:
            continue
        attestations.extend(_parse_definition(obj, definition, inventory))
    return attestations


def _parse_definition(obj: dict, definition: str, inventory: _Inventory) -> list[dict]:
    target_fqn = f"{inventory.system}.{obj['schema']}.{obj['name']}"
    ref = definition_ref(definition)
    try:
        root = sqlglot.parse_one(definition, read="postgres")
    except ParseError as e:
        raise LineageParseError(target_fqn, ref, str(e)) from e
    if not isinstance(root, (exp.Select, exp.SetOperation)):
        raise LineageParseError(
            target_fqn, ref, f"definition is not a SELECT (got {type(root).__name__})"
        )
    scope = build_scope(root)
    if scope is None:  # pragma: no cover - build_scope is total over selects
        raise LineageParseError(target_fqn, ref, "sqlglot produced no scope")

    extractor = _Extractor(inventory, target_fqn)
    try:
        # Every relation referenced anywhere in the definition is a
        # dependency edge, including WHERE-only joins and EXISTS
        # subqueries that feed no output column.
        extractor.collect_relations(scope)
        mappings = extractor.output_mappings(scope)
    except _ExtractionError as e:
        raise LineageParseError(target_fqn, ref, str(e)) from e

    operation = _operation(root, scope)
    edges = []
    for relation in sorted(extractor.relations.values(), key=lambda r: r.fqn):
        entry = {
            "source": relation.fqn,
            "target": target_fqn,
            "operation": operation,
            "evidence": {"tier": "sql-parse", "ref": ref},
            "source_meta": {"resolved": relation.resolved, "kind": relation.kind,
                            "schema": relation.schema, "name": relation.name},
            "target_meta": {"resolved": True, "kind": obj["kind"],
                            "schema": obj["schema"], "name": obj["name"]},
        }
        columns = mappings.get(relation.fqn)
        if columns:
            entry["columns"] = [
                {"from": sorted(frm), "to": to}
                for to, frm in sorted(columns.items())
            ]
        edges.append(entry)
    return edges


class _ExtractionError(Exception):
    """Internal: extraction met a shape it cannot honestly interpret."""


class _Extractor:
    """Resolves output columns of a scope tree to base-relation columns.

    Provenance is traced *through* CTE and subquery scopes (never nodes,
    D-42.5) down to FROM-clause relations, resolved against the snapshot
    inventory. Collects every referenced relation on the way — including
    those feeding no output column (WHERE-only joins still make edges).
    """

    def __init__(self, inventory: _Inventory, target_fqn: str):
        self.inventory = inventory
        self.target_fqn = target_fqn
        self.relations: dict[str, _Relation] = {}

    # -- relation handling -------------------------------------------------

    def _relation(self, table: exp.Table) -> _Relation:
        rel = self.inventory.resolve(table.db or None, table.name)
        # Two dangling references spelled differently may share an fqn;
        # identity dedupes (F-1 spirit at node level).
        return self.relations.setdefault(rel.fqn, rel)

    def collect_relations(self, scope: Scope) -> None:
        """Register every FROM-clause relation in every scope."""
        for s in self._walk_scopes(scope):
            for source in s.sources.values():
                if not isinstance(source, Scope):
                    self._relation(source)

    # -- output extraction ---------------------------------------------------

    def output_mappings(self, scope: Scope) -> dict[str, dict[str, set[str]]]:
        """{relation fqn: {target column: {source columns}}} for the root.

        A column-free derivation (count(*)) contributes an empty source
        set on every relation feeding its scope (D-42.2); serialization
        renders it as ``from: []``.
        """
        mappings: dict[str, dict[str, set[str]]] = {}
        for target, attributions in self._scope_outputs(scope):
            if attributions is None:
                continue  # unattributable — logged where detected, never fabricated
            for rel, column in attributions:
                per_rel = mappings.setdefault(rel.fqn, {})
                per_target = per_rel.setdefault(target, set())
                if column is not None:
                    per_target.add(column)
        return mappings

    def _scope_outputs(
        self, scope: Scope
    ) -> list[tuple[str, list[tuple[_Relation, str | None]] | None]]:
        """[(output name, attributions)] for one scope, unions folded.

        Attribution ``(relation, None)`` marks a column-free derivation
        against that relation; ``None`` in place of the list marks an
        output we could not attribute (dangling star and the like).
        """
        expression = scope.expression
        if isinstance(expression, exp.SetOperation):
            # PG: output names come from the left branch; every branch
            # contributes provenance to the same targets (positional).
            left, right = scope.union_scopes
            outputs = self._scope_outputs(left)
            names = [name for name, _ in outputs]
            for i, (_, attributions) in enumerate(self._scope_outputs(right)):
                if i >= len(names):
                    break
                prior = outputs[i][1]
                if prior is None or attributions is None:
                    outputs[i] = (names[i], prior or attributions)
                else:
                    outputs[i] = (names[i], prior + attributions)
            return outputs

        outputs: list[tuple[str, list[tuple[_Relation, str | None]] | None]] = []
        for select in expression.selects:
            if isinstance(select, exp.Star):
                outputs.extend(self._expand_star(scope, qualifier=None))
            elif isinstance(select, exp.Column) and isinstance(select.this, exp.Star):
                outputs.extend(self._expand_star(scope, qualifier=select.table))
            else:
                outputs.append(
                    (select.alias_or_name, self._expression_sources(select, scope))
                )
        return outputs

    def _expand_star(
        self, scope: Scope, qualifier: str | None
    ) -> list[tuple[str, list[tuple[_Relation, str | None]] | None]]:
        """Expand * / t.* against the snapshot inventory (D-42.3).

        Binds to the referenced relation's recorded columns in ordinal
        order — snapshot is authority (MC-5); scope sources (CTEs,
        derived tables) expand to their projected names and recurse. A
        star over a dangling relation has no inventory to bind: its
        outputs are unattributable (columns omitted, D-41).
        """
        outputs: list[tuple[str, list[tuple[_Relation, str | None]] | None]] = []
        for name, source in scope.sources.items():
            if qualifier is not None and name != qualifier:
                continue
            if isinstance(source, Scope):
                inner = dict(self._named_scope_outputs(source))
                for out_name in self._scope_output_names(source):
                    outputs.append((out_name, inner.get(out_name)))
            else:
                rel = self._relation(source)
                if not rel.resolved:
                    logger.warning(
                        "star over dangling relation %s in %s cannot be expanded; "
                        "column mappings omitted (D-41)", rel.fqn, self.target_fqn,
                    )
                    continue
                for column in rel.columns:
                    outputs.append((column, [(rel, column)]))
        return outputs

    def _named_scope_outputs(self, scope: Scope):
        for name, attributions in self._scope_outputs(scope):
            yield name, attributions

    def _scope_output_names(self, scope: Scope) -> list[str]:
        return [name for name, _ in self._scope_outputs(scope)]

    def _expression_sources(
        self, expression: exp.Expression, scope: Scope
    ) -> list[tuple[_Relation, str | None]] | None:
        """Attribute one projection expression to base-relation columns."""
        columns = [
            c for c in expression.find_all(exp.Column)
            if not isinstance(c.this, exp.Star)
        ]
        if not columns:
            # Column-free derivation (count(*), constants): draws on the
            # rows of every relation feeding this scope (D-42.2).
            return [(rel, None) for rel in self._scope_relations(scope)]
        attributions: list[tuple[_Relation, str | None]] = []
        for column in columns:
            resolved = self._resolve_column(column, scope)
            if resolved is not None:
                attributions.extend(resolved)
        return attributions

    def _scope_relations(self, scope: Scope) -> list[_Relation]:
        """Base relations feeding a scope, through CTE/subquery sources."""
        relations: dict[str, _Relation] = {}
        for source in scope.sources.values():
            if isinstance(source, Scope):
                for rel in self._scope_relations(source):
                    relations[rel.fqn] = rel
            else:
                rel = self._relation(source)
                relations[rel.fqn] = rel
        return [relations[k] for k in sorted(relations)]

    def _resolve_column(
        self, column: exp.Column, scope: Scope
    ) -> list[tuple[_Relation, str | None]] | None:
        """Resolve one column reference in the scope where it appears.

        Walks the scope chain outward for correlated references. Never
        guesses: an ambiguous or unbindable reference logs a warning and
        attributes nothing (D-42.7).
        """
        owner = self._owning_scope(column, scope) or scope
        current: Scope | None = owner
        while current is not None:
            resolved = self._resolve_in_scope(column, current)
            if resolved is not None:
                return resolved
            current = current.parent
        logger.warning(
            "column %r in %s does not bind to any relation in scope; "
            "mapping omitted (never fabricated)", column.sql(), self.target_fqn,
        )
        return None

    def _owning_scope(self, column: exp.Column, scope: Scope) -> Scope | None:
        """Deepest scope whose expression contains the column node."""
        best: Scope | None = None
        for candidate in self._walk_scopes(scope):
            for c in candidate.columns:
                if c is column:
                    return candidate
            if any(n is column for n in candidate.expression.walk()):
                best = candidate
        return best

    def _walk_scopes(self, scope: Scope):
        yield scope
        for child in scope.cte_scopes + scope.derived_table_scopes + \
                scope.subquery_scopes + scope.union_scopes:
            yield from self._walk_scopes(child)

    def _resolve_in_scope(
        self, column: exp.Column, scope: Scope
    ) -> list[tuple[_Relation, str | None]] | None:
        name = column.name
        qualifier = column.table or None
        sources = scope.sources

        if qualifier is not None:
            source = sources.get(qualifier)
            if source is None:
                return None  # correlation: try the parent scope
            return self._source_column(source, name, attested=True)

        # Unqualified: bind by inventory / projected-name membership.
        candidates = []
        dangling = []
        for source in sources.values():
            if isinstance(source, Scope):
                if name in self._scope_output_names(source):
                    candidates.append(source)
            else:
                rel = self._relation(source)
                if not rel.resolved:
                    dangling.append(source)
                elif name in rel.columns:
                    candidates.append(source)
        if len(candidates) == 1:
            return self._source_column(candidates[0], name, attested=False)
        if len(candidates) > 1:
            logger.warning(
                "unqualified column %r is ambiguous across sources in %s; "
                "mapping omitted (never fabricated)", name, self.target_fqn,
            )
            return []
        if not candidates and len(dangling) == 1 and len(sources) == 1:
            # The scope's sole source is dangling: the text attests the
            # column comes from it (D-41 attested-by-text).
            return self._source_column(dangling[0], name, attested=True)
        if dangling:
            logger.warning(
                "column %r in %s may belong to a dangling relation; "
                "attribution omitted (never guessed)", name, self.target_fqn,
            )
            return []
        return None  # nothing here: correlated reference, walk outward

    def _source_column(
        self, source, name: str, attested: bool
    ) -> list[tuple[_Relation, str | None]] | None:
        if isinstance(source, Scope):
            inner = dict(self._named_scope_outputs(source))
            if name in inner:
                return inner[name]
            return []  # projected name unknown — engine SQL cannot produce this
        rel = self._relation(source)
        if rel.resolved:
            if name in rel.columns:
                return [(rel, name)]
            logger.warning(
                "column %s.%s referenced by %s is not in the snapshot inventory; "
                "mapping omitted (snapshot is authority, MC-5)",
                rel.fqn, name, self.target_fqn,
            )
            return []
        if attested:
            return [(rel, name)]  # dangling but attested by the text (D-41)
        return []


def _operation(root: exp.Expression, scope: Scope) -> str:
    """D-42.1: strongest transformation the defining query applies."""
    nodes = list(root.walk())
    exhibits = {
        "aggregate": any(isinstance(n, (exp.AggFunc, exp.Group)) for n in nodes),
        "dedupe": any(isinstance(n, exp.Distinct) for n in nodes)
        or any(
            isinstance(n, exp.SetOperation) and n.args.get("distinct")
            for n in nodes
        ),
        "join": any(isinstance(n, exp.Join) for n in nodes),
        "derive": _has_derived_projection(root),
        "cast": _has_cast_projection(root),
        "rename": _has_renamed_projection(root),
        "filter": any(isinstance(n, exp.Where) for n in nodes),
    }
    for op in _OP_PRECEDENCE:
        if exhibits[op]:
            return op
    return "rename"  # pure passthrough floor (D-42.1)


def _all_projections(root: exp.Expression):
    for select in root.find_all(exp.Select):
        yield from select.selects


def _unalias(expression: exp.Expression) -> exp.Expression:
    return expression.this if isinstance(expression, exp.Alias) else expression


def _has_derived_projection(root: exp.Expression) -> bool:
    for select in _all_projections(root):
        inner = _unalias(select)
        if isinstance(inner, (exp.Column, exp.Star)):
            continue
        if isinstance(inner, exp.Cast) and isinstance(inner.this, exp.Column):
            continue
        return True
    return False


def _has_cast_projection(root: exp.Expression) -> bool:
    return any(
        isinstance(inner := _unalias(s), exp.Cast)
        and isinstance(inner.this, exp.Column)
        for s in _all_projections(root)
    )


def _has_renamed_projection(root: exp.Expression) -> bool:
    return any(
        isinstance(s, exp.Alias)
        and isinstance(s.this, exp.Column)
        and s.alias != s.this.name
        for s in _all_projections(root)
    )
