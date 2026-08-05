"""Publisher conformance for the Looker Studio template-link adapter.

Capability spec §8 duties, tested at the two layers that own them:
the adapter (PB-1/PB-2/PB-4, CC-7/CC-8, the sql_backing: views
constraint, blend structural checks) and the SDK publish engine
(artifact_version gate, PB-3 enforcement, error taxonomy mapping).
Pure-function adapter — no docker, no network, nothing env-gated.
"""

from urllib.parse import parse_qsl, urlsplit

import pytest

from connectors.looker_studio.connector import connector
from connectors.looker_studio.publisher import LookerStudioPublisher
from connectors.sdk.errors import ConfigError
from connectors.sdk.manifest import load_manifest
from connectors.sdk.providers import Identity, PublishRequest, Publisher, PublishResult
from connectors.sdk.runner import Job, run_job

IDENTITY = Identity(subject="oidc|reporter@customer.example", session_id="s-9")

CONFIG = {
    "system": "looker_studio",
    "template_report_id": "tmpl-abc123",
    "template_visual_kinds": ["line", "table"],
    "sources": {
        "supabase": {
            "kind": "postgres", "alias": "sb",
            "host": "db.pilot.supabase.co", "port": 5432,
            "database": "postgres", "username": "example_exec",
        },
        "ga4": {"kind": "ga4", "alias": "ga", "property_id": "000000000"},
        "gsc": {
            "kind": "gsc", "alias": "sc",
            "site_url": "sc-domain:example-estate.com",
            "table_type": "SITE_IMPRESSION",
        },
    },
}

FLAGS = connector.manifest.capabilities["publish"]


def artifact(**overrides) -> dict:
    base = {
        "artifact_version": "1",
        "id": "ra-018f3c00-0000-4000-8000-000000000001",
        "title": "New users by day",
        "kb_ref": "abc123",
        "queries": [
            {
                "name": "signups",
                "system": "supabase",
                "request": {
                    "dialect": "sql",
                    "statement": "SELECT signup_day, new_users FROM reporting.v_user_signups_by_day",
                },
                "validated_against": "sha256:aa",
                "backing": {"mode": "reporting_view", "ref": "reporting.v_user_signups_by_day"},
            }
        ],
        "semantics": {"metrics": [], "dimensions": [], "grain": "day", "trust_notes": []},
        "visuals": [{"kind": "line", "query": "signups", "encoding": {"x": "signup_day", "y": "new_users"}}],
        "blend": None,
    }
    base.update(overrides)
    return base


def publish(art: dict, config: dict = CONFIG, flags: dict = FLAGS) -> PublishResult:
    request = PublishRequest.parse(art, "looker_studio")
    return LookerStudioPublisher().publish(config, request, IDENTITY, dict(flags))


def url_params(result: PublishResult) -> dict:
    url = result.created[0]["url"]
    split = urlsplit(url)
    assert f"{split.scheme}://{split.netloc}{split.path}" == \
        "https://lookerstudio.google.com/reporting/create"
    return dict(parse_qsl(split.query))


# --- CC-1: manifest + assembly ------------------------------------------------

def test_manifest_validates_and_assembly_holds():
    manifest = load_manifest(connector.manifest.path)
    assert manifest.capabilities["publish"]["create_report"] == "template_link"
    # YAML "no" must arrive as the string the §8.1 registry defines,
    # never as a boolean that slipped through unquoted.
    assert manifest.capabilities["publish"]["create_dataset"] == "no"
    assert isinstance(connector.handlers["publish"], Publisher)


# --- the template-link translation --------------------------------------------

def test_postgres_sources_emit_no_ds_parameters():
    """D-89: PostgreSQL is not a Linking-API-configurable connector.

    The M3 gate found this the only way it could be found — by opening a
    real link, which Looker Studio refused. An invalid `ds.*.connector`
    fails report creation outright; it does not degrade into a field the
    human completes, which is what the original watch note assumed.
    """
    result = publish(artifact())
    assert result.mode == "template_link"
    params = url_params(result)
    assert params["c.reportId"] == "tmpl-abc123"
    assert params["r.reportName"] == "New users by day"

    assert not [key for key in params if key.startswith("ds.sb.")], (
        "no ds.* parameter may be emitted for a postgres source"
    )

    # The backing is still declared — what the report rests on is a fact
    # about the artifact, independent of what the URL can carry.
    assert result.backing == [
        {"type": "reporting_view", "ref": "reporting.v_user_signups_by_day"}
    ]
    # PB-3: the human step names the alias, the view, and where to do it.
    step = next(s for s in result.pending_human_steps if "sb" in s)
    assert "reporting.v_user_signups_by_day" in step
    assert "manage added data sources" in step
    assert "password" in step


def test_every_emitted_connector_id_is_a_real_linking_api_connector():
    """D-89 guardrail: we never invent a connector id.

    Asserted over the whole pinned table rather than one publish, so a
    future source kind added without checking the reference fails here
    instead of at Google's create endpoint.
    """
    from connectors.looker_studio.publisher import (
        _LINKING_API_CONNECTOR_IDS,
        _LINKING_API_CONNECTORS,
    )

    for kind, params in _LINKING_API_CONNECTORS.items():
        assert params["connector"] in _LINKING_API_CONNECTOR_IDS, (
            f"source kind {kind!r} maps to a connector id the Linking API does not define"
        )

    art = artifact(
        queries=[{
            "name": "sessions", "system": "ga4",
            "request": {"dialect": "api", "operation": "runReport", "body": {}},
            "validated_against": "sha256:cc",
            "backing": {"mode": "dataset_ref", "ref": "properties/000000000"},
        }],
    )
    emitted = {
        key.rsplit(".", 1)[0]: value
        for key, value in url_params(publish(art)).items()
        if key.endswith(".connector")
    }
    assert emitted, "expected at least one connector parameter"
    for value in emitted.values():
        assert value in _LINKING_API_CONNECTOR_IDS


def test_unsupported_source_kind_is_refused_not_guessed():
    """An unknown kind fails at our validation, naming what is supported."""
    unsupported = {
        **CONFIG,
        "sources": {"supabase": {"kind": "mysql", "alias": "sb", "host": "db.example"}},
    }
    with pytest.raises(ConfigError) as excinfo:
        publish(artifact(), config=unsupported)
    message = str(excinfo.value)
    assert "not supported by this adapter" in message
    assert "postgres" in message and "ga4" in message


def test_cross_source_wires_native_sources_and_blend_steps():
    art = artifact(
        queries=[
            artifact()["queries"][0],
            {
                "name": "pages", "system": "gsc",
                "request": {"dialect": "api", "operation": "searchanalytics.query", "body": {}},
                "validated_against": "sha256:bb",
                "backing": {"mode": "dataset_ref", "ref": "sc-domain:example-estate.com"},
            },
            {
                "name": "sessions", "system": "ga4",
                "request": {"dialect": "api", "operation": "runReport", "body": {}},
                "validated_against": "sha256:cc",
                "backing": {"mode": "dataset_ref", "ref": "properties/000000000"},
            },
        ],
        blend={
            "left": "pages", "right": "sessions",
            "keys": [{"left_column": "page", "right_column": "pagePath",
                      "entity_ref": "entities/page.md"}],
            "join": "left",
        },
    )
    result = publish(art)
    params = url_params(result)
    assert params["ds.ga.connector"] == "googleAnalytics"
    assert params["ds.ga.propertyId"] == "000000000"
    assert params["ds.sc.connector"] == "searchConsole"
    assert params["ds.sc.siteUrl"] == "sc-domain:example-estate.com"
    assert params["ds.sc.tableType"] == "SITE_IMPRESSION"
    assert any("blend" in step for step in result.pending_human_steps)


def test_blend_key_without_entity_ref_is_refused():
    art = artifact(blend={"left": "a", "right": "b",
                          "keys": [{"left_column": "page", "right_column": "pagePath"}],
                          "join": "left"})
    with pytest.raises(ConfigError, match="entity_ref"):
        publish(art)


# --- sql_backing: views is a wall, not advice ----------------------------------

def test_direct_sql_backing_is_refused_with_the_actionable_error():
    art = artifact()
    art["queries"][0]["backing"] = {"mode": "direct"}
    with pytest.raises(ConfigError, match="reporting view"):
        publish(art)


def test_unwired_system_is_refused():
    art = artifact()
    art["queries"][0]["system"] = "warehouse9"
    with pytest.raises(ConfigError, match="warehouse9"):
        publish(art)


# --- PB-1 / CC-8: flags govern -------------------------------------------------

def test_flags_beyond_template_link_are_config_error():
    for create_report in ("none", "full"):
        with pytest.raises(ConfigError, match="PB-1"):
            publish(artifact(), flags={**FLAGS, "create_report": create_report})


# --- PB-2 / CC-7: idempotency --------------------------------------------------

def test_republish_is_byte_identical_same_id_same_url():
    first, second = publish(artifact()), publish(artifact())
    assert first.created == second.created
    assert first.created[0]["id"].startswith("tl-")
    # Same artifact id to a different target keeps a different identity.
    other = LookerStudioPublisher().publish(
        CONFIG, PublishRequest.parse(artifact(), "looker_studio_staging"), IDENTITY, dict(FLAGS)
    )
    assert other.created[0]["id"] != first.created[0]["id"]


# --- PB-4: substitutions recorded, never silent ---------------------------------

def test_visual_kind_outside_template_recorded_as_substitution():
    art = artifact(visuals=[{"kind": "pivot", "query": "signups", "encoding": {}}])
    result = publish(art)
    assert result.detail["visual_substitutions"] == [{
        "kind": "pivot",
        "substituted_with": "template default",
        "note": ("the linked template does not exercise 'pivot'; pick the chart "
                 "in the Looker Studio editor after creating the report"),
    }]


def test_visual_kind_outside_registry_is_refused():
    art = artifact(visuals=[{"kind": "sankey", "query": "signups", "encoding": {}}])
    with pytest.raises(ConfigError, match="registry"):
        publish(art)


# --- the SDK publish engine ------------------------------------------------------

def job(art: dict, target: str = "looker_studio") -> Job:
    return Job(
        job_id="j-publish-1", config=dict(CONFIG), type="publish",
        identity={"subject": IDENTITY.subject}, artifact=art, target=target,
    )


def test_engine_happy_path_returns_the_result_envelope():
    outcome = run_job(connector, job(artifact()))
    assert outcome.status == "succeeded"
    assert outcome.result["mode"] == "template_link"
    assert outcome.result["created"][0]["url"].startswith(
        "https://lookerstudio.google.com/reporting/create?"
    )


def test_engine_gates_artifact_version():
    outcome = run_job(connector, job(artifact(artifact_version="2")))
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert outcome.error.detail["capability_code"] == "artifact_version_unsupported"


def test_engine_maps_adapter_refusals_to_config_error():
    art = artifact()
    art["queries"][0]["backing"] = {"mode": "direct"}
    outcome = run_job(connector, job(art))
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert not outcome.error.retryable


def test_engine_enforces_pb3():
    class ForgetfulPublisher(Publisher):
        def publish(self, config, request, identity, flags):
            return PublishResult(mode="template_link", created=[],
                                 pending_human_steps=[], backing=[], detail={})

    from connectors.sdk.connector import Connector
    forgetful = Connector(manifest=connector.manifest,
                          handlers={"publish": ForgetfulPublisher()})
    outcome = run_job(forgetful, job(artifact()))
    assert outcome.status == "failed"
    assert "PB-3" in outcome.error.message
