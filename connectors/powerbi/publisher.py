"""Power BI push-model publisher — the core data-plane leg (RA-2/RA-6).

Two modes under the capability §8.2 two-call contract (report-authoring
§4/§5/§7):

`deliver_model` — creates or updates ONE push semantic model per
artifact id (`cl-<artifact-id-short>`), fed exclusively from the
gateway-executed results the payload carries (RA-2: the adapter holds a
Power BI credential and nothing else; no database credential exists on
this path and no query is ever run here). Tables are named per
result-set alias; column types follow the pinned QE-5 → PowerBIDataType
map; relationships come only from the artifact's blend keys.

`attest` — a pure function: shapes the §8.2 attest result with the
workspace report URL from the pinned webUrl template. No Microsoft call
is made; the skill already verified the deploy (RA-7) and the core owns
the attestation record.

Delivery is **complete-or-previous** (§5, AT-8): every check that can
fail — schemas, limits, encodability — runs BEFORE the first mutation;
a wire failure mid-replacement restores the already-replaced tables
from the payload's `previous` results, and a first delivery that fails
midway deletes the dataset it just created (previous state = absent).
Only a double fault (delivery AND restore failing) leaves a mixed
model, and that surfaces as the loud `delivery_state_inconsistent`
naming each table's state — reported, never papered over.

Relationship direction is derived from the artifact alone: the blend's
`join` names the preserved side, so the OTHER side is the lookup
(dimension) the many-to-one relationship points at — `join: left` →
toTable = the right query's table. The §5 default ("toward the
dimension side named by the entity doc's role") is a KB-side fact the
core validated when it checked the blend keys against the entity doc;
what reaches this adapter is the artifact's own declaration.

Push limits (pinned, reference.PUSH_LIMITS) are checked at delivery;
exceeding one raises the actionable `push_limit_exceeded` capability
error naming the limit, the measured value, and the RA-6
Fabric/DirectLake escalation — never a silent truncation.
"""

from __future__ import annotations

import json
import os

from connectors.powerbi import reference as ref
from connectors.powerbi.client import PowerBIClient
from connectors.sdk.errors import ConfigError, ConnectorError, GuardrailViolation, SourceUnavailable
from connectors.sdk.providers import Identity, Publisher, PublishRequest, PublishResult

_RA6_ESCALATION = (
    "the RA-6 escalation is the Fabric lakehouse/DirectLake leg "
    "(report-authoring spec §2 RA-6) — a register decision, not a workaround"
)


def dataset_name(artifact_id: str) -> str:
    """`cl-<artifact-id-short>` (§5, RA-D): the id without its `ra-`
    prefix, first 12 characters — stable across revisions."""
    short = artifact_id[3:] if artifact_id.startswith("ra-") else artifact_id
    short = "".join(ch for ch in short if ch.isalnum())[:12]
    if not short:
        raise ConfigError(f"artifact id {artifact_id!r} yields no dataset short name")
    return f"cl-{short}"


def _push_limit(name: str, measured: int | str, limit: int | str, where: str) -> GuardrailViolation:
    return GuardrailViolation(
        f"push-model limit exceeded at {where}: {name} is {measured}, the pinned "
        f"Power BI limit is {limit} (reference.PUSH_LIMITS); {_RA6_ESCALATION}",
        capability_code="push_limit_exceeded",
        detail={"limit": name, "measured": measured, "allowed": limit},
    )


def _limit_proximity(counts: list[tuple[str, int, int, str]]) -> list[dict]:
    """RA-F tripwire (D-96.3e): a delivery that clears a pinned push limit
    but stands at >=80% of it is telemetry, not a failure — the escalation
    decision should fire on evidence of approach, not on the first
    push_limit_exceeded refusal. Reported in the result detail; the core
    surfaces it to health. Threshold integer-exact (measured*5 >=
    allowed*4), no float edge at the boundary."""
    return [
        {"limit": name, "measured": measured, "allowed": allowed, "at": where}
        for name, measured, allowed, where in counts
        if measured * 5 >= allowed * 4
    ]


class _TablePlan:
    def __init__(self, name: str, columns: list[dict], rows: list[dict], notes: list[str]):
        self.name = name
        self.columns = columns  # [{name, dataType}]
        self.rows = rows  # encoded row objects, ready to POST
        self.notes = notes
        self.column_meta: list[dict] = []  # delivered.tables[].columns entries


class PowerBIPublisher(Publisher):
    SUPPORTED_ARTIFACT_VERSIONS = ("1",)

    def publish(
        self,
        config: dict,
        request: PublishRequest,
        identity: Identity,
        flags: dict,
    ) -> PublishResult:
        # PB-1 / CC-8: this adapter implements the api class and nothing
        # else; a registration asking otherwise is a release bug.
        create_report = flags.get("create_report")
        if create_report != "api":
            raise ConfigError(
                f"powerbi publishes via the api two-call contract only; effective "
                f"create_report={create_report!r} cannot be honored (PB-1)"
            )
        if request.mode not in ("deliver_model", "attest"):
            raise ConfigError(
                "powerbi requires payload.mode 'deliver_model' or 'attest' "
                f"(got {request.mode!r}) — capability §8.2 amendment"
            )
        workspace_id = config.get("workspace_id")
        if not isinstance(workspace_id, str) or not workspace_id:
            raise ConfigError("config.workspace_id is required")
        artifact_id = request.artifact.get("id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ConfigError("artifact.id (stable UUID, formats §4.1) is required")

        if request.mode == "attest":
            return self._attest(workspace_id, request)
        return self._deliver(config, workspace_id, artifact_id, request)

    # --- attest (pure) -------------------------------------------------------

    def _attest(self, workspace_id: str, request: PublishRequest) -> PublishResult:
        attestation = request.attestation or {}
        report_id = attestation.get("report_id")
        definition_hash = attestation.get("definition_hash")
        if not isinstance(report_id, str) or not report_id:
            raise ConfigError("attest requires attestation.report_id")
        if not isinstance(definition_hash, str) or not _sha256_shaped(definition_hash):
            raise ConfigError(
                "attest requires a well-formed attestation.definition_hash "
                "('sha256:' + 64 lowercase hex)"
            )
        url = ref.REPORT_WEB_URL_TEMPLATE.format(groupId=workspace_id, reportId=report_id)
        return PublishResult(
            mode="attest",
            created=[{"type": "report", "id": report_id, "url": url}],
            pending_human_steps=[],
            backing=[],
            detail={
                "attested": {
                    "artifact_id": request.artifact.get("id"),
                    "workspace_id": workspace_id,
                    "report_id": report_id,
                    "definition_hash": definition_hash,
                }
            },
        )

    # --- deliver_model -------------------------------------------------------

    def _deliver(
        self,
        config: dict,
        workspace_id: str,
        artifact_id: str,
        request: PublishRequest,
    ) -> PublishResult:
        results = request.results
        if not isinstance(results, dict) or not results:
            raise ConfigError(
                "deliver_model requires payload.results — the gateway-executed "
                "result per artifact query (RA-2); nothing else may feed a model"
            )

        # ---- validation phase: everything that can fail, before any wire ----
        plans = self._plan_tables(request.artifact, results)
        relationships = self._plan_relationships(request.artifact, plans)
        limits = ref.PUSH_LIMITS
        proximity = _limit_proximity(
            [("tables", len(plans), limits["max_tables"], "model"),
             ("relationships", len(relationships), limits["max_relationships"], "model")]
            + [entry for plan in plans for entry in (
                ("columns", len(plan.columns), limits["max_columns_per_table"],
                 f"table {plan.name!r}"),
                ("rows", len(plan.rows), limits["max_rows_per_table_none_retention"],
                 f"table {plan.name!r}"),
            )]
        )
        client = self._client(config)

        # ---- locate the model ------------------------------------------------
        name = dataset_name(artifact_id)
        _, _, listing = client.call(
            "datasets.list_in_group", params={"groupId": workspace_id},
        )
        existing = _find_dataset(listing, name)

        if existing is None:
            dataset_id, web_url = self._create(client, workspace_id, name, plans, relationships)
        else:
            dataset_id = str(existing.get("id"))
            web_url = str(existing.get("webUrl") or "")
            self._revise(client, workspace_id, dataset_id, plans, request.previous)

        backing = _backing_entries(request.artifact)
        notes = [note for plan in plans for note in plan.notes]
        return PublishResult(
            mode="deliver_model",
            created=[{"type": "dataset", "id": dataset_id, "url": web_url}],
            pending_human_steps=[],
            backing=backing,
            detail={
                "dataset_name": name,
                "delivered": {
                    "workspace_id": workspace_id,
                    "dataset_id": dataset_id,
                    "tables": [
                        {
                            "name": plan.name,
                            "columns": plan.column_meta,
                            "rows_delivered": len(plan.rows),
                        }
                        for plan in plans
                    ],
                },
                **({"precision_notes": notes} if notes else {}),
                **({"limit_proximity": proximity} if proximity else {}),
            },
        )

    def _client(self, config: dict) -> PowerBIClient:
        tenant_id = config.get("tenant_id")
        client_id = config.get("client_id")
        secret_env = config.get("client_secret_env")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise ConfigError("config.tenant_id is required")
        if not isinstance(client_id, str) or not client_id:
            raise ConfigError("config.client_id is required")
        if not isinstance(secret_env, str) or not secret_env:
            raise ConfigError(
                "config.client_secret_env is required — the runner resolves the "
                "client_secret credential reference into it (J-4)"
            )
        secret = os.environ.get(secret_env, "")
        if not secret:
            raise ConfigError(
                f"client secret env {secret_env} is empty — the registration must "
                'carry credentials: [{key: "client_secret", ref: "env://…", '
                'required_for: ["publish"]}]'
            )
        # Fixture stubs rewrite the HOST after the pinned gate; the
        # canonical path shape is always the verified one (client.py).
        base_overrides = {
            canonical: str(config[key]).rstrip("/")
            for canonical, key in (
                (ref.PBI_API_BASE, "api_base_override"),
                (ref.LOGIN_BASE, "login_base_override"),
                (ref.FABRIC_API_BASE, "fabric_base_override"),
            )
            if isinstance(config.get(key), str) and config.get(key)
        }
        return PowerBIClient(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=secret,
            base_overrides=base_overrides,
        )

    # ---- planning (no wire) -------------------------------------------------

    def _plan_tables(self, artifact: dict, results: dict) -> list[_TablePlan]:
        queries = artifact.get("queries")
        if not isinstance(queries, list) or not queries:
            raise ConfigError("artifact carries no queries; nothing to deliver")
        limits = ref.PUSH_LIMITS
        if len(queries) > limits["max_tables"]:
            raise _push_limit("tables", len(queries), limits["max_tables"], "model")

        plans: list[_TablePlan] = []
        for query in queries:
            qname = query.get("name") if isinstance(query, dict) else None
            if not isinstance(qname, str) or not qname:
                raise ConfigError("every artifact query needs a name (formats §4.2)")
            result = results.get(qname)
            if not isinstance(result, dict):
                raise ConfigError(
                    f"deliver_model payload carries no result for query {qname!r} — "
                    "every artifact query must arrive gateway-executed (RA-2)"
                )
            if result.get("truncated") is True:
                # Defense in depth: the core refuses this before enqueue.
                raise GuardrailViolation(
                    f"result for query {qname!r} is truncated; a capped result "
                    "must never quietly become the model (CI-7)",
                    capability_code="row_cap",
                )
            columns = result.get("columns")
            rows = result.get("rows")
            if not isinstance(columns, list) or not columns:
                raise ConfigError(f"result for query {qname!r} carries no columns")
            if not isinstance(rows, list):
                raise ConfigError(f"result for query {qname!r} carries no rows array")
            if len(columns) > limits["max_columns_per_table"]:
                raise _push_limit(
                    "columns", len(columns), limits["max_columns_per_table"], f"table {qname!r}"
                )
            if len(rows) > limits["max_rows_per_table_none_retention"]:
                raise _push_limit(
                    "rows", len(rows), limits["max_rows_per_table_none_retention"],
                    f"table {qname!r}",
                )

            plan_columns: list[dict] = []
            column_meta: list[dict] = []
            notes: list[str] = []
            converters: list[tuple[str, object]] = []
            for column in columns:
                cname = column.get("name") if isinstance(column, dict) else None
                ctype = column.get("type") if isinstance(column, dict) else None
                if not isinstance(cname, str) or not cname:
                    raise ConfigError(f"query {qname!r}: a result column has no name")
                source_type = ctype if isinstance(ctype, str) else ""
                pbi_type, note = ref.qe5_to_pbi_type(source_type)
                body = {"name": cname, "dataType": pbi_type}
                ref.assert_emitted_fields("column", body)
                plan_columns.append(body)
                meta = {"name": cname, "type": pbi_type, "source_type": source_type}
                if note:
                    meta["note"] = note
                    notes.append(f"{qname}.{cname}: {note}")
                column_meta.append(meta)
                converters.append((pbi_type, cname))

            encoded_rows = [
                _encode_row(qname, plan_columns, converters, row, limits)
                for row in rows
            ]
            plan = _TablePlan(qname, plan_columns, encoded_rows, notes)
            plan.column_meta = column_meta
            plans.append(plan)
        return plans

    def _plan_relationships(self, artifact: dict, plans: list[_TablePlan]) -> list[dict]:
        blend = artifact.get("blend")
        if blend is None:
            return []
        if not isinstance(blend, dict):
            raise ConfigError("artifact.blend must be an object when present")
        keys = blend.get("keys")
        if not isinstance(keys, list) or not keys:
            raise ConfigError("artifact.blend.keys must be a non-empty list (formats §4.5)")
        left = blend.get("left")
        right = blend.get("right")
        table_names = {plan.name for plan in plans}
        if left not in table_names or right not in table_names:
            raise ConfigError(
                f"blend names queries {left!r} × {right!r} but the delivered tables "
                f"are {sorted(table_names)}"
            )
        join = blend.get("join") if isinstance(blend.get("join"), str) else "left"
        # The preserved side keeps every row (the many/fact side); the
        # other side is the lookup the relationship points at.
        from_table, to_table = (left, right) if join != "right" else (right, left)

        columns_by_table = {
            plan.name: {column["name"] for column in plan.columns} for plan in plans
        }
        relationships: list[dict] = []
        for index, key in enumerate(keys):
            if not isinstance(key, dict) or not key.get("entity_ref"):
                raise ConfigError(
                    "every blend key needs entity_ref — blend keys come from the "
                    "entity doc's documented mappings, never improvised (formats §4.5)"
                )
            left_column = key.get("left_column")
            right_column = key.get("right_column")
            if not isinstance(left_column, str) or not isinstance(right_column, str):
                raise ConfigError(f"blend.keys[{index}] needs left_column and right_column")
            from_column = left_column if from_table == left else right_column
            to_column = right_column if to_table == right else left_column
            if from_column not in columns_by_table[from_table]:
                raise ConfigError(
                    f"blend key column {from_column!r} is not in the delivered schema "
                    f"of {from_table!r}"
                )
            if to_column not in columns_by_table[to_table]:
                raise ConfigError(
                    f"blend key column {to_column!r} is not in the delivered schema "
                    f"of {to_table!r}"
                )
            body = {
                "name": f"rel-{index}-{from_table}-{to_table}"[:100],
                "fromTable": from_table,
                "fromColumn": from_column,
                "toTable": to_table,
                "toColumn": to_column,
                "crossFilteringBehavior": "OneDirection",
            }
            ref.assert_emitted_fields("relationship", body)
            relationships.append(body)
        if len(relationships) > ref.PUSH_LIMITS["max_relationships"]:
            raise _push_limit(
                "relationships", len(relationships), ref.PUSH_LIMITS["max_relationships"], "model"
            )
        return relationships

    # ---- create path --------------------------------------------------------

    def _create(
        self,
        client: PowerBIClient,
        workspace_id: str,
        name: str,
        plans: list[_TablePlan],
        relationships: list[dict],
    ) -> tuple[str, str]:
        tables = []
        for plan in plans:
            table_body = {"name": plan.name, "columns": plan.columns}
            ref.assert_emitted_fields("table", table_body)
            tables.append(table_body)
        body: dict = {"name": name, "defaultMode": "Push", "tables": tables}
        if relationships:
            body["relationships"] = relationships
        ref.assert_emitted_fields("create_dataset", body)

        _, _, created = client.call(
            "push.create_dataset",
            params={"groupId": workspace_id},
            query={"defaultRetentionPolicy": "None"},
            json_body=body,
            expect=(201, 202),
        )
        dataset_id = str((created or {}).get("id", "")) if isinstance(created, dict) else ""
        if not dataset_id:
            raise SourceUnavailable("dataset creation returned no id")

        try:
            for plan in plans:
                self._push_rows(client, workspace_id, dataset_id, plan)
        except ConnectorError as exc:
            # First delivery: previous state is "absent" — restore it.
            try:
                client.call(
                    "datasets.delete",
                    params={"groupId": workspace_id, "datasetId": dataset_id},
                )
            except ConnectorError as cleanup_exc:
                raise SourceUnavailable(
                    f"model delivery failed AND the created dataset could not be "
                    f"removed — the workspace holds a partial model {name!r} "
                    f"(dataset {dataset_id}); delete it manually. "
                    f"Delivery error: {exc}; cleanup error: {cleanup_exc}",
                    detail={
                        "capability_code": "delivery_state_inconsistent",
                        "dataset_id": dataset_id,
                    },
                ) from exc
            raise

        web_url = ""
        _, _, listing = client.call("datasets.list_in_group", params={"groupId": workspace_id})
        found = _find_dataset(listing, name)
        if found is not None:
            web_url = str(found.get("webUrl") or "")
        return dataset_id, web_url

    # ---- revision path ------------------------------------------------------

    def _revise(
        self,
        client: PowerBIClient,
        workspace_id: str,
        dataset_id: str,
        plans: list[_TablePlan],
        previous: dict | None,
    ) -> None:
        _, _, table_listing = client.call(
            "push.get_tables",
            params={"groupId": workspace_id, "datasetId": dataset_id},
        )
        existing_tables = {
            str(table.get("name")): table
            for table in ((table_listing or {}).get("value") or [])
            if isinstance(table, dict)
        }
        planned_names = {plan.name for plan in plans}
        if set(existing_tables) != planned_names:
            # PutTable updates; it does not create or delete. A changed
            # table SET is a model-shape change the push surface cannot
            # express in place — refuse with the real options rather
            # than leave identity behind (RA-8).
            raise ConfigError(
                f"revision changes the table set: model has {sorted(existing_tables)}, "
                f"artifact delivers {sorted(planned_names)}. The push surface cannot "
                "add or remove tables of an existing model in place; either keep the "
                "result-set aliases stable across revisions (RA-8) or retire this "
                "report (deletion is a human/workspace act, report-authoring §8) and "
                "mint a new artifact id."
            )

        # Schema updates first (atomic per table via PutTable), then row
        # replacement. Restore set tracks what a mid-flight failure must
        # roll back.
        for plan in plans:
            current = existing_tables.get(plan.name) or {}
            current_columns = [
                {"name": str(column.get("name")), "dataType": str(column.get("dataType"))}
                for column in (current.get("columns") or [])
                if isinstance(column, dict)
            ]
            if current_columns != plan.columns:
                table_body = {"name": plan.name, "columns": plan.columns}
                ref.assert_emitted_fields("table", table_body)
                client.call(
                    "push.put_table",
                    params={
                        "groupId": workspace_id,
                        "datasetId": dataset_id,
                        "tableName": plan.name,
                    },
                    json_body=table_body,
                )

        replaced: list[str] = []
        try:
            for plan in plans:
                self._replace_rows(client, workspace_id, dataset_id, plan)
                replaced.append(plan.name)
        except ConnectorError as exc:
            self._restore(client, workspace_id, dataset_id, replaced, previous, exc)
            raise

    def _restore(
        self,
        client: PowerBIClient,
        workspace_id: str,
        dataset_id: str,
        replaced: list[str],
        previous: dict | None,
        original: ConnectorError,
    ) -> None:
        """Put already-replaced tables back to the previous delivery's
        rows (§5 complete-or-previous). Raises the loud inconsistent
        state only when the restore itself fails."""
        if not replaced:
            return  # nothing mutated: the model is still entirely previous
        states: dict[str, str] = {}
        problems: list[str] = []
        for table_name in replaced:
            prior = (previous or {}).get(table_name) if isinstance(previous, dict) else None
            prior_rows = prior.get("rows") if isinstance(prior, dict) else None
            prior_columns = prior.get("columns") if isinstance(prior, dict) else None
            if not isinstance(prior_rows, list) or not isinstance(prior_columns, list):
                states[table_name] = "new-rows (no previous results to restore from)"
                problems.append(table_name)
                continue
            converters = [
                (ref.qe5_to_pbi_type(str(column.get("type", "")))[0], str(column.get("name")))
                for column in prior_columns
                if isinstance(column, dict)
            ]
            plan_columns = [{"name": cname, "dataType": ptype} for ptype, cname in converters]
            try:
                restore_plan = _TablePlan(
                    table_name,
                    plan_columns,
                    [
                        _encode_row(table_name, plan_columns, converters, row, ref.PUSH_LIMITS)
                        for row in prior_rows
                    ],
                    [],
                )
                self._replace_rows(client, workspace_id, dataset_id, restore_plan)
                states[table_name] = "restored-previous"
            except ConnectorError:
                states[table_name] = "unknown (restore failed)"
                problems.append(table_name)
        if problems:
            raise SourceUnavailable(
                "model delivery failed mid-replacement AND restore could not return "
                f"every table to the previous revision — table states: {states}. "
                "Re-delivering this revision will converge the model. "
                f"Original delivery error: {original}",
                detail={"capability_code": "delivery_state_inconsistent", "tables": states},
            ) from original

    # ---- row transport ------------------------------------------------------

    def _replace_rows(
        self, client: PowerBIClient, workspace_id: str, dataset_id: str, plan: _TablePlan
    ) -> None:
        client.call(
            "push.delete_rows",
            params={
                "groupId": workspace_id,
                "datasetId": dataset_id,
                "tableName": plan.name,
            },
        )
        self._push_rows(client, workspace_id, dataset_id, plan)

    def _push_rows(
        self, client: PowerBIClient, workspace_id: str, dataset_id: str, plan: _TablePlan
    ) -> None:
        batch_size = ref.PUSH_LIMITS["max_rows_per_post"]
        for start in range(0, len(plan.rows), batch_size):
            batch = plan.rows[start:start + batch_size]
            body = {"rows": batch}
            ref.assert_emitted_fields("post_rows", body)
            client.call(
                "push.post_rows",
                params={
                    "groupId": workspace_id,
                    "datasetId": dataset_id,
                    "tableName": plan.name,
                },
                json_body=body,
            )


# --- helpers ----------------------------------------------------------------


def _sha256_shaped(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    digest = value[len("sha256:"):]
    return len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest)


def _find_dataset(listing: object, name: str) -> dict | None:
    if not isinstance(listing, dict):
        return None
    for dataset in listing.get("value") or []:
        if isinstance(dataset, dict) and dataset.get("name") == name:
            return dataset
    return None


def _backing_entries(artifact: dict) -> list[dict]:
    backing: list[dict] = []
    for query in artifact.get("queries") or []:
        if not isinstance(query, dict):
            continue
        info = query.get("backing")
        if isinstance(info, dict) and info.get("mode") == "reporting_view":
            entry = {"type": "reporting_view", "ref": str(info.get("ref", ""))}
            if entry not in backing:
                backing.append(entry)
    return backing


def _encode_row(
    table: str,
    columns: list[dict],
    converters: list[tuple[str, str]],
    row: object,
    limits: dict,
) -> dict:
    """QE-5 result row (positional array) → push-API row object, typed
    per the pinned map. Conversion failures are OUR defect and fail the
    delivery before any mutation, naming table and column."""
    if not isinstance(row, list) or len(row) != len(columns):
        raise ConfigError(
            f"table {table!r}: a result row has {len(row) if isinstance(row, list) else 'no'} "
            f"values for {len(columns)} columns"
        )
    encoded: dict = {}
    for (pbi_type, cname), value in zip(converters, row):
        if value is None:
            encoded[cname] = None
            continue
        try:
            if pbi_type == "Int64":
                # QE-5 delivers a beyond-float64-safe integer as a
                # string; int() recovers it exactly, and json emits the
                # exact digits — no precision loss on this path.
                converted: object = int(value)
            elif pbi_type == "Double":
                converted = float(value)
            elif pbi_type == "Boolean":
                converted = bool(value)
            elif pbi_type == "DateTime":
                converted = str(value)
            else:  # String
                if isinstance(value, (dict, list)):
                    converted = json.dumps(value, separators=(",", ":"), sort_keys=True)
                else:
                    converted = str(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"table {table!r} column {cname!r}: value cannot encode as {pbi_type} "
                f"({type(exc).__name__}) — the QE-5 result and the pinned type map "
                "disagree; this is our defect, not the source's"
            ) from exc
        if isinstance(converted, str) and len(converted) > limits["max_string_value_chars"]:
            raise _push_limit(
                "string value length",
                len(converted),
                limits["max_string_value_chars"],
                f"table {table!r} column {cname!r}",
            )
        encoded[cname] = converted
    return encoded
