"""Wire JSON → snapshot objects. Pure functions, no I/O (D-23..D-27).

One object per definition: the Data API metadata endpoint enumerates
the queryable estate (existence, apiName, description, metric type);
the Admin API decorates custom entries with the registered definition
facts it alone carries — `scope` for custom metrics, `formula` for
calculated metrics (D-23). Custom-dimension scope is *not* emitted:
GA4's naming rule already encodes it in the apiName prefix, and §4.5
registers `scope` for `api_metric` only.

Every free-text field is verbatim or null (S-8): proto3 JSON omits
empty strings, so an absent/empty `description` becomes null. Key
events carry no description at all (D-25).

The two surfaces are read by separate non-atomic calls; a custom
definition present on one but not the other is a torn read and fails
the job `source_unavailable` (retryable) — the snapshot must describe
one moment (S-6).
"""

from connectors.sdk import ConnectorError, SourceUnavailable

# GA4's own scope→prefix naming rule for custom definitions.
DIMENSION_SCOPE_PREFIXES = {"EVENT": "customEvent:", "USER": "customUser:", "ITEM": "customItem:"}
METRIC_SCOPE_PREFIXES = {"EVENT": "customEvent:"}
CALCULATED_PREFIX = "calcMetric:"

# The Data API types every dimension value as a string; DimensionMetadata
# carries no type field because none can vary (D-24).
DIMENSION_DATA_TYPE = "string"


def _description(entry: dict) -> str | None:
    return entry.get("description") or None


def _object(kind: str, schema: str, name: str, description: str | None, stats: dict) -> dict:
    return {
        "kind": kind,
        "schema": schema,
        "name": name,
        "description": description,
        "columns": [],
        "keys": {},
        "stats": stats,
    }


def _origin(custom: bool) -> str:
    return "custom" if custom else "standard"


def _admin_api_name(row: dict, prefixes: dict, what: str) -> str:
    scope = row.get("scope")
    prefix = prefixes.get(scope)
    if prefix is None:
        raise ConnectorError(
            f"unrecognized {what} scope {scope!r} for parameter "
            f"{row.get('parameterName')!r} — API surface changed beyond this connector version"
        )
    return prefix + row["parameterName"]


def build_objects(
    metadata: dict,
    custom_dimensions: list[dict],
    custom_metrics: list[dict],
    calculated_metrics: list[dict],
    key_events: list[dict],
) -> list[dict]:
    admin_dims = {
        _admin_api_name(row, DIMENSION_SCOPE_PREFIXES, "custom-dimension"): row
        for row in custom_dimensions
    }
    admin_metrics = {
        _admin_api_name(row, METRIC_SCOPE_PREFIXES, "custom-metric"): row
        for row in custom_metrics
    }
    admin_calcs = {CALCULATED_PREFIX + row["calculatedMetricId"]: row for row in calculated_metrics}

    torn: list[str] = []
    objects: list[dict] = []
    seen_dims: set[str] = set()
    seen_metrics: set[str] = set()
    seen_calcs: set[str] = set()

    for dim in metadata.get("dimensions", []):
        name = dim["apiName"]
        custom = bool(dim.get("customDefinition"))
        if custom:
            if name in admin_dims:
                seen_dims.add(name)
            else:
                torn.append(f"dimension {name} is in Data API metadata but not Admin customDimensions")
        objects.append(
            _object(
                "api_dimension",
                _origin(custom),
                name,
                _description(dim),
                {"data_type": DIMENSION_DATA_TYPE},
            )
        )

    for metric in metadata.get("metrics", []):
        name = metric["apiName"]
        custom = bool(metric.get("customDefinition"))
        stats = {"data_type": metric["type"]}
        if custom and name.startswith(CALCULATED_PREFIX):
            row = admin_calcs.get(name)
            if row is None:
                torn.append(f"metric {name} is in Data API metadata but not Admin calculatedMetrics")
            else:
                seen_calcs.add(name)
                stats["formula"] = row["formula"]
        elif custom:
            row = admin_metrics.get(name)
            if row is None:
                torn.append(f"metric {name} is in Data API metadata but not Admin customMetrics")
            else:
                seen_metrics.add(name)
                stats["scope"] = row["scope"]
        objects.append(_object("api_metric", _origin(custom), name, _description(metric), stats))

    for name in sorted(set(admin_dims) - seen_dims):
        torn.append(f"custom dimension {name} is in Admin customDimensions but not Data API metadata")
    for name in sorted(set(admin_metrics) - seen_metrics):
        torn.append(f"custom metric {name} is in Admin customMetrics but not Data API metadata")
    for name in sorted(set(admin_calcs) - seen_calcs):
        torn.append(f"calculated metric {name} is in Admin calculatedMetrics but not Data API metadata")
    if torn:
        raise SourceUnavailable(
            "GA4 surfaces disagree (torn read across non-atomic API calls; "
            "retry will re-read both): " + "; ".join(torn)
        )

    for event in key_events:
        objects.append(
            _object(
                "api_event",
                _origin(bool(event.get("custom"))),
                event["eventName"],
                None,  # key events carry no description field (D-25)
                {"is_key_event": True},
            )
        )

    return objects


def source_properties(property_resource: dict) -> dict:
    """The four documented envelope keys (MP-2, D-27), verbatim."""
    return {
        "property_id": property_resource["name"],
        "display_name": property_resource.get("displayName"),
        "time_zone": property_resource.get("timeZone"),
        "currency_code": property_resource.get("currencyCode"),
    }
