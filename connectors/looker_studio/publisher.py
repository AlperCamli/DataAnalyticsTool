"""Looker Studio publisher — the template-link path (capability §8).

The whole adapter is a deterministic translation: report artifact +
connection config → one prefilled Linking API URL
(`https://lookerstudio.google.com/reporting/create?...`) that swaps the
pre-built template's data sources for the customer's, plus the honest
`pending_human_steps` that template_link mode mandates (PB-3). No
Google API is called and no secret rides the URL: the human opens the
link, enters the database password in the Looker UI, and clicks create.

Because the translation is a pure function of `(artifact, target,
config)`, idempotency (PB-2/CC-7) holds by construction: the same
artifact published to the same target yields byte-identical `created`
entries — id and URL — every time. The stable publisher id is derived
from `(artifact.id, target)`, not from content, so a revised artifact
updates the same object identity (F-5) rather than minting a new one.

Linking API parameter names are pinned here in one table
(`_SOURCE_PARAMS`) from the published Linking API documentation. They
are externally owned and the live M3 gate verifies them by opening a
real link; a drifted name degrades softly — the human completes that
field in the UI, which template_link journeys already require.

`sql_backing: views` is enforced structurally: a SQL-dialect query
whose backing is not `reporting_view` is refused with the actionable
error (formats §4.2 — the SK-6 branch should have produced a view; raw
SELECT text is not a thing a Looker data source can point at).
"""

from __future__ import annotations

import hashlib
from urllib.parse import quote, urlencode

from connectors.sdk.errors import ConfigError
from connectors.sdk.providers import Identity, Publisher, PublishRequest, PublishResult

LINKING_BASE = "https://lookerstudio.google.com/reporting/create"

#: Formats spec §4.4 registry v1 — closed set, additive growth only.
VISUAL_KINDS = ("table", "line", "bar", "scorecard", "pivot")

#: Linking API `ds.<alias>.*` parameters per source kind. `connector`
#: is the Linking API's connector id; the remaining entries map our
#: config keys onto Linking API parameter names.
_SOURCE_PARAMS: dict[str, dict[str, str]] = {
    "postgres": {
        "connector": "postgreSQL",
        "host": "host",
        "port": "port",
        "database": "database",
        "username": "username",
    },
    "ga4": {
        "connector": "googleAnalytics",
        "property_id": "propertyId",
    },
    "gsc": {
        "connector": "searchConsole",
        "site_url": "siteUrl",
        "table_type": "tableType",
    },
}


def _stable_id(artifact_id: str, target: str) -> str:
    """PB-2 stable publisher id per (artifact.id, target)."""
    digest = hashlib.sha256(f"{artifact_id}\n{target}".encode("utf-8")).hexdigest()
    return f"tl-{digest[:16]}"


class LookerStudioPublisher(Publisher):
    SUPPORTED_ARTIFACT_VERSIONS = ("1",)

    def publish(
        self,
        config: dict,
        request: PublishRequest,
        identity: Identity,
        flags: dict,
    ) -> PublishResult:
        # PB-1 / CC-8: this adapter implements template_link and nothing
        # else; effective flags asking for more (or forbidding even
        # that) are a configuration/release bug, surfaced as such.
        create_report = flags.get("create_report")
        if create_report != "template_link":
            raise ConfigError(
                f"looker_studio publishes via template_link only; effective "
                f"create_report={create_report!r} cannot be honored (PB-1)"
            )

        artifact = request.artifact
        artifact_id = artifact.get("id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ConfigError(
                "artifact.id (stable UUID, formats §4.1) is required — "
                "publish identity and idempotency key off it (F-5/PB-2)"
            )
        queries = artifact.get("queries")
        if not isinstance(queries, list) or not queries:
            raise ConfigError("artifact carries no queries; nothing to wire")

        template_id = config.get("template_report_id")
        if not isinstance(template_id, str) or not template_id:
            raise ConfigError("config.template_report_id is required for template_link")
        sources = config.get("sources")
        if not isinstance(sources, dict) or not sources:
            raise ConfigError("config.sources must map artifact systems to template aliases")

        # --- blend re-check (structural; the server did the semantic
        # MT-10/entity-doc validation before enqueue) --------------------
        blend = artifact.get("blend")
        if blend is not None:
            if flags.get("cross_source") != "blending":
                raise ConfigError(
                    "artifact carries a blend but effective cross_source is "
                    f"{flags.get('cross_source')!r}"
                )
            keys = blend.get("keys") if isinstance(blend, dict) else None
            if not isinstance(keys, list) or not keys:
                raise ConfigError("artifact.blend.keys must be a non-empty list (formats §4.5)")
            for entry in keys:
                if not isinstance(entry, dict) or not entry.get("entity_ref"):
                    raise ConfigError(
                        "every blend key needs entity_ref — blend keys come from the "
                        "entity doc's documented mappings, never improvised (formats §4.5)"
                    )

        # --- wire data sources ------------------------------------------
        ds_params: dict[str, str] = {}
        backing: list[dict] = []
        pending: list[str] = []
        unwired: list[str] = []
        wired_systems: set[str] = set()

        for query in queries:
            if not isinstance(query, dict):
                raise ConfigError("artifact.queries entries must be objects")
            system = query.get("system")
            if not isinstance(system, str) or not system:
                raise ConfigError("every artifact query needs a system")
            source = sources.get(system)
            if not isinstance(source, dict):
                raise ConfigError(
                    f"artifact query {query.get('name')!r} targets system {system!r} "
                    f"but config.sources has no wiring for it"
                )
            kind = source.get("kind")
            params = _SOURCE_PARAMS.get(kind or "")
            if params is None:
                raise ConfigError(f"config.sources[{system!r}].kind {kind!r} is not supported")
            alias = source.get("alias")
            if not isinstance(alias, str) or not alias:
                raise ConfigError(f"config.sources[{system!r}].alias is required")

            request_dialect = (query.get("request") or {}).get("dialect")
            backing_info = query.get("backing") if isinstance(query.get("backing"), dict) else {}
            if kind == "postgres":
                # sql_backing: views — the load-bearing constraint.
                if backing_info.get("mode") != "reporting_view":
                    raise ConfigError(
                        f"query {query.get('name')!r} has backing.mode="
                        f"{backing_info.get('mode')!r}; this adapter is sql_backing: views — "
                        "recurring SQL reaches Looker Studio only through a reporting view "
                        "(formats §4.2 / skill SK-6). Produce the view, re-point the query "
                        "at it, and re-validate."
                    )
                ref = backing_info.get("ref")
                if not isinstance(ref, str) or not ref:
                    raise ConfigError(
                        f"query {query.get('name')!r}: backing.mode=reporting_view needs backing.ref"
                    )
                backing_entry = {"type": "reporting_view", "ref": ref}
                if backing_entry not in backing:
                    backing.append(backing_entry)
                if system in wired_systems:
                    # One alias per system in the template: further views
                    # cannot be prefilled through the link. Honest, loud.
                    if ds_params.get(f"ds.{alias}.tableName") != ref:
                        unwired.append(ref)
                    continue
                ds_params[f"ds.{alias}.tableName"] = ref
            elif request_dialect not in (None, "api"):
                raise ConfigError(
                    f"query {query.get('name')!r}: system {system!r} is wired as {kind!r} "
                    f"but the query dialect is {request_dialect!r}"
                )

            if system not in wired_systems:
                ds_params[f"ds.{alias}.connector"] = params["connector"]
                for config_key, wire_key in params.items():
                    if config_key == "connector":
                        continue
                    value = source.get(config_key)
                    if value is not None:
                        ds_params[f"ds.{alias}.{wire_key}"] = str(value)
                wired_systems.add(system)

        # --- visual fidelity (PB-4) --------------------------------------
        substitutions: list[dict] = []
        template_kinds = config.get("template_visual_kinds")
        exercised = (
            [k for k in template_kinds if k in VISUAL_KINDS]
            if isinstance(template_kinds, list)
            else list(VISUAL_KINDS)
        )
        visuals = artifact.get("visuals")
        for visual in visuals if isinstance(visuals, list) else []:
            kind = visual.get("kind") if isinstance(visual, dict) else None
            if not isinstance(kind, str):
                continue
            if kind not in VISUAL_KINDS:
                raise ConfigError(
                    f"visual kind {kind!r} is outside the formats §4.4 registry "
                    f"({', '.join(VISUAL_KINDS)})"
                )
            if kind not in exercised:
                substitutions.append({
                    "kind": kind,
                    "substituted_with": "template default",
                    "note": (
                        f"the linked template does not exercise {kind!r}; pick the chart "
                        "in the Looker Studio editor after creating the report"
                    ),
                })

        # --- assemble the link (deterministic param order) ---------------
        title = artifact.get("title") if isinstance(artifact.get("title"), str) else "Context Layer report"
        prefix = config.get("report_name_prefix")
        report_name = f"{prefix}{title}" if isinstance(prefix, str) and prefix else title
        ordered: list[tuple[str, str]] = [
            ("c.reportId", template_id),
            ("r.reportName", report_name),
        ]
        ordered.extend(sorted(ds_params.items()))
        url = f"{LINKING_BASE}?{urlencode(ordered, quote_via=quote)}"

        pending.append("Open the template link and review the prefilled data sources.")
        if any(key.endswith(".connector") and value == "postgreSQL" for key, value in ds_params.items()):
            pending.append(
                "Enter the database password for the reporting role when Looker Studio "
                "prompts (credentials never ride the link), and enable SSL."
            )
        if blend is not None:
            pairs = ", ".join(
                f"{k.get('left_column')}×{k.get('right_column')} per {k.get('entity_ref')}"
                for k in blend.get("keys", [])
                if isinstance(k, dict)
            )
            pending.append(f"Verify the blend join ({pairs}) matches the template's blend setup.")
        for ref in unwired:
            pending.append(
                f"Add a data source for {ref} in the editor — the template exposes one "
                "data source per system and it is already used."
            )
        pending.append('Click "Edit and share" to create your copy of the report.')

        detail: dict = {
            "template_report_id": template_id,
            "visual_substitutions": substitutions,
        }
        if unwired:
            detail["unwired_backings"] = unwired

        return PublishResult(
            mode="template_link",
            created=[{
                "type": "template_link",
                "id": _stable_id(artifact_id, request.target),
                "url": url,
            }],
            pending_human_steps=pending,
            backing=backing,
            detail=detail,
        )
