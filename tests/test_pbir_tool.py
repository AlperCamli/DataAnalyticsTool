"""The skill-local PBIR tooling (RA-5/RA-7) — generation, gates, verify.

Covers: the pin-sync invariant (the skill-local copy of the Microsoft
surface never drifts from connectors/powerbi/reference.py — the same
D-46 instinct that keeps the vendored wheel honest), deterministic
generation (byte-identical parts, no clocks in ids), the RA-4 trust
element rendered verbatim (authoring AT-3 at the render layer), the
local AT-4 gate (a field absent from the delivered schema refuses
generation BEFORE any deploy), and deploy/verify against an in-process
stub Fabric API — including the tampered-deploy case where verify says
no and exits nonzero (RA-7: never attest unverified work).
"""

import importlib.util
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from connectors.powerbi import reference as ref

TOOL_PATH = Path(__file__).resolve().parents[1] / "core" / "skills" / "report" / "pbir_tool.py"

spec = importlib.util.spec_from_file_location("pbir_tool", TOOL_PATH)
pbir_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pbir_tool)


def artifact() -> dict:
    return {
        "artifact_version": "1",
        "id": "ra-018f3c00-9abc-4000-8000-000000000001",
        "title": "Search vs analytics",
        "semantics": {"trust_notes": ["built on draft doc systems/ga4/metrics.md — user acknowledged"]},
        "layout": {
            "designed_by": "report-skill@test",
            "pages": [{
                "name": "Overview",
                "visuals": [
                    {"kind": "bar", "registry_kind": "bar", "table": "gsc_pages",
                     "x": "page", "y": "clicks", "title": "Clicks by page"},
                    {"kind": "table", "registry_kind": "table", "table": "ga4_sessions",
                     "columns": ["pagePath", "sessions"]},
                ],
            }],
            "trust_element": {"page": "Overview", "placement": "footer", "content_from": "trust_notes"},
        },
    }


def delivered() -> dict:
    return {
        "workspace_id": "11111111-1111-4111-8111-111111111111",
        "dataset_id": "cfafbeb1-8037-4d0c-896e-a46fb27ff229",
        "tables": [
            {"name": "gsc_pages", "columns": [
                {"name": "page", "type": "String", "source_type": "text"},
                {"name": "clicks", "type": "Int64", "source_type": "int8"},
            ], "rows_delivered": 2},
            {"name": "ga4_sessions", "columns": [
                {"name": "pagePath", "type": "String", "source_type": "text"},
                {"name": "sessions", "type": "Int64", "source_type": "int4"},
            ], "rows_delivered": 2},
        ],
    }


GENERATED_DATE = "2026-07-29"


def build():
    return pbir_tool.build_parts(artifact(), delivered(), GENERATED_DATE)


# --- pin sync (the two copies of the Microsoft surface never drift) ---------


def test_skill_pins_match_the_reference_module():
    for name, entry in pbir_tool.PINNED["endpoints"].items():
        master = ref.ENDPOINTS.get(name)
        assert master is not None, f"skill tool pins {name!r}, reference.py does not"
        assert entry["method"] == master["method"]
        assert entry["template"] == master["template"]
        assert entry["ref"] == master["ref"]
    for key, pin in pbir_tool.PINNED["references"].items():
        if key in ref.REFERENCES:
            assert pin == ref.REFERENCES[key], f"reference {key!r} drifted between copies"
        else:
            # Skill-only pins (PBIR docs) still carry URL + date.
            assert pin["url"].startswith("https://")
            assert pin["retrieved"] >= "2026-07-29"
    assert pbir_tool.PINNED["fabric_api_base"] == ref.FABRIC_API_BASE
    assert pbir_tool.PINNED["login_base"] == ref.LOGIN_BASE
    assert pbir_tool.PINNED["fabric_scope"] == ref.FABRIC_SCOPE


# --- generation --------------------------------------------------------------


def test_generation_is_deterministic_and_complete():
    first, second = build(), build()
    assert first == second
    assert pbir_tool.parts_hash(first) == pbir_tool.parts_hash(second)
    # The required PBIR part set (pinned via projects-report).
    assert "definition.pbir" in first
    assert "definition/version.json" in first
    assert "definition/report.json" in first
    assert "definition/pages/pages.json" in first
    page_parts = [p for p in first if p.endswith("/page.json")]
    visual_parts = [p for p in first if p.endswith("/visual.json")]
    assert len(page_parts) == 1
    assert len(visual_parts) == 3  # two layout visuals + the trust element


def test_definition_pbir_binds_the_delivered_model():
    parts = build()
    connection = parts["definition.pbir"]["datasetReference"]["byConnection"]["connectionString"]
    assert connection == "semanticmodelid=cfafbeb1-8037-4d0c-896e-a46fb27ff229"
    assert parts["definition/version.json"]["version"] == "2.0.0"


def test_projections_come_from_the_delivered_schema():
    parts = build()
    bar = next(
        content for path, content in parts.items()
        if path.endswith("visual.json") and content["visual"].get("visualType") == "barChart"
    )
    state = bar["visual"]["query"]["queryState"]
    assert state["Category"]["projections"][0]["field"]["Column"] == {
        "Expression": {"SourceRef": {"Entity": "gsc_pages"}}, "Property": "page",
    }
    assert state["Y"]["projections"][0]["queryRef"] == "gsc_pages.clicks"


def test_trust_element_renders_notes_verbatim_with_id_and_date():
    parts = build()
    boxes = [
        content for path, content in parts.items()
        if path.endswith("visual.json") and content["visual"].get("visualType") == "textbox"
    ]
    assert len(boxes) == 1
    runs = [
        run["value"]
        for paragraph in boxes[0]["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
        for run in paragraph["textRuns"]
    ]
    assert "Trust: built on draft doc systems/ga4/metrics.md — user acknowledged" in runs
    assert any("ra-018f3c00-9abc-4000-8000-000000000001" in r and GENERATED_DATE in r for r in runs)


def test_missing_trust_element_refuses_generation():
    art = artifact()
    del art["layout"]["trust_element"]
    with pytest.raises(SystemExit):
        pbir_tool.build_parts(art, delivered(), GENERATED_DATE)


def test_field_absent_from_delivered_schema_refuses_generation(capsys):
    # The AT-4 gate locally: refs come from the DELIVERED schema or the
    # tool refuses before any deploy — never guessed field names.
    art = artifact()
    art["layout"]["pages"][0]["visuals"][0]["y"] = "impressions"
    with pytest.raises(SystemExit):
        pbir_tool.build_parts(art, delivered(), GENERATED_DATE)
    err = capsys.readouterr().err
    assert "gsc_pages.impressions" in err
    assert "delivered schema" in err


def test_undelivered_table_refuses_generation():
    art = artifact()
    art["layout"]["pages"][0]["visuals"][0]["table"] = "nope"
    with pytest.raises(SystemExit):
        pbir_tool.build_parts(art, delivered(), GENERATED_DATE)


# --- deploy / verify against a stub Fabric ----------------------------------


class StubFabric(BaseHTTPRequestHandler):
    reports: dict[str, dict] = {}
    tamper: str | None = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.endswith("/reports"):
            report_id = "5b218778-e7a5-4d73-8187-f10824047715"
            type(self).reports[report_id] = body["definition"]
            self._reply(201, {"id": report_id, "displayName": body.get("displayName")})
        elif self.path.endswith("/updateDefinition"):
            report_id = self.path.split("/reports/")[1].split("/")[0]
            type(self).reports[report_id] = body["definition"]
            self._reply(200, {})
        elif self.path.endswith("/getDefinition"):
            report_id = self.path.split("/reports/")[1].split("/")[0]
            definition = type(self).reports.get(report_id, {"parts": []})
            parts = definition["parts"]
            if type(self).tamper:
                parts = [dict(p) for p in parts]
                for part in parts:
                    if part["path"] == type(self).tamper:
                        import base64 as b64
                        tampered = json.loads(b64.b64decode(part["payload"]))
                        tampered["tampered"] = True
                        part["payload"] = b64.b64encode(
                            json.dumps(tampered).encode()).decode()
            self._reply(200, {"definition": {"parts": parts}})
        elif "/oauth2/v2.0/token" in self.path:
            self._reply(200, {"access_token": "stub-token", "expires_in": 3599})
        else:
            self._reply(404, {"errorCode": "NotFound"})

    def _reply(self, status: int, body: dict):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):  # quiet
        pass


@pytest.fixture()
def stub_fabric():
    server = HTTPServer(("127.0.0.1", 0), StubFabric)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    StubFabric.reports = {}
    StubFabric.tamper = None
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def run_tool(args: list[str], base: str, tmp_path: Path) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin",
        "PBIR_FABRIC_BASE_OVERRIDE": base,
        "PBIR_LOGIN_BASE_OVERRIDE": base,
        "POWERBI_FABRIC_TOKEN": "stub-token",
        "HOME": str(tmp_path),
    }
    return subprocess.run(
        [sys.executable, str(TOOL_PATH), *args],
        capture_output=True, text=True, env=env,
    )


def write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    artifact_file = tmp_path / "artifact.json"
    delivered_file = tmp_path / "delivered.json"
    parts_dir = tmp_path / "parts"
    artifact_file.write_text(json.dumps(artifact()), encoding="utf-8")
    delivered_file.write_text(json.dumps(delivered()), encoding="utf-8")
    return artifact_file, delivered_file, parts_dir


def test_generate_deploy_verify_attest_round_trip(stub_fabric, tmp_path):
    artifact_file, delivered_file, parts_dir = write_inputs(tmp_path)

    generated = run_tool([
        "generate", "--artifact", str(artifact_file), "--delivered", str(delivered_file),
        "--out", str(parts_dir), "--generated-date", GENERATED_DATE,
    ], stub_fabric, tmp_path)
    assert generated.returncode == 0, generated.stderr
    pbir_hash = json.loads(generated.stdout)["pbir_hash"]

    deployed = run_tool([
        "deploy", "--parts", str(parts_dir),
        "--workspace", "11111111-1111-4111-8111-111111111111",
        "--display-name", "Search vs analytics",
    ], stub_fabric, tmp_path)
    assert deployed.returncode == 0, deployed.stderr
    report_id = json.loads(deployed.stdout)["report_id"]

    verified = run_tool([
        "verify", "--parts", str(parts_dir),
        "--workspace", "11111111-1111-4111-8111-111111111111",
        "--report-id", report_id, "--delivered", str(delivered_file),
    ], stub_fabric, tmp_path)
    assert verified.returncode == 0, verified.stderr
    verdict = json.loads(verified.stdout)
    assert verdict["verified"] is True
    assert verdict["definition_hash"] == pbir_hash
    assert verdict["deployed_hash"] == pbir_hash

    attest = run_tool([
        "attest-payload", "--parts", str(parts_dir), "--report-id", report_id,
    ], stub_fabric, tmp_path)
    payload = json.loads(attest.stdout)
    assert payload == {"report_id": report_id, "definition_hash": pbir_hash}

    # Update-in-place (RA-8): deploy with --report-id updates, same id.
    redeploy = run_tool([
        "deploy", "--parts", str(parts_dir),
        "--workspace", "11111111-1111-4111-8111-111111111111",
        "--report-id", report_id,
    ], stub_fabric, tmp_path)
    assert redeploy.returncode == 0, redeploy.stderr
    assert json.loads(redeploy.stdout) == {"report_id": report_id, "action": "updated"}


def test_verify_fails_nonzero_on_a_tampered_deploy(stub_fabric, tmp_path):
    artifact_file, delivered_file, parts_dir = write_inputs(tmp_path)
    run_tool(["generate", "--artifact", str(artifact_file), "--delivered", str(delivered_file),
              "--out", str(parts_dir), "--generated-date", GENERATED_DATE], stub_fabric, tmp_path)
    deployed = run_tool(["deploy", "--parts", str(parts_dir),
                         "--workspace", "11111111-1111-4111-8111-111111111111",
                         "--display-name", "x"], stub_fabric, tmp_path)
    report_id = json.loads(deployed.stdout)["report_id"]

    StubFabric.tamper = "definition/report.json"
    verified = run_tool(["verify", "--parts", str(parts_dir),
                         "--workspace", "11111111-1111-4111-8111-111111111111",
                         "--report-id", report_id, "--delivered", str(delivered_file)],
                        stub_fabric, tmp_path)
    assert verified.returncode == 1  # RA-7: never attest unverified work
    verdict = json.loads(verified.stdout)
    assert verdict["verified"] is False
    assert any("definition/report.json" in p for p in verdict["problems"])
