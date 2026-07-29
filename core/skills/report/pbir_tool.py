#!/usr/bin/env python3
"""pbir_tool — the report skill's PBIR authoring tooling (RA-5).

Deterministic PBIR generation from the artifact's layout section +
Fabric REST deployment + the RA-7 read-back verify. This file is
skill-local by ruling: it ships with the report skill bundle and runs
in the customer's session with nothing but python3 and the session's
Power BI environment — no repo, no venv, no third-party packages, and
NO database credentials (RA-2: the only secret this tool may see is the
Power BI service principal's).

The four commands mirror authoring-spec §4 stages 6–9:

  generate  --artifact F --delivered F --out DIR [--generated-date D]
            stage 6: layout + delivered schema → PBIR parts, field
            refs linted against the DELIVERED columns (never guessed),
            the RA-4 trust element rendered from trust_notes verbatim.
            Prints {pbir_hash, parts}. Deterministic: same inputs →
            byte-identical parts (ids derive from content, no clocks).

  deploy    --parts DIR --workspace W --display-name N [--report-id R]
            stage 7: create on revision 1, update the same report_id
            in place thereafter (RA-8). Prints {report_id}.

  verify    --parts DIR --workspace W --report-id R --delivered F
            stage 8: read back the deployed definition; assert every
            authored part matches canonically AND every field ref
            resolves against the delivered schema. Prints
            {verified, definition_hash}; exits 1 on mismatch — never
            attest unverified work.

  attest-payload --parts DIR --report-id R
            stage 9 input: the attestation JSON for publish_report.

Auth: prefers a pre-acquired token in POWERBI_FABRIC_TOKEN (the
compiled setup can inject a scoped token — §10's "never the raw secret
where the platform can avoid it"); falls back to the client-credentials
grant from POWERBI_TENANT_ID / POWERBI_CLIENT_ID /
POWERBI_CLIENT_SECRET. Fixture stubs override hosts via
PBIR_FABRIC_BASE_OVERRIDE / PBIR_LOGIN_BASE_OVERRIDE — path shapes stay
the pinned ones.

Pinned Microsoft surface (D-89 pattern; the platform repo's
connectors/powerbi/reference.py carries the master copy and a CI test
asserts this skill-local copy never drifts from it):
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# --- pinned surface (subset of connectors/powerbi/reference.py; the
# --- pin-sync CI test keeps the two copies identical) -----------------------

PINNED = {
    "login_base": "https://login.microsoftonline.com",
    "fabric_api_base": "https://api.fabric.microsoft.com/v1",
    "fabric_scope": "https://api.fabric.microsoft.com/.default",
    "endpoints": {
        "token": {
            "method": "POST",
            "template": "https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token",
            "ref": "entra-client-credentials",
        },
        "fabric.create_report": {
            "method": "POST",
            "template": "https://api.fabric.microsoft.com/v1/workspaces/{workspaceId}/reports",
            "ref": "fabric-create-report",
        },
        "fabric.update_report_definition": {
            "method": "POST",
            "template": "https://api.fabric.microsoft.com/v1/workspaces/{workspaceId}/reports/{reportId}/updateDefinition",
            "ref": "fabric-update-report-definition",
        },
        "fabric.get_report_definition": {
            "method": "POST",
            "template": "https://api.fabric.microsoft.com/v1/workspaces/{workspaceId}/reports/{reportId}/getDefinition",
            "ref": "fabric-get-report-definition",
        },
        "fabric.operation_state": {
            "method": "GET",
            "template": "https://api.fabric.microsoft.com/v1/operations/{operationId}",
            "ref": "fabric-lro",
        },
        "fabric.operation_result": {
            "method": "GET",
            "template": "https://api.fabric.microsoft.com/v1/operations/{operationId}/result",
            "ref": "fabric-lro",
        },
    },
    "references": {
        "entra-client-credentials": {
            "url": "https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow",
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
        "fabric-lro": {
            "url": "https://learn.microsoft.com/en-us/rest/api/fabric/articles/long-running-operation",
            "retrieved": "2026-07-29",
        },
        "fabric-report-definition": {
            "url": "https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/report-definition",
            "retrieved": "2026-07-29",
        },
        "pbir-projects-report": {
            "url": "https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report",
            "retrieved": "2026-07-29",
        },
        "pbir-json-schemas": {
            "url": "https://github.com/microsoft/json-schemas/tree/main/fabric/item/report/definition",
            "retrieved": "2026-07-29",
        },
    },
}

#: PBIR schema URLs we emit (ref: pbir-json-schemas — required members
#: verified against the published schemas on the retrieval date).
SCHEMAS = {
    "definitionProperties": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
    "versionMetadata": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
    "report": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/2.0.0/schema.json",
    "pagesMetadata": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
    "page": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json",
    "visualContainer": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.0.0/schema.json",
    "visualConfiguration": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualConfiguration/2.0.0/schema.json",
}

#: Registry kind → Power BI visualType + encoding-role buckets.
#: visualType strings are service visual-registry names (schema-free
#: strings per visualConfiguration 2.0.0): `barChart` appears verbatim
#: in the Fabric report-definition reference example; the rest are the
#: standard registry names, live-verified at the Phase-2 gate (a wrong
#: name fails deploy/read-back loudly, never silently).
REGISTRY_VISUALS = {
    "bar": {"visualType": "barChart", "buckets": {"x": "Category", "y": "Y", "series": "Series"}},
    "line": {"visualType": "lineChart", "buckets": {"x": "Category", "y": "Y", "series": "Series"}},
    "table": {"visualType": "tableEx", "buckets": {"columns": "Values"}},
    "scorecard": {"visualType": "card", "buckets": {"y": "Values"}},
    "pivot": {"visualType": "pivotTable", "buckets": {"x": "Rows", "series": "Columns", "y": "Values"}},
}
#: Encoding-role buckets for target-native kinds used outside the
#: registry: the generic Category/Y/Series family.
DEFAULT_BUCKETS = {"x": "Category", "y": "Y", "series": "Series", "columns": "Values"}

PAGE_WIDTH = 1280.0
PAGE_HEIGHT = 720.0
TRUST_HEIGHT = 64.0


def fail(message: str) -> "sys.NoReturn":
    print(json.dumps({"error": message}), file=sys.stderr)
    sys.exit(1)


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stable_name(*keys: str) -> str:
    """20-hex object name (the PBIR default naming convention length),
    derived from content so regeneration is byte-identical."""
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:20]


def parts_hash(parts: dict[str, dict]) -> str:
    """The pbir_hash / definition_hash formula: sha256 over the
    canonical JSON of every part, sorted by path. Both sides of the
    RA-7 comparison use this exact function."""
    digest = hashlib.sha256()
    for path in sorted(parts):
        digest.update(path.encode("utf-8"))
        digest.update(b"\n")
        digest.update(canonical(parts[path]).encode("utf-8"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


# --- generate ---------------------------------------------------------------


def build_parts(artifact: dict, delivered: dict, generated_date: str) -> dict[str, dict]:
    layout = artifact.get("layout")
    if not isinstance(layout, dict) or not isinstance(layout.get("pages"), list):
        fail("artifact.layout in the formats §4.7 shape is required (authoring stage 4 writes it)")
    trust_element = layout.get("trust_element")
    if not isinstance(trust_element, dict):
        fail("layout.trust_element is required — the artifact is invalid without it (RA-4/AT-3)")
    if trust_element.get("content_from") != "trust_notes":
        fail('layout.trust_element.content_from must be "trust_notes" (formats §4.7)')

    tables: dict[str, set[str]] = {}
    for table in (delivered.get("tables") or []):
        tables[str(table.get("name"))] = {
            str(column.get("name")) for column in (table.get("columns") or [])
        }
    if not tables:
        fail("delivered.tables is empty — run deliver_model first and pass its delivered schema")

    artifact_id = str(artifact.get("id", ""))
    dataset_id = str(delivered.get("dataset_id", ""))
    if not dataset_id:
        fail("delivered.dataset_id is required (the deliver_model result carries it)")
    trust_notes = [
        str(note) for note in ((artifact.get("semantics") or {}).get("trust_notes") or [])
    ]

    parts: dict[str, dict] = {}
    parts["definition.pbir"] = {
        "$schema": SCHEMAS["definitionProperties"],
        "version": "4.0",
        "datasetReference": {
            # The documented Fabric-REST deploy form (ref:
            # pbir-projects-report): semanticmodelid alone binds the
            # report to the delivered push model — the RA-8 rebind seam.
            "byConnection": {"connectionString": f"semanticmodelid={dataset_id}"}
        },
    }
    parts["definition/version.json"] = {
        "$schema": SCHEMAS["versionMetadata"],
        "version": "2.0.0",
    }
    parts["definition/report.json"] = {
        "$schema": SCHEMAS["report"],
        "themeCollection": {},
    }

    page_order: list[str] = []
    for page_index, page in enumerate(layout["pages"]):
        page_display = str(page.get("name") or f"Page {page_index + 1}")
        page_name = stable_name(artifact_id, "page", page_display)
        page_order.append(page_name)
        parts[f"definition/pages/{page_name}/page.json"] = {
            "$schema": SCHEMAS["page"],
            "name": page_name,
            "displayName": page_display,
            "displayOption": "FitToPage",
            "height": PAGE_HEIGHT,
            "width": PAGE_WIDTH,
        }

        visuals = page.get("visuals") or []
        trust_here = trust_element.get("page") == page.get("name")
        usable_height = PAGE_HEIGHT - (TRUST_HEIGHT + 16.0 if trust_here else 0.0)
        grid_columns = 1 if len(visuals) <= 1 else 2
        rows = (len(visuals) + grid_columns - 1) // grid_columns
        cell_w = PAGE_WIDTH / grid_columns
        cell_h = usable_height / max(rows, 1)

        for visual_index, visual in enumerate(visuals):
            visual_name = stable_name(artifact_id, "visual", page_display, str(visual_index))
            table = str(visual.get("table", ""))
            if table not in tables:
                fail(
                    f"layout visual {visual_index} on page {page_display!r} names table "
                    f"{table!r}, which the delivered model does not carry "
                    f"(delivered: {sorted(tables)})"
                )
            registry_kind = visual.get("registry_kind")
            kind = str(visual.get("kind", ""))
            spec = REGISTRY_VISUALS.get(str(registry_kind)) or REGISTRY_VISUALS.get(kind)
            visual_type = spec["visualType"] if spec else kind
            buckets = spec["buckets"] if spec else DEFAULT_BUCKETS

            query_state: dict[str, dict] = {}
            for encoding, bucket in buckets.items():
                value = visual.get(encoding)
                columns = value if isinstance(value, list) else [value] if value else []
                projections = []
                for column in columns:
                    column = str(column)
                    if column not in tables[table]:
                        # The AT-4 gate, locally, before any deploy:
                        # field refs come from the DELIVERED schema or
                        # they do not exist (authoring §8: never guess
                        # field names).
                        fail(
                            f"visual {visual_index} on page {page_display!r} references "
                            f"{table}.{column}, absent from the delivered schema "
                            f"(delivered columns: {sorted(tables[table])})"
                        )
                    projections.append({
                        "field": {
                            "Column": {
                                "Expression": {"SourceRef": {"Entity": table}},
                                "Property": column,
                            }
                        },
                        "queryRef": f"{table}.{column}",
                    })
                if projections:
                    query_state[bucket] = {"projections": projections}
            if not query_state:
                fail(
                    f"visual {visual_index} on page {page_display!r} has no usable encodings "
                    f"for kind {visual_type!r} (expected members: {sorted(buckets)})"
                )

            row, col = divmod(visual_index, grid_columns)
            parts[f"definition/pages/{page_name}/visuals/{visual_name}/visual.json"] = {
                "$schema": SCHEMAS["visualContainer"],
                "name": visual_name,
                "position": {
                    "x": round(col * cell_w + 8, 2),
                    "y": round(row * cell_h + 8, 2),
                    "z": float(visual_index),
                    "width": round(cell_w - 16, 2),
                    "height": round(cell_h - 16, 2),
                },
                # NB: the nested visual object is the EMBEDDED
                # visualConfiguration (schema-embedded.json) — it
                # rejects a $schema member; live-verified 2026-07-29
                # (Report_Import_FailedToImportReport names it).
                "visual": {
                    "visualType": visual_type,
                    "query": {"queryState": query_state},
                    "drillFilterOtherVisuals": True,
                    **({"objects": {"title": [{"properties": {"text": {"expr": {"Literal": {
                        "Value": f"'{str(visual.get('title'))}'"}}}}}]}
                       } if visual.get("title") else {}),
                },
            }

        if trust_here:
            # RA-4: the disclosures are a visible element OF the report —
            # trust_notes verbatim, artifact id, generated date.
            lines = [f"Trust: {note}" for note in trust_notes] or [
                "Trust: no outstanding disclosures for this report's sources."
            ]
            lines.append(f"Context Layer artifact {artifact_id} — generated {generated_date}.")
            trust_name = stable_name(artifact_id, "trust", page_display)
            parts[f"definition/pages/{page_name}/visuals/{trust_name}/visual.json"] = {
                "$schema": SCHEMAS["visualContainer"],
                "name": trust_name,
                "position": {
                    "x": 8.0,
                    "y": round(PAGE_HEIGHT - TRUST_HEIGHT - 8, 2),
                    "z": 1000.0,
                    "width": round(PAGE_WIDTH - 16, 2),
                    "height": TRUST_HEIGHT,
                },
                "visual": {
                    "visualType": "textbox",
                    "objects": {
                        "general": [{
                            "properties": {
                                "paragraphs": [
                                    {"textRuns": [{"value": line}]} for line in lines
                                ]
                            }
                        }]
                    },
                },
            }

    if not any(
        trust_element.get("page") == page.get("name") for page in layout["pages"]
    ):
        fail(
            f"layout.trust_element.page {trust_element.get('page')!r} names no layout page — "
            "the trust element must land on a real page (RA-4)"
        )

    parts["definition/pages/pages.json"] = {
        "$schema": SCHEMAS["pagesMetadata"],
        "pageOrder": page_order,
        "activePageName": page_order[0],
    }
    return parts


def cmd_generate(args) -> int:
    artifact = _read_json(args.artifact)
    delivered = _read_json(args.delivered)
    generated_date = args.generated_date or time.strftime("%Y-%m-%d")
    parts = build_parts(artifact, delivered, generated_date)
    os.makedirs(args.out, exist_ok=True)
    for path, content in parts.items():
        full = os.path.join(args.out, path.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical(content))
    digest = parts_hash(parts)
    with open(os.path.join(args.out, "pbir_hash.txt"), "w", encoding="utf-8") as handle:
        handle.write(digest + "\n")
    print(json.dumps({"pbir_hash": digest, "parts": sorted(parts)}, indent=2))
    return 0


# --- HTTP (stdlib; pinned emission) -----------------------------------------


def _endpoint(name: str, **params: str) -> tuple[str, str]:
    entry = PINNED["endpoints"].get(name)
    if entry is None:
        fail(f"endpoint {name!r} is not in this tool's pinned Microsoft surface")
    url = entry["template"]
    for key, value in params.items():
        if not value or any(ch in value for ch in "/?#% "):
            fail(f"endpoint {name!r} parameter {key} has an unsafe value")
        url = url.replace("{" + key + "}", value)
    if "{" in url:
        fail(f"endpoint {name!r} is missing parameters ({url})")
    for canonical_base, env in (
        (PINNED["fabric_api_base"], "PBIR_FABRIC_BASE_OVERRIDE"),
        (PINNED["login_base"], "PBIR_LOGIN_BASE_OVERRIDE"),
    ):
        override = os.environ.get(env, "")
        if override and url.startswith(canonical_base):
            url = override.rstrip("/") + url[len(canonical_base):]
    return entry["method"], url


def _http(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), error.read()


def _token() -> str:
    token = os.environ.get("POWERBI_FABRIC_TOKEN", "")
    if token:
        return token
    tenant = os.environ.get("POWERBI_TENANT_ID", "")
    client = os.environ.get("POWERBI_CLIENT_ID", "")
    secret = os.environ.get("POWERBI_CLIENT_SECRET", "")
    if not (tenant and client and secret):
        fail(
            "no Fabric credentials: set POWERBI_FABRIC_TOKEN (preferred) or "
            "POWERBI_TENANT_ID + POWERBI_CLIENT_ID + POWERBI_CLIENT_SECRET"
        )
    method, url = _endpoint("token", tenantId=tenant)
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client,
        "client_secret": secret,
        "scope": PINNED["fabric_scope"],
    }).encode("ascii")
    status, _, raw = _http(method, url, {"Content-Type": "application/x-www-form-urlencoded"}, body)
    parsed = _parse(raw)
    if status != 200 or not parsed.get("access_token"):
        fail(f"token acquisition failed (HTTP {status})")
    return str(parsed["access_token"])


def _parse(raw: bytes) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _fabric(name: str, token: str, *, params: dict[str, str], body: dict | None = None,
            expect: tuple[int, ...] = (200, 201)) -> dict:
    method, url = _endpoint(name, **params)
    headers = {"Authorization": f"Bearer {token}"}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body).encode("utf-8")
    status, response_headers, raw = _http(method, url, headers, payload)
    if status == 202:
        # Pinned LRO contract: poll state, then fetch the result.
        operation = ""
        for key, value in response_headers.items():
            if key.lower() == "x-ms-operation-id":
                operation = str(value)
        if not operation:
            fail(f"{name}: Fabric 202 carried no x-ms-operation-id")
        waited = 0.0
        while True:
            retry_after = 2.0
            for key, value in response_headers.items():
                if key.lower() == "retry-after":
                    try:
                        retry_after = float(value)
                    except ValueError:
                        pass
            time.sleep(min(retry_after, 30.0))
            waited += retry_after
            status, response_headers, raw = _http(
                *(_endpoint("fabric.operation_state", operationId=operation)),
                {"Authorization": f"Bearer {token}"}, None,
            )
            parsed_state = _parse(raw)
            state = str(parsed_state.get("status", ""))
            if state == "Succeeded":
                status, _, raw = _http(
                    *(_endpoint("fabric.operation_result", operationId=operation)),
                    {"Authorization": f"Bearer {token}"}, None,
                )
                return _parse(raw)
            if state == "Failed" or waited > 600:
                error = parsed_state.get("error")
                fail(
                    f"{name}: Fabric operation {operation} {state or 'timed out'}"
                    + (f" — {json.dumps(error)}" if error else "")
                )
    if status not in expect:
        code = str(_parse(raw).get("errorCode", ""))
        fail(f"{name} failed (HTTP {status}{f' {code}' if code else ''})")
    return _parse(raw)


def _load_parts(directory: str) -> dict[str, dict]:
    parts: dict[str, dict] = {}
    for root, _dirs, files in os.walk(directory):
        for name in files:
            if name == "pbir_hash.txt":
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, directory).replace(os.sep, "/")
            with open(full, "r", encoding="utf-8") as handle:
                parts[rel] = json.load(handle)
    if "definition.pbir" not in parts:
        fail(f"{directory} holds no definition.pbir — run generate first")
    return parts


def _definition_body(parts: dict[str, dict]) -> dict:
    return {
        "definition": {
            "parts": [
                {
                    "path": path,
                    "payload": base64.b64encode(canonical(parts[path]).encode("utf-8")).decode("ascii"),
                    "payloadType": "InlineBase64",
                }
                for path in sorted(parts)
            ]
        }
    }


def cmd_deploy(args) -> int:
    parts = _load_parts(args.parts)
    token = _token()
    if args.report_id:
        _fabric(
            "fabric.update_report_definition", token,
            params={"workspaceId": args.workspace, "reportId": args.report_id},
            body=_definition_body(parts), expect=(200,),
        )
        print(json.dumps({"report_id": args.report_id, "action": "updated"}))
        return 0
    body = {"displayName": args.display_name, **_definition_body(parts)}
    created = _fabric(
        "fabric.create_report", token,
        params={"workspaceId": args.workspace}, body=body, expect=(201,),
    )
    report_id = str(created.get("id", ""))
    if not report_id:
        fail("create returned no report id")
    print(json.dumps({"report_id": report_id, "action": "created"}))
    return 0


def cmd_verify(args) -> int:
    parts = _load_parts(args.parts)
    delivered = _read_json(args.delivered)
    token = _token()
    response = _fabric(
        "fabric.get_report_definition", token,
        params={"workspaceId": args.workspace, "reportId": args.report_id},
        body=None, expect=(200,),
    )
    deployed: dict[str, dict] = {}
    for part in ((response.get("definition") or {}).get("parts") or []):
        path = str(part.get("path", ""))
        try:
            deployed[path] = json.loads(base64.b64decode(part.get("payload", "")).decode("utf-8"))
        except Exception:
            deployed[path] = {"_undecodable": True}

    problems: list[str] = []
    for path in sorted(parts):
        if path not in deployed:
            problems.append(f"authored part {path} is absent from the deployed definition")
        elif path == "definition.pbir":
            # Live-verified 2026-07-29: the service EXPANDS the deployed
            # connection string ('semanticmodelid=<id>' comes back as the
            # full 'Data Source="powerbi://…";initial catalog=…;
            # semanticmodelid=<id>' form). The fact RA-7 must hold is the
            # BINDING: the deployed report points at the same semantic
            # model we authored against; the rest of the part must still
            # match structurally.
            authored_id = _semantic_model_id(parts[path])
            deployed_id = _semantic_model_id(deployed[path])
            if authored_id is None or deployed_id != authored_id:
                problems.append(
                    f"definition.pbir binds semantic model {deployed_id!r}, "
                    f"authored {authored_id!r}"
                )
            elif canonical(_without_connection(deployed[path])) != canonical(
                _without_connection(parts[path])
            ):
                problems.append("definition.pbir differs beyond the connection string")
            else:
                # Normalized-equal: hash over the authored form so the
                # definition_hash equality below means what it says.
                deployed[path] = parts[path]
        elif canonical(deployed[path]) != canonical(parts[path]):
            problems.append(f"deployed part {path} differs from the authored part")

    # Field-ref lint against the DELIVERED schema (RA-7 clause b).
    tables = {
        str(table.get("name")): {str(c.get("name")) for c in (table.get("columns") or [])}
        for table in (delivered.get("tables") or [])
    }
    for path, content in sorted(parts.items()):
        if not path.endswith("visual.json"):
            continue
        query_state = ((content.get("visual") or {}).get("query") or {}).get("queryState") or {}
        for bucket in query_state.values():
            for projection in bucket.get("projections", []):
                column_ref = (projection.get("field") or {}).get("Column") or {}
                entity = ((column_ref.get("Expression") or {}).get("SourceRef") or {}).get("Entity")
                prop = column_ref.get("Property")
                if entity not in tables or prop not in tables.get(entity, set()):
                    problems.append(f"{path}: field {entity}.{prop} does not resolve in the delivered schema")

    authored_hash = parts_hash(parts)
    deployed_hash = parts_hash({p: deployed[p] for p in parts if p in deployed})
    verdict = {
        "verified": not problems and deployed_hash == authored_hash,
        "definition_hash": authored_hash,
        "deployed_hash": deployed_hash,
        **({"problems": problems} if problems else {}),
    }
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["verified"] else 1


def cmd_attest_payload(args) -> int:
    parts = _load_parts(args.parts)
    print(json.dumps({
        "report_id": args.report_id,
        "definition_hash": parts_hash(parts),
    }))
    return 0


def _semantic_model_id(content: dict) -> str | None:
    connection = (
        ((content.get("datasetReference") or {}).get("byConnection") or {})
        .get("connectionString", "")
    )
    for piece in str(connection).split(";"):
        key, _, value = piece.partition("=")
        if key.strip().lower() == "semanticmodelid":
            return value.strip().strip('"').lower() or None
    return None


def _without_connection(content: dict) -> dict:
    clone = json.loads(json.dumps(content))
    by_connection = (clone.get("datasetReference") or {}).get("byConnection")
    if isinstance(by_connection, dict):
        by_connection.pop("connectionString", None)
    return clone


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as error:
        fail(f"cannot read {path}: {error}")
    if not isinstance(value, dict):
        fail(f"{path} does not hold a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pbir_tool", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate")
    generate.add_argument("--artifact", required=True)
    generate.add_argument("--delivered", required=True)
    generate.add_argument("--out", required=True)
    generate.add_argument("--generated-date", default="")
    generate.set_defaults(fn=cmd_generate)

    deploy = sub.add_parser("deploy")
    deploy.add_argument("--parts", required=True)
    deploy.add_argument("--workspace", required=True)
    deploy.add_argument("--display-name", default="Context Layer report")
    deploy.add_argument("--report-id", default="")
    deploy.set_defaults(fn=cmd_deploy)

    verify = sub.add_parser("verify")
    verify.add_argument("--parts", required=True)
    verify.add_argument("--workspace", required=True)
    verify.add_argument("--report-id", required=True)
    verify.add_argument("--delivered", required=True)
    verify.set_defaults(fn=cmd_verify)

    attest = sub.add_parser("attest-payload")
    attest.add_argument("--parts", required=True)
    attest.add_argument("--report-id", required=True)
    attest.set_defaults(fn=cmd_attest_payload)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
