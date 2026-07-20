"""The GSC QueryExecutor (capability spec §6, API dialect — CP-6/M2).

`searchAnalytics.query` is the one documented operation (capability
§6). Unlike GA4, Search Console's schema is a fixed constant table
(D-30), so this executor *can* do the full MT-8 check locally: the
documented dimension and metric vocabulary is compiled into the
connector, and an undocumented field is refused here without a request
being made at all. That is a stronger local guarantee than the GA4
path gets, and it costs nothing — the vocabulary cannot drift because
the API has no metadata endpoint for it to drift against.

Row cap applies to pagination (QE-1): pages are pulled with
`startRow`/`rowLimit` until the cap is reached, then stopped. Quota is
terminal for interactive callers (QE-4) — the shared client raises
`QuotaExceeded` and the engine converts it.

Read-only by construction: the credentials carry only
`webmasters.readonly`.
"""

import time
from urllib.parse import quote

from connectors.gsc.api import (
    API_BASE,
    FIXED_DIMENSIONS,
    FIXED_METRICS,
    MANIFEST,
    _authorized_transport,
    _post_json,
)
from connectors.sdk import (
    ConfigError,
    ExecuteRequest,
    ExecuteResult,
    Guardrails,
    GuardrailViolation,
    Identity,
    QueryExecutor,
    QuotaPolicy,
)

DOCUMENTED_OPERATIONS = ("searchAnalytics.query",)

# The API's own ceiling for one searchAnalytics page.
MAX_PAGE_SIZE = 25_000

DOCUMENTED_METRICS = tuple(name for name, _ in FIXED_METRICS)


class GscExecutor(QueryExecutor):
    """API-dialect QueryExecutor for Search Console."""

    def __init__(self, transport_factory=None, *, sleep=time.sleep, rng=None):
        self._transport_factory = transport_factory or _authorized_transport
        self._sleep = sleep
        self._rng = rng

    def preflight(self, config: dict) -> dict:
        if not config.get("site_url"):
            raise ConfigError("gsc execution requires config.site_url")
        return {"site_url": config["site_url"]}

    def execute(
        self,
        config: dict,
        request: ExecuteRequest,
        guardrails: Guardrails,
        identity: Identity,
    ) -> ExecuteResult:
        if request.dialect != "api":
            raise ConfigError(f"gsc executes the api dialect, got {request.dialect!r}")
        if request.operation not in DOCUMENTED_OPERATIONS:
            raise GuardrailViolation(
                f"operation {request.operation!r} is not documented for gsc "
                f"(documented: {', '.join(DOCUMENTED_OPERATIONS)})",
                capability_code="schema_mismatch",
            )
        body = dict(request.body or {})

        # MT-8, locally: the fixed vocabulary is knowable here, so an
        # undocumented dimension never reaches the wire.
        undocumented = [d for d in body.get("dimensions") or [] if d not in FIXED_DIMENSIONS]
        if undocumented:
            raise GuardrailViolation(
                f"dimension(s) {', '.join(sorted(undocumented))} are not in the documented "
                f"Search Console surface (documented: {', '.join(FIXED_DIMENSIONS)})",
                capability_code="schema_mismatch",
                detail={"undocumented_dimensions": sorted(undocumented)},
            )
        if not body.get("startDate") or not body.get("endDate"):
            raise GuardrailViolation(
                "searchAnalytics.query requires startDate and endDate",
                capability_code="syntax_error",
            )

        policy = QuotaPolicy.from_rate_limit(MANIFEST.rate_limit)
        transport = self._transport_factory(config)
        url = f"{API_BASE}/sites/{quote(config['site_url'], safe='')}/searchAnalytics/query"
        dimensions = list(body.get("dimensions") or [])
        started = time.monotonic()

        rows: list[list] = []
        truncated = False
        start_row = 0
        while len(rows) < guardrails.row_cap:
            page_size = min(guardrails.row_cap - len(rows) + 1, MAX_PAGE_SIZE)
            page = _post_json(
                transport,
                url,
                {**body, "rowLimit": page_size, "startRow": start_row},
                policy,
                sleep=self._sleep,
                rng=self._rng,
            )
            page_rows = page.get("rows") or []
            for row in page_rows:
                if len(rows) >= guardrails.row_cap:
                    truncated = True
                    break
                rows.append(
                    list(row.get("keys") or [])
                    + [row.get(metric) for metric in DOCUMENTED_METRICS]
                )
            # A short page means the source has no more rows — stop
            # rather than paging into an empty response.
            if truncated or len(page_rows) < page_size:
                break
            start_row += len(page_rows)

        columns = [{"name": d, "type": "string"} for d in dimensions] + [
            {"name": name, "type": data_type} for name, data_type in FIXED_METRICS
        ]
        return ExecuteResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
            source={"executed_on": "api", "engine_version": "searchconsole-v3"},
        )
