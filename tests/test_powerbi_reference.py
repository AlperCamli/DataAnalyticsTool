"""AT-7 — the pinned Microsoft surface refuses unpinned emissions.

Report-authoring spec §9 (the D-89 pattern): any endpoint, field, or
tool shape outside the pinned set must die in OUR validation as
ConfigError before any Microsoft call. These tests exercise the gate
functions as pure functions (no network) and hold the pin table to the
discipline's structural rules — every pin carries a Microsoft-owned
reference URL and a real retrieval date, mirroring D-89.3's
"pinned-set-is-real" check: a surface added carelessly fails here, not
at Microsoft, minutes later, in a customer's session.
"""

import re
from datetime import date

import pytest

from connectors.powerbi import reference as ref
from connectors.sdk.errors import ConfigError

MICROSOFT_HOSTS = (
    "https://learn.microsoft.com/",
    "https://login.microsoftonline.com/",
)


# --- pin-table discipline ---------------------------------------------------


def test_every_reference_is_microsoft_owned_and_dated():
    assert ref.REFERENCES, "the pin table must not be empty"
    for name, pin in ref.REFERENCES.items():
        assert pin["url"].startswith(MICROSOFT_HOSTS), (
            f"reference {name!r} points at {pin['url']!r} — pins must cite the "
            "Microsoft-owned source of truth"
        )
        retrieved = date.fromisoformat(pin["retrieved"])  # raises if malformed
        assert retrieved >= date(2026, 7, 29), (
            f"reference {name!r} carries retrieval date {retrieved} — pins are "
            "verified forward, never backdated"
        )


def test_every_endpoint_cites_a_pinned_reference():
    for name, entry in ref.ENDPOINTS.items():
        assert entry["ref"] in ref.REFERENCES, (
            f"endpoint {name!r} cites unknown reference {entry['ref']!r}"
        )
        assert entry["method"] in {"GET", "POST", "PUT", "DELETE"}
        assert entry["template"].startswith(
            (ref.LOGIN_BASE, ref.PBI_API_BASE, ref.FABRIC_API_BASE)
        ), f"endpoint {name!r} template is outside the pinned hosts"


def test_query_param_sets_only_name_pinned_endpoints():
    for name in ref.ENDPOINT_QUERY_PARAMS:
        assert name in ref.ENDPOINTS


# --- the emission gates (AT-7 proper) ---------------------------------------


def test_unpinned_endpoint_name_is_refused_before_any_call():
    with pytest.raises(ConfigError, match="not in the pinned Microsoft surface"):
        ref.pinned_endpoint("push.execute_queries", groupId="g")


def test_missing_and_extra_parameters_are_refused():
    with pytest.raises(ConfigError, match="missing: datasetId"):
        ref.pinned_endpoint("push.post_rows", groupId="g", tableName="t")
    with pytest.raises(ConfigError, match="unexpected: profileId"):
        ref.pinned_endpoint("groups.list", profileId="p")


def test_url_shape_altering_parameter_is_refused():
    for bad in ("a/b", "a?x=1", "a#f", "a b", ""):
        with pytest.raises(ConfigError, match="outside the pinned id/name alphabet"):
            ref.pinned_endpoint(
                "push.put_table",
                groupId="f089354e-8366-4e18-aea3-4cb4a3a50b48",
                datasetId="cfafbeb1-8037-4d0c-896e-a46fb27ff229",
                tableName=bad,
            )


def test_every_pinned_endpoint_builds_and_round_trips_pinned_request():
    sample = {
        "tenantId": "aaaabbbb-0000-cccc-1111-dddd2222eeee",
        "groupId": "f089354e-8366-4e18-aea3-4cb4a3a50b48",
        "datasetId": "cfafbeb1-8037-4d0c-896e-a46fb27ff229",
        "tableName": "weekly_signups",
        "reportId": "5b218778-e7a5-4d73-8187-f10824047715",
        "workspaceId": "cfafbeb1-8037-4d0c-896e-a46fb27ff229",
        "operationId": "0acd697c-1550-43cd-b998-91bfbfbd47c6",
    }
    for name, entry in ref.ENDPOINTS.items():
        needed = set(re.findall(r"\{([a-zA-Z]+)\}", entry["template"]))
        params = {key: sample[key] for key in needed}
        method, url = ref.pinned_endpoint(name, **params)
        assert method == entry["method"]
        # The last-line gate recognizes exactly what pinned_endpoint built.
        assert ref.pinned_request(method, url) == name


def test_unpinned_request_is_refused_at_the_last_line_gate():
    gid = "f089354e-8366-4e18-aea3-4cb4a3a50b48"
    did = "cfafbeb1-8037-4d0c-896e-a46fb27ff229"
    refusals = [
        # A real Microsoft endpoint we have NOT pinned (executeQueries):
        ("POST", f"{ref.PBI_API_BASE}/groups/{gid}/datasets/{did}/executeQueries"),
        # Right path, wrong method:
        ("PUT", f"{ref.PBI_API_BASE}/groups/{gid}/datasets"),
        # Right shape, wrong host:
        ("GET", f"https://api.powerbi.example.com/v1.0/myorg/groups"),
        # Admin surface:
        ("GET", f"{ref.PBI_API_BASE}/admin/groups"),
    ]
    for method, url in refusals:
        with pytest.raises(ConfigError, match="matches no pinned Microsoft endpoint"):
            ref.pinned_request(method, url)


def test_unpinned_query_parameter_is_refused():
    ref.pinned_query_params("push.create_dataset", {"defaultRetentionPolicy": "None"})
    with pytest.raises(ConfigError, match="outside the pinned set"):
        ref.pinned_query_params("push.create_dataset", {"datasourceType": "sql"})
    with pytest.raises(ConfigError, match="outside the pinned set"):
        ref.pinned_query_params("push.post_rows", {"sequenceNumber": "1"})


def test_unpinned_body_field_is_refused():
    ref.assert_emitted_fields(
        "column", {"name": "net_total", "dataType": "Double", "formatString": "0.00"}
    )
    with pytest.raises(ConfigError, match="outside the pinned"):
        ref.assert_emitted_fields(
            "column", {"name": "net_total", "dataType": "Double", "summarizeBy": "sum"}
        )
    with pytest.raises(ConfigError, match="outside the pinned"):
        ref.assert_emitted_fields("create_dataset", {"name": "x", "tables": [], "datasources": []})
    with pytest.raises(ConfigError, match="no pinned field set"):
        ref.assert_emitted_fields("streaming_dataset", {"name": "x"})


# --- pinned enums and the QE-5 mapping --------------------------------------


def test_data_type_enum_is_exactly_the_documented_five():
    assert ref.PBI_DATA_TYPES == {"Int64", "Double", "Boolean", "DateTime", "String"}


def test_qe5_mapping_lands_only_on_pinned_types():
    cases = {
        "int2": "Int64", "int4": "Int64", "int8": "Int64", "bigint": "Int64",
        "float4": "Double", "float8": "Double",
        "numeric": "Double", "decimal": "Double",
        "bool": "Boolean", "boolean": "Boolean",
        "date": "DateTime", "timestamp": "DateTime", "timestamptz": "DateTime",
        "time": "String", "interval": "String",
        "uuid": "String", "text": "String", "jsonb": "String", "bytea": "String",
        "some_exotic_type": "String",
    }
    for source, expected in cases.items():
        pbi_type, note = ref.qe5_to_pbi_type(source)
        assert pbi_type == expected, f"{source} → {pbi_type}, expected {expected}"
        assert pbi_type in ref.PBI_DATA_TYPES
        if source in ("numeric", "decimal"):
            assert note and "precision" in note, (
                "numeric delivery must carry the documented precision note "
                "(report-authoring §5) — a silent Double is a changed fact"
            )


def test_mcp_tool_pin_set_is_empty_in_v1():
    # RA-A (Modeling MCP off) + RA-B (remote reads off by default): the
    # skill relies on zero Microsoft MCP tools, so the pinned set is
    # empty BY RULING. The first entry added here must bring a schema
    # reference URL + retrieval date and its own AT-7 case.
    assert ref.MCP_TOOLS_PINNED == {}


def test_push_limits_match_the_limitations_page():
    assert ref.PUSH_LIMITS["max_tables"] == 75
    assert ref.PUSH_LIMITS["max_columns_per_table"] == 75
    assert ref.PUSH_LIMITS["max_relationships"] == 75
    assert ref.PUSH_LIMITS["max_rows_per_post"] == 10_000
    assert ref.PUSH_LIMITS["max_rows_per_table_none_retention"] == 5_000_000
    assert ref.PUSH_LIMITS["max_string_value_chars"] == 4_000


def test_deprecation_horizon_is_pinned_with_its_reference():
    dep = ref.PUSH_MODEL_DEPRECATION
    assert dep["new_model_creation_supported_until"] == "2027-10-31"
    assert dep["ref"] in ref.REFERENCES


def test_report_web_url_matches_the_documented_weburl_form():
    url = ref.REPORT_WEB_URL_TEMPLATE.format(
        groupId="f089354e-8366-4e18-aea3-4cb4a3a50b48",
        reportId="5b218778-e7a5-4d73-8187-f10824047715",
    )
    # Exactly the webUrl the Reports API example serves (ref:
    # reports-get-in-group).
    assert url == (
        "https://app.powerbi.com/groups/f089354e-8366-4e18-aea3-4cb4a3a50b48"
        "/reports/5b218778-e7a5-4d73-8187-f10824047715"
    )
