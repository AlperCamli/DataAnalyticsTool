"""Pinned Microsoft surface references — the D-89 guardrail for Power BI.

Report-authoring spec §9 (RA-5): every Microsoft endpoint, field, and
tool shape this leg emits is pinned HERE, with the reference URL and the
date it was independently retrieved. Emitting anything outside the
pinned set raises `ConfigError` at OUR validation, before any Microsoft
call — preview drift dies in our CI, not in a customer's session. The
Looker adapter learned this the hard way (D-89: an invented connector id
fails an entire report creation, minutes later, in a browser); this
module is that lesson applied before the first Power BI call, not after.

Discipline for editors:
- Every entry in `ENDPOINTS`, every emittable field set, and every enum
  below carries a key into `REFERENCES`. Re-check the reference page
  before trusting a pin, and update `retrieved` when you do.
- The HTTP layer must route every outgoing request through
  `pinned_request()` (or build it with `pinned_endpoint()`); tests
  assert the module refuses anything unpinned (conformance AT-7).
- Adding a surface = fetch its reference page first, pin it with
  today's date, then emit against it. Never the other order.

All references below were retrieved 2026-07-29 against the live
Microsoft Learn pages.
"""

from __future__ import annotations

import re
import string
from typing import Mapping

from connectors.sdk.errors import ConfigError

#: Source-of-truth pages, each independently retrieved (D-89 pattern).
REFERENCES: dict[str, dict[str, str]] = {
    "entra-client-credentials": {
        "url": "https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow",
        "retrieved": "2026-07-29",
    },
    "pbi-sp-scope": {
        # Documents the Power BI resource scope string for SP tokens.
        "url": "https://learn.microsoft.com/en-us/power-bi/developer/embedded/embed-service-principal-certificate",
        "retrieved": "2026-07-29",
    },
    "pbi-service-principal": {
        # Tenant settings + workspace membership requirements.
        "url": "https://learn.microsoft.com/en-us/power-bi/developer/embedded/embed-service-principal",
        "retrieved": "2026-07-29",
    },
    "push-datasets-index": {
        "url": "https://learn.microsoft.com/en-us/rest/api/power-bi/push-datasets",
        "retrieved": "2026-07-29",
    },
    "push-post-dataset-in-group": {
        "url": "https://learn.microsoft.com/en-us/rest/api/power-bi/push-datasets/datasets-post-dataset-in-group",
        "retrieved": "2026-07-29",
    },
    "push-post-rows-in-group": {
        "url": "https://learn.microsoft.com/en-us/rest/api/power-bi/push-datasets/datasets-post-rows-in-group",
        "retrieved": "2026-07-29",
    },
    "push-delete-rows-in-group": {
        "url": "https://learn.microsoft.com/en-us/rest/api/power-bi/push-datasets/datasets-delete-rows-in-group",
        "retrieved": "2026-07-29",
    },
    "push-put-table-in-group": {
        "url": "https://learn.microsoft.com/en-us/rest/api/power-bi/push-datasets/datasets-put-table-in-group",
        "retrieved": "2026-07-29",
    },
    "push-get-tables-in-group": {
        "url": "https://learn.microsoft.com/en-us/rest/api/power-bi/push-datasets/datasets-get-tables-in-group",
        "retrieved": "2026-07-29",
    },
    "push-limitations": {
        "url": "https://learn.microsoft.com/en-us/power-bi/developer/embedded/push-datasets-limitations",
        "retrieved": "2026-07-29",
    },
    "pbi-datatype-enum": {
        # Microsoft's own tooling enum for push dataset column types —
        # the REST reference documents no closed set, so this is the
        # authoritative published list (PowerBIDataType).
        "url": "https://learn.microsoft.com/en-us/powershell/module/microsoftpowerbimgmt.data/new-powerbicolumn?view=powerbi-ps",
        "retrieved": "2026-07-29",
    },
    "datasets-get-in-group": {
        "url": "https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/get-datasets-in-group",
        "retrieved": "2026-07-29",
    },
    "datasets-delete-in-group": {
        "url": "https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/delete-dataset-in-group",
        "retrieved": "2026-07-29",
    },
    "groups-get-groups": {
        "url": "https://learn.microsoft.com/en-us/rest/api/power-bi/groups/get-groups",
        "retrieved": "2026-07-29",
    },
    "reports-get-in-group": {
        # Documents the report `webUrl` form served back at attest.
        "url": "https://learn.microsoft.com/en-us/rest/api/power-bi/reports/get-report-in-group",
        "retrieved": "2026-07-29",
    },
    "fabric-create-report": {
        "url": "https://learn.microsoft.com/en-us/rest/api/fabric/report/items/create-report",
        "retrieved": "2026-07-29",
    },
    "fabric-update-report-definition": {
        "url": "https://learn.microsoft.com/en-us/rest/api/fabric/report/items/update-report-definition",
        "retrieved": "2026-07-29",
    },
    "fabric-get-report-definition": {
        "url": "https://learn.microsoft.com/en-us/rest/api/fabric/report/items/get-report-definition",
        "retrieved": "2026-07-29",
    },
    "fabric-list-reports": {
        "url": "https://learn.microsoft.com/en-us/rest/api/fabric/report/items/list-reports",
        "retrieved": "2026-07-29",
    },
    "fabric-lro": {
        "url": "https://learn.microsoft.com/en-us/rest/api/fabric/articles/long-running-operation",
        "retrieved": "2026-07-29",
    },
    "fabric-report-definition": {
        # PBIR formats, part paths, definition.pbir byConnection form.
        "url": "https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/report-definition",
        "retrieved": "2026-07-29",
    },
    "realtime-retirement": {
        # Deprecation horizon for the whole push surface — see
        # PUSH_MODEL_DEPRECATION below.
        "url": "https://learn.microsoft.com/en-us/power-bi/connect-data/service-real-time-streaming",
        "retrieved": "2026-07-29",
    },
}

# --- hosts ------------------------------------------------------------------

LOGIN_BASE = "https://login.microsoftonline.com"
PBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"
FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"
REPORT_WEB_BASE = "https://app.powerbi.com"

#: OAuth resource scopes for service-principal client-credential tokens.
#: One resource per token (mixing scopes across resources is an AADSTS
#: error, per the client-credentials reference).
PBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"  # ref: pbi-sp-scope
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"  # ref: fabric-create-report (host)

# --- the emission surface ---------------------------------------------------

#: Every request this leg may emit: name -> (method, URL template, ref).
#: Templates use {param} placeholders; query strings are listed with the
#: parameters the reference documents (optional ones may be omitted at
#: call time, never invented).
ENDPOINTS: dict[str, dict[str, str]] = {
    "token": {
        "method": "POST",
        "template": LOGIN_BASE + "/{tenantId}/oauth2/v2.0/token",
        "ref": "entra-client-credentials",
    },
    "groups.list": {
        "method": "GET",
        "template": PBI_API_BASE + "/groups",
        "ref": "groups-get-groups",
    },
    "datasets.list_in_group": {
        "method": "GET",
        "template": PBI_API_BASE + "/groups/{groupId}/datasets",
        "ref": "datasets-get-in-group",
    },
    "push.create_dataset": {
        "method": "POST",
        "template": PBI_API_BASE + "/groups/{groupId}/datasets",
        "ref": "push-post-dataset-in-group",
        # Optional query parameter defaultRetentionPolicy — values in
        # RETENTION_POLICIES below.
    },
    "push.get_tables": {
        "method": "GET",
        "template": PBI_API_BASE + "/groups/{groupId}/datasets/{datasetId}/tables",
        "ref": "push-get-tables-in-group",
    },
    "push.put_table": {
        "method": "PUT",
        "template": PBI_API_BASE + "/groups/{groupId}/datasets/{datasetId}/tables/{tableName}",
        "ref": "push-put-table-in-group",
    },
    "push.post_rows": {
        "method": "POST",
        "template": PBI_API_BASE + "/groups/{groupId}/datasets/{datasetId}/tables/{tableName}/rows",
        "ref": "push-post-rows-in-group",
    },
    "push.delete_rows": {
        "method": "DELETE",
        "template": PBI_API_BASE + "/groups/{groupId}/datasets/{datasetId}/tables/{tableName}/rows",
        "ref": "push-delete-rows-in-group",
    },
    "datasets.delete": {
        "method": "DELETE",
        "template": PBI_API_BASE + "/groups/{groupId}/datasets/{datasetId}",
        "ref": "datasets-delete-in-group",
    },
    "reports.get_in_group": {
        "method": "GET",
        "template": PBI_API_BASE + "/groups/{groupId}/reports/{reportId}",
        "ref": "reports-get-in-group",
    },
    "fabric.list_reports": {
        "method": "GET",
        "template": FABRIC_API_BASE + "/workspaces/{workspaceId}/reports",
        "ref": "fabric-list-reports",
    },
    "fabric.create_report": {
        "method": "POST",
        "template": FABRIC_API_BASE + "/workspaces/{workspaceId}/reports",
        "ref": "fabric-create-report",
    },
    "fabric.update_report_definition": {
        "method": "POST",
        "template": FABRIC_API_BASE + "/workspaces/{workspaceId}/reports/{reportId}/updateDefinition",
        "ref": "fabric-update-report-definition",
        # Optional query parameter updateMetadata=True|False.
    },
    "fabric.get_report_definition": {
        "method": "POST",
        "template": FABRIC_API_BASE + "/workspaces/{workspaceId}/reports/{reportId}/getDefinition",
        "ref": "fabric-get-report-definition",
        # Optional query parameter format=.
    },
    "fabric.operation_state": {
        "method": "GET",
        "template": FABRIC_API_BASE + "/operations/{operationId}",
        "ref": "fabric-lro",
    },
    "fabric.operation_result": {
        "method": "GET",
        "template": FABRIC_API_BASE + "/operations/{operationId}/result",
        "ref": "fabric-lro",
    },
}

#: Documented query parameters per endpoint (only these may be sent).
ENDPOINT_QUERY_PARAMS: dict[str, frozenset[str]] = {
    "push.create_dataset": frozenset({"defaultRetentionPolicy"}),
    "groups.list": frozenset({"$filter", "$top", "$skip"}),
    "fabric.update_report_definition": frozenset({"updateMetadata"}),
    "fabric.get_report_definition": frozenset({"format"}),
    "fabric.list_reports": frozenset({"recursive", "rootFolderId", "continuationToken"}),
}

#: The report web URL handed back at attest, exactly the `webUrl` form
#: the Reports API documents (ref: reports-get-in-group). Constructed,
#: not fetched, so attest stays a pure function; the Phase-2 live run
#: compares one constructed URL against a served `webUrl` as evidence.
REPORT_WEB_URL_TEMPLATE = REPORT_WEB_BASE + "/groups/{groupId}/reports/{reportId}"

# --- enums and field sets we may emit --------------------------------------

#: PowerBIDataType — Microsoft's published closed enum for push dataset
#: columns (ref: pbi-datatype-enum). There is no documented `Decimal`
#: for push columns; see qe5_to_pbi_type for the numeric consequence.
PBI_DATA_TYPES = frozenset({"Int64", "Double", "Boolean", "DateTime", "String"})

#: DatasetMode values (ref: push-post-dataset-in-group). This leg emits
#: only "Push" — the plain push model with a backing database, the only
#: mode that supports report building.
DATASET_MODES = frozenset({"Push"})

#: DefaultRetentionPolicy values (ref: push-post-dataset-in-group).
#: This leg emits "None": rows live until we replace them (5M row cap)
#: — basicFIFO's 200k drop-oldest window is a streaming behavior, and a
#: model that silently drops rows is a changed fact.
RETENTION_POLICIES = frozenset({"None", "basicFIFO"})

#: CrossFilteringBehavior values (ref: push-post-dataset-in-group).
CROSS_FILTERING_BEHAVIORS = frozenset({"OneDirection", "BothDirections", "Automatic"})

#: Fields we may emit per request-body object (refs: the operation pages
#: above). Anything not listed here is refused before the wire — a field
#: Microsoft ignores today is drift waiting to be a 400 tomorrow.
EMITTABLE_FIELDS: dict[str, frozenset[str]] = {
    "create_dataset": frozenset({"name", "defaultMode", "tables", "relationships"}),
    "table": frozenset({"name", "columns", "measures"}),
    "column": frozenset({"name", "dataType", "formatString"}),
    "measure": frozenset({"name", "expression", "formatString"}),
    "relationship": frozenset(
        {"name", "fromTable", "fromColumn", "toTable", "toColumn", "crossFilteringBehavior"}
    ),
    "post_rows": frozenset({"rows"}),
    "fabric_create_report": frozenset({"displayName", "description", "definition"}),
    "fabric_update_definition": frozenset({"definition"}),
    "fabric_definition": frozenset({"format", "parts"}),
    "fabric_definition_part": frozenset({"path", "payload", "payloadType"}),
}

#: Fabric definition part payload types (refs: fabric-create-report).
FABRIC_PAYLOAD_TYPES = frozenset({"InlineBase64"})

#: Fabric report definition formats (ref: fabric-report-definition).
#: PBIR is the folder form we author; PBIR-Legacy is read-back-only for
#: us (a report we authored is always PBIR).
FABRIC_REPORT_FORMATS = frozenset({"PBIR", "PBIR-Legacy"})

#: PBIR part paths we author (ref: fabric-report-definition). Page and
#: visual names are lowercase hex identifiers in the documented layout.
PBIR_PART_PATHS = {
    "definition_pbir": "definition.pbir",
    "report": "definition/report.json",
    "version": "definition/version.json",
    "pages_index": "definition/pages/pages.json",
    "page": "definition/pages/{pageName}/page.json",
    "visual": "definition/pages/{pageName}/visuals/{visualName}/visual.json",
}

#: definition.pbir shape (ref: fabric-report-definition): version "4.0",
#: datasetReference.byConnection.connectionString of exactly this form
#: binds the report to a workspace semantic model by id — the rebind
#: seam RA-8 relies on.
PBIR_DEFINITION_VERSION = "4.0"
PBIR_BY_CONNECTION_TEMPLATE = "semanticmodelid={semanticModelId}"
PBIR_SCHEMA_URLS = {
    "definitionProperties": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
    "page": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json",
    "visualContainer": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.0.0/schema.json",
}

#: Fabric LRO contract (ref: fabric-lro): 202 + Location +
#: x-ms-operation-id + Retry-After; poll operation state until a
#: terminal status, then fetch the result endpoint where one exists.
FABRIC_LRO_TERMINAL_STATUSES = frozenset({"Succeeded", "Failed"})

#: Microsoft MCP tool schemas the skill relies on in v1: NONE, and that
#: is a ruling, not an omission. Modeling MCP is off (report-authoring
#: RA-A: measures are delivered from artifact metadata only) and remote
#: MCP verification reads are off by default (RA-B: the RA-7 read-back
#: suffices). The first tool added here must arrive with its schema
#: reference URL, retrieval date, and an AT-7 conformance case.
MCP_TOOLS_PINNED: dict[str, dict[str, str]] = {}

# --- documented limits (ref: push-limitations) ------------------------------

#: Push semantic model limits, enforced at OUR validation before any
#: call (report-authoring §5: exceeding one is an actionable capability
#: failure naming the limit and the RA-6 escalation, never a silent
#: truncation).
PUSH_LIMITS = {
    "max_tables": 75,
    "max_columns_per_table": 75,
    "max_relationships": 75,
    "max_rows_per_post": 10_000,
    "max_rows_per_hour": 1_000_000,
    "max_pending_post_requests": 5,
    "max_post_requests_per_minute": 120,
    "max_rows_per_table_none_retention": 5_000_000,
    "max_string_value_chars": 4_000,
}

#: The deprecation horizon for the whole push surface (ref:
#: realtime-retirement, page updated 2025-12-04): creation of new push
#: semantic models remains supported until 2027-10-31; EXISTING models
#: are unaffected after that date. The RA-6 Fabric/DirectLake
#: escalation therefore has a hard calendar trigger for new-model
#: creation, independent of estate size. Surfaced to the owner at the
#: CP-7 STOP-A report (2026-07-29).
PUSH_MODEL_DEPRECATION = {
    "new_model_creation_supported_until": "2027-10-31",
    "existing_models": "unaffected",
    "ref": "realtime-retirement",
}

#: Push datasets do not work with service principal *profiles* (the
#: Embedded multi-tenancy sub-identities; ref: push-limitations). Plain
#: service principals — what this deployment uses — are supported.
SP_PROFILES_UNSUPPORTED = True

# --- validation gates (AT-7: refuse before any Microsoft call) --------------

_PLACEHOLDER = re.compile(r"\{([a-zA-Z]+)\}")
#: Conservative safe set for path parameter values: everything Microsoft
#: ids use (uuids, alphanumerics) plus the table-name characters we mint
#: (result-set aliases are snake_case). Anything else — separators, '?',
#: '#', '%', whitespace — would change the URL's shape.
_SAFE_PARAM = frozenset(string.ascii_letters + string.digits + "-_.")


def endpoint_names() -> frozenset[str]:
    return frozenset(ENDPOINTS)


def pinned_endpoint(name: str, **params: str) -> tuple[str, str]:
    """Build (method, url) for a pinned endpoint, or refuse.

    Refuses an unknown endpoint name, a missing/extra parameter, or a
    parameter value that would alter the URL shape — each with the
    actionable message the D-89 pattern requires, before any HTTP.
    """
    entry = ENDPOINTS.get(name)
    if entry is None:
        known = ", ".join(sorted(ENDPOINTS))
        raise ConfigError(
            f"endpoint {name!r} is not in the pinned Microsoft surface (known: {known}). "
            "Pin it in connectors/powerbi/reference.py with its reference URL and "
            "retrieval date before emitting it (report-authoring spec §9)."
        )
    template = entry["template"]
    needed = set(_PLACEHOLDER.findall(template))
    given = set(params)
    if needed != given:
        missing = ", ".join(sorted(needed - given)) or "none"
        extra = ", ".join(sorted(given - needed)) or "none"
        raise ConfigError(
            f"endpoint {name!r} takes parameters [{', '.join(sorted(needed))}] — "
            f"missing: {missing}; unexpected: {extra}"
        )
    for key, value in params.items():
        if not value or not set(value) <= _SAFE_PARAM:
            raise ConfigError(
                f"endpoint {name!r} parameter {key}={value!r} contains characters "
                "outside the pinned id/name alphabet; refusing to build a URL whose "
                "shape the reference does not document"
            )
    url = template
    for key, value in params.items():
        url = url.replace("{" + key + "}", value)
    return entry["method"], url


def pinned_query_params(name: str, params: Mapping[str, str]) -> None:
    """Refuse query parameters the endpoint's reference does not list."""
    allowed = ENDPOINT_QUERY_PARAMS.get(name, frozenset())
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ConfigError(
            f"endpoint {name!r} documents query parameters {sorted(allowed)}; "
            f"{unknown} is outside the pinned set (report-authoring spec §9)"
        )


def pinned_request(method: str, url: str) -> str:
    """Assert an outgoing (method, url) matches a pinned endpoint; return
    its name. The HTTP layer calls this as the last gate before the wire,
    so no code path — including future ones — can emit an unpinned
    request without tripping ConfigError first (conformance AT-7)."""
    bare = url.split("?", 1)[0]
    for name, entry in ENDPOINTS.items():
        if entry["method"] != method:
            continue
        # Escape the template, then swap each placeholder for a
        # one-segment matcher in the safe id/name alphabet.
        pattern = re.escape(entry["template"])
        for placeholder in set(_PLACEHOLDER.findall(entry["template"])):
            pattern = pattern.replace(re.escape("{" + placeholder + "}"), r"[A-Za-z0-9\-_\.]+")
        if re.fullmatch(pattern, bare):
            return name
    raise ConfigError(
        f"{method} {bare} matches no pinned Microsoft endpoint "
        "(connectors/powerbi/reference.py). Refusing to emit a request the "
        "pinned reference set does not document (report-authoring spec §9 / D-89)."
    )


def assert_emitted_fields(kind: str, obj: Mapping[str, object]) -> None:
    """Refuse a request-body object carrying fields outside the pinned
    shape for its kind."""
    allowed = EMITTABLE_FIELDS.get(kind)
    if allowed is None:
        raise ConfigError(
            f"body kind {kind!r} has no pinned field set (known: "
            f"{', '.join(sorted(EMITTABLE_FIELDS))})"
        )
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise ConfigError(
            f"{kind} body carries fields outside the pinned {sorted(allowed)}: "
            f"{unknown}. Pin new fields with their reference before emitting them "
            "(report-authoring spec §9)."
        )


# --- QE-5 → Power BI type mapping (report-authoring §5) ---------------------

_INT_TYPES = frozenset({"int2", "int4", "int8", "smallint", "integer", "bigint"})
_FLOAT_TYPES = frozenset({"float4", "float8", "real", "double precision"})
_NUMERIC_TYPES = frozenset({"numeric", "decimal"})
_BOOL_TYPES = frozenset({"bool", "boolean"})
_TEMPORAL_TYPES = frozenset({"date", "timestamp", "timestamptz", "timestamp with time zone",
                             "timestamp without time zone", "datetime"})


def qe5_to_pbi_type(source_type: str) -> tuple[str, str | None]:
    """Map a QE-5 result column's source-native type to a pinned Power BI
    dataType. Returns (pbi_type, note) — `note` is the documented caveat
    that travels into the delivered schema (never a silent choice).

    The report-authoring spec §5 asks for "numeric-as-string → decimal
    with documented precision note"; the pinned Power BI enum
    (PBI_DATA_TYPES) has no Decimal, so the decimal-capable numeric it
    offers is Double, and the precision note documents exactly that
    boundary (IEEE-754 float64). GA4/GSC API types land here too via the
    QE-5 result's source-native names.
    """
    lowered = source_type.lower().strip()
    if lowered in _INT_TYPES:
        return "Int64", None
    if lowered in _FLOAT_TYPES:
        return "Double", None
    if lowered in _NUMERIC_TYPES:
        return (
            "Double",
            f"source {source_type} delivered as Double (the pinned Power BI type set "
            "has no Decimal); values beyond IEEE-754 float64 exact range lose "
            "precision — QE-5 kept the exact string, this model column does not",
        )
    if lowered in _BOOL_TYPES:
        return "Boolean", None
    if lowered in _TEMPORAL_TYPES:
        return "DateTime", None
    if lowered == "time" or lowered == "interval":
        return "String", None
    # The QE-5 catch-all instinct, applied to model typing: an unmapped
    # source type is delivered as its QE-5 text rendering, never dropped
    # and never guessed into a numeric.
    return "String", None
