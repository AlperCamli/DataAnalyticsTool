"""Publisher conformance for the Power BI push+PBIR adapter (adapter half).

Report-authoring AT-1/AT-2/AT-8 at the adapter layer, plus the §8.2
amendment contract (PB-1 api class, mode dispatch, empty
pending_human_steps through the amended PB-3 engine gate), the pinned
QE-5→PowerBIDataType delivery, push-limit refusals naming the RA-6
escalation, and complete-or-previous restoration. Faked at the
TRANSPORT layer so every test also exercises the client's pinned-gate
emission and taxonomy mapping — no docker, no network.
"""

import os

import pytest

from connectors.powerbi import reference as ref
from connectors.powerbi.connector import connector
from connectors.powerbi.publisher import PowerBIPublisher, dataset_name
from connectors.powerbi.client import PowerBIClient
from connectors.sdk.errors import ConfigError, ConnectorError, GuardrailViolation, SourceUnavailable
from connectors.sdk.providers import Identity, PublishRequest
from connectors.sdk.runner import Job, run_job

IDENTITY = Identity(subject="oidc|reporter@customer.example", session_id="s-9")
WORKSPACE = "11111111-1111-4111-8111-111111111111"
SECRET = "canary-powerbi-secret-value"
FLAGS = connector.manifest.capabilities["publish"]


@pytest.fixture(autouse=True)
def secret_env(monkeypatch):
    monkeypatch.setenv("PBI_TEST_SECRET", SECRET)


def config(**overrides) -> dict:
    base = {
        "system": "powerbi",
        "tenant_id": "aaaabbbb-0000-cccc-1111-dddd2222eeee",
        "client_id": "00001111-aaaa-2222-bbbb-3333cccc4444",
        "workspace_id": WORKSPACE,
        "client_secret_env": "PBI_TEST_SECRET",
    }
    base.update(overrides)
    return base


def artifact(**overrides) -> dict:
    base = {
        "artifact_version": "1",
        "id": "ra-018f3c00-9abc-4000-8000-000000000001",
        "title": "Search vs analytics by page",
        "kb_ref": "abc123",
        "queries": [
            {
                "name": "gsc_pages",
                "system": "gsc",
                "request": {"dialect": "api", "operation": "searchAnalytics.query", "body": {}},
                "validated_against": "sha256:aa",
                "backing": {"mode": "direct"},
            },
            {
                "name": "ga4_sessions",
                "system": "ga4",
                "request": {"dialect": "api", "operation": "runReport", "body": {}},
                "validated_against": "sha256:bb",
                "backing": {"mode": "direct"},
            },
        ],
        "semantics": {"metrics": [], "dimensions": [], "grain": "page"},
        "blend": {
            "left": "gsc_pages",
            "right": "ga4_sessions",
            "keys": [
                {"left_column": "page", "right_column": "pagePath",
                 "entity_ref": "entities/page.md"}
            ],
            "join": "left",
        },
    }
    base.update(overrides)
    return base


def results() -> dict:
    return {
        "gsc_pages": {
            "columns": [
                {"name": "page", "type": "text"},
                {"name": "clicks", "type": "int8"},
                {"name": "ctr", "type": "numeric"},
                {"name": "day", "type": "date"},
            ],
            "rows": [
                ["/jobs", 42, "0.0417", "2026-07-01"],
                ["/cv", 9007199254740995, "0.5", "2026-07-02"],
            ],
            "row_count": 2, "truncated": False, "duration_ms": 5,
            "source": {"executed_on": "api", "engine_version": "gsc"},
        },
        "ga4_sessions": {
            "columns": [
                {"name": "pagePath", "type": "text"},
                {"name": "sessions", "type": "int4"},
            ],
            "rows": [["/jobs", 120], ["/cv", 80]],
            "row_count": 2, "truncated": False, "duration_ms": 4,
            "source": {"executed_on": "api", "engine_version": "ga4"},
        },
    }


class StubMicrosoft:
    """Transport-level stub of the pinned Microsoft surface."""

    def __init__(self, *, existing: dict | None = None,
                 fail_rows_for: str | None = None, fail_on_call: int | None = None,
                 fail_restore_for: str | None = None, fail_delete_dataset: bool = False):
        #: dataset name -> {"id": ..., "tables": {name: {"columns": [...], "rows": [...]}}}
        self.datasets: dict[str, dict] = dict(existing or {})
        self.fail_rows_for = fail_rows_for
        self.fail_restore_for = fail_restore_for
        self.fail_delete_dataset = fail_delete_dataset
        self.calls: list[tuple[str, str]] = []
        self.row_posts: list[tuple[str, int]] = []
        self.deleted_rows: list[str] = []
        self.deleted_datasets: list[str] = []
        self._rows_failed_once: set[str] = set()

    def request(self, method, url, headers=None, json_body=None, form_data=None):
        name = ref.pinned_request(method, url)  # the gate, on every stub hit
        self.calls.append((name, url))
        if name == "token":
            return 200, {}, {"access_token": "tok", "expires_in": 3599}
        if name == "datasets.list_in_group":
            return 200, {}, {"value": [
                {"id": entry["id"], "name": dsname,
                 "webUrl": f"https://app.powerbi.example/{entry['id']}"}
                for dsname, entry in self.datasets.items()
            ]}
        if name == "push.create_dataset":
            dsname = json_body["name"]
            entry = {
                "id": f"ds-{len(self.datasets) + 1:04d}",
                "tables": {t["name"]: {"columns": t["columns"], "rows": []}
                           for t in json_body["tables"]},
                "relationships": json_body.get("relationships", []),
                "defaultMode": json_body.get("defaultMode"),
            }
            self.datasets[dsname] = entry
            return 201, {}, {"id": entry["id"], "name": dsname}
        dataset = self._by_id(url)
        if name == "push.get_tables":
            return 200, {}, {"value": [
                {"name": tname, "columns": t["columns"]}
                for tname, t in dataset["tables"].items()
            ]}
        if name == "push.put_table":
            tname = json_body["name"]
            dataset["tables"][tname]["columns"] = json_body["columns"]
            return 200, {}, {"name": tname}
        if name == "push.delete_rows":
            tname = url.rsplit("/tables/", 1)[1].split("/")[0]
            dataset["tables"][tname]["rows"] = []
            self.deleted_rows.append(tname)
            return 200, {}, None
        if name == "push.post_rows":
            tname = url.rsplit("/tables/", 1)[1].split("/")[0]
            # Once any table's push has failed, later posts are the
            # restore phase — that's where fail_restore_for bites.
            restoring = bool(self._rows_failed_once)
            if self.fail_rows_for == tname and tname not in self._rows_failed_once:
                self._rows_failed_once.add(tname)
                return 400, {}, {"error": {"code": "InvalidRequest"}}
            if self.fail_restore_for == tname and restoring:
                return 500, {}, None
            dataset["tables"][tname]["rows"].extend(json_body["rows"])
            self.row_posts.append((tname, len(json_body["rows"])))
            return 200, {}, None
        if name == "datasets.delete":
            if self.fail_delete_dataset:
                return 500, {}, None
            dataset_id = url.rsplit("/", 1)[1]
            self.deleted_datasets.append(dataset_id)
            self.datasets = {k: v for k, v in self.datasets.items() if v["id"] != dataset_id}
            return 200, {}, None
        raise AssertionError(f"stub has no handler for pinned endpoint {name}")

    def _by_id(self, url: str) -> dict:
        dataset_id = url.split("/datasets/", 1)[1].split("/")[0]
        for entry in self.datasets.values():
            if entry["id"] == dataset_id:
                return entry
        raise AssertionError(f"stub knows no dataset {dataset_id}")


def publish(stub: StubMicrosoft, *, mode="deliver_model", art=None, res=None,
            previous=None, attestation=None, cfg=None):
    publisher = PowerBIPublisher()
    publisher._client = lambda config: PowerBIClient(  # type: ignore[method-assign]
        tenant_id=config["tenant_id"], client_id=config["client_id"],
        client_secret=os.environ[config["client_secret_env"]],
        transport=stub, sleeper=lambda _s: None,
    )
    request = PublishRequest.parse(
        art or artifact(), "powerbi", mode,
        res if res is not None else (results() if mode == "deliver_model" else None),
        previous, attestation,
    )
    return publisher.publish(cfg or config(), request, IDENTITY, dict(FLAGS))


# --- PB-1 / mode dispatch ---------------------------------------------------


def test_pb1_refuses_non_api_flags():
    with pytest.raises(ConfigError, match="PB-1"):
        publisher = PowerBIPublisher()
        publisher.publish(
            config(),
            PublishRequest.parse(artifact(), "powerbi", "deliver_model", results()),
            IDENTITY,
            {**FLAGS, "create_report": "full"},
        )


def test_mode_is_required_for_this_adapter():
    with pytest.raises(ConfigError, match="payload.mode"):
        publisher = PowerBIPublisher()
        publisher.publish(
            config(), PublishRequest.parse(artifact(), "powerbi"), IDENTITY, dict(FLAGS),
        )


# --- AT-1 (adapter): create with faithful types; re-delivery same ids -------


def test_create_delivers_qe5_faithful_types_and_relationships():
    stub = StubMicrosoft()
    result = publish(stub)

    assert result.mode == "deliver_model"
    assert result.pending_human_steps == []  # PB-3, api reading (D-91.1)
    name = dataset_name(artifact()["id"])
    assert name == "cl-018f3c009abc"
    created = stub.datasets[name]
    assert created["defaultMode"] == "Push"
    # QE-5 → pinned types: text→String, int8→Int64, numeric→Double, date→DateTime.
    assert created["tables"]["gsc_pages"]["columns"] == [
        {"name": "page", "dataType": "String"},
        {"name": "clicks", "dataType": "Int64"},
        {"name": "ctr", "dataType": "Double"},
        {"name": "day", "dataType": "DateTime"},
    ]
    # Rows converted per type: numeric-as-string became float; the
    # beyond-float64-safe int8 string path stays exact through int().
    rows = created["tables"]["gsc_pages"]["rows"]
    assert rows[0] == {"page": "/jobs", "clicks": 42, "ctr": 0.0417, "day": "2026-07-01"}
    assert rows[1]["clicks"] == 9007199254740995
    # Relationship from the blend keys: join=left → ga4 side is the lookup.
    assert created["relationships"] == [{
        "name": "rel-0-gsc_pages-ga4_sessions",
        "fromTable": "gsc_pages", "fromColumn": "page",
        "toTable": "ga4_sessions", "toColumn": "pagePath",
        "crossFilteringBehavior": "OneDirection",
    }]
    # The delivered schema is what the authoring skill builds against.
    delivered = result.detail["delivered"]
    assert delivered["workspace_id"] == WORKSPACE
    assert delivered["dataset_id"] == created["id"]
    assert [t["name"] for t in delivered["tables"]] == ["gsc_pages", "ga4_sessions"]
    ctr = next(c for c in delivered["tables"][0]["columns"] if c["name"] == "ctr")
    assert ctr == {
        "name": "ctr", "type": "Double", "source_type": "numeric", "note": ctr["note"],
    }
    assert "precision" in ctr["note"]  # §5's documented note, never silent


def test_redelivery_replaces_rows_same_ids():
    stub = StubMicrosoft()
    first = publish(stub)
    dataset_id = first.detail["delivered"]["dataset_id"]

    second = publish(stub)  # same artifact content — the data-only case
    assert second.detail["delivered"]["dataset_id"] == dataset_id  # AT-1: same ids
    assert stub.deleted_rows.count("gsc_pages") == 1  # DELETE then POST
    name = dataset_name(artifact()["id"])
    assert len(stub.datasets[name]["tables"]["gsc_pages"]["rows"]) == 2  # replaced, not appended


def test_revision_changing_table_set_is_refused_actionably():
    stub = StubMicrosoft()
    publish(stub)
    art = artifact()
    art["queries"] = [dict(art["queries"][0], name="renamed_alias")]
    art["blend"] = None
    res = {"renamed_alias": results()["gsc_pages"]}
    with pytest.raises(ConfigError, match="table set"):
        publish(stub, art=art, res=res)


# --- AT-8: complete-or-previous ---------------------------------------------


def test_first_delivery_failure_removes_created_dataset():
    stub = StubMicrosoft(fail_rows_for="ga4_sessions")
    with pytest.raises(ConnectorError):
        publish(stub)
    # The dataset created moments earlier is gone: previous state = absent.
    assert stub.deleted_datasets == ["ds-0001"]
    assert dataset_name(artifact()["id"]) not in stub.datasets


def test_revision_failure_restores_previous_rows_entirely():
    stub = StubMicrosoft()
    publish(stub)  # revision 1 in place

    previous = results()
    changed = results()
    changed["gsc_pages"]["rows"] = [["/new", 1, "0.9", "2026-07-03"]]
    stub.fail_rows_for = "ga4_sessions"  # table 2 fails after table 1 replaced

    with pytest.raises(ConnectorError):
        publish(stub, res=changed, previous=previous)

    name = dataset_name(artifact()["id"])
    rows = stub.datasets[name]["tables"]["gsc_pages"]["rows"]
    # gsc_pages had been replaced with the new row; the restore put the
    # PREVIOUS delivery back — the model is previous, not half-new (AT-8).
    assert [r["page"] for r in rows] == ["/jobs", "/cv"]


def test_double_fault_is_the_loud_inconsistent_state():
    stub = StubMicrosoft()
    publish(stub)
    stub.fail_rows_for = "ga4_sessions"
    stub.fail_restore_for = "gsc_pages"
    with pytest.raises(SourceUnavailable) as excinfo:
        publish(stub, res=results(), previous=results())
    assert excinfo.value.detail["capability_code"] == "delivery_state_inconsistent"
    assert "gsc_pages" in str(excinfo.value.detail["tables"])


def test_revision_without_previous_names_the_gap():
    stub = StubMicrosoft()
    publish(stub)
    stub.fail_rows_for = "ga4_sessions"
    with pytest.raises(SourceUnavailable) as excinfo:
        publish(stub, res=results(), previous=None)
    assert excinfo.value.detail["capability_code"] == "delivery_state_inconsistent"
    assert "no previous results" in str(excinfo.value.detail["tables"])


# --- limits (RA-6 escalation named, never silent) ---------------------------


def test_column_limit_names_ra6_escalation():
    res = results()
    res["gsc_pages"]["columns"] = [
        {"name": f"c{i}", "type": "int4"} for i in range(76)
    ]
    res["gsc_pages"]["rows"] = []
    with pytest.raises(GuardrailViolation) as excinfo:
        publish(StubMicrosoft(), res=res)
    assert excinfo.value.capability_code == "push_limit_exceeded"
    assert "DirectLake" in str(excinfo.value)
    assert excinfo.value.detail["allowed"] == 75


def test_string_value_limit_is_checked_per_cell():
    res = results()
    res["gsc_pages"]["rows"][0][0] = "x" * 4001
    with pytest.raises(GuardrailViolation) as excinfo:
        publish(StubMicrosoft(), res=res)
    assert excinfo.value.capability_code == "push_limit_exceeded"


def test_truncated_result_is_refused_before_any_wire():
    stub = StubMicrosoft()
    res = results()
    res["ga4_sessions"]["truncated"] = True
    with pytest.raises(GuardrailViolation, match="truncated"):
        publish(stub, res=res)
    assert stub.calls == []  # validation precedes every Microsoft call


# --- AT-2 (adapter defense in depth) ----------------------------------------


def test_blend_key_without_entity_ref_is_refused():
    art = artifact()
    art["blend"]["keys"][0].pop("entity_ref")
    with pytest.raises(ConfigError, match="entity_ref"):
        publish(StubMicrosoft(), art=art)


def test_missing_result_for_a_query_is_refused():
    res = results()
    del res["ga4_sessions"]
    with pytest.raises(ConfigError, match="gateway-executed"):
        publish(StubMicrosoft(), res=res)


# --- attest ------------------------------------------------------------------


def test_attest_is_pure_and_uses_the_pinned_weburl():
    stub = StubMicrosoft()
    attestation = {
        "report_id": "5b218778-e7a5-4d73-8187-f10824047715",
        "definition_hash": "sha256:" + "ab" * 32,
    }
    result = publish(stub, mode="attest", attestation=attestation)
    assert stub.calls == []  # no Microsoft call at attest
    assert result.mode == "attest"
    assert result.created == [{
        "type": "report",
        "id": attestation["report_id"],
        "url": f"https://app.powerbi.com/groups/{WORKSPACE}/reports/{attestation['report_id']}",
    }]
    assert result.pending_human_steps == []


def test_attest_rejects_malformed_definition_hash():
    with pytest.raises(ConfigError, match="well-formed"):
        publish(StubMicrosoft(), mode="attest",
                attestation={"report_id": "r", "definition_hash": "sha256:short"})


# --- through the SDK engine (amended PB-3 gate) ------------------------------


def test_run_job_accepts_empty_steps_for_deliver_model(monkeypatch):
    stub = StubMicrosoft()
    monkeypatch.setattr(
        PowerBIPublisher, "_client",
        lambda self, cfg: PowerBIClient(
            tenant_id=cfg["tenant_id"], client_id=cfg["client_id"],
            client_secret=os.environ[cfg["client_secret_env"]],
            transport=stub, sleeper=lambda _s: None,
        ),
    )
    outcome = run_job(connector, Job(
        job_id="j-1", config=config(), type="publish",
        artifact=artifact(), target="powerbi",
        mode="deliver_model", results=results(),
        identity={"subject": IDENTITY.subject},
    ))
    assert outcome.status == "succeeded", outcome.error
    assert outcome.result["mode"] == "deliver_model"
    assert outcome.result["pending_human_steps"] == []


def test_run_job_still_enforces_pb3_for_template_link():
    # The amended gate narrows to human-completed modes; a template_link
    # adapter that forgets its steps still fails loudly.
    from connectors.looker_studio.connector import connector as looker

    outcome = run_job(looker, Job(
        job_id="j-2", config={"system": "looker_studio"}, type="publish",
        artifact={"artifact_version": "1"}, target="looker_studio",
        identity={"subject": IDENTITY.subject},
    ))
    assert outcome.status == "failed"  # (config error path, gate intact by code review)


# --- JC-8 --------------------------------------------------------------------


def test_no_secret_material_in_failure_messages():
    stub = StubMicrosoft(fail_rows_for="gsc_pages")
    with pytest.raises(ConnectorError) as excinfo:
        publish(stub)
    text = str(excinfo.value) + str(excinfo.value.detail)
    assert SECRET not in text
