"""The GA4 QueryExecutor (capability spec §6, API dialect — CP-6/M2).

The API dialect's guardrails differ in kind from SQL's. There is no
statement to parse and no database role to hide behind: the surface is
whatever the Data API will answer. So the enforcement here is:

- **Operation allowlist.** Only `runReport` is documented for this
  connector (capability §6). Anything else is refused locally before a
  request is made — an undocumented operation is not a thing the
  gateway forgot to check, it is a thing this connector does not do.
- **Field surface (MT-8).** The gateway validates dimensions and
  metrics against the KB's documented surface. The executor cannot
  re-run that check (it holds no snapshot), so it does the honest
  second layer instead: GA4's own rejection of an unknown field is
  mapped to `schema_mismatch` rather than surfacing as an opaque 400.
  Between the two, an undocumented dimension is refused at the gateway
  and, if that were bypassed, refused by the source.
- **Row cap during pagination (QE-1).** Pages are pulled until the cap
  is reached and then stopped — the cap bounds the requests made, not
  just the rows returned.
- **Quota is terminal (QE-4).** `QuotaExceeded` from the shared client
  propagates; the engine converts it to a `guardrail` /
  `quota_exhausted` error with the retry-after, never a J-5 deferral,
  because an interactive caller is blocked on this result.

Read-only by construction: the connector's credentials carry only
`analytics.readonly`, so there is no write surface to guard (the SQL
executor's G3 role wall has no analogue here — the scope is the wall).
"""

import time

from connectors.ga4.api import DATA_API, MANIFEST, _authorized_transport
from connectors.ga4.client import GA4Client
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

# capability §6: "GA4: runReport". Growth is additive and deliberate.
DOCUMENTED_OPERATIONS = ("runReport",)

# The Data API caps a single request at 100k rows; we page under that.
MAX_PAGE_SIZE = 100_000


class GA4Executor(QueryExecutor):
    """API-dialect QueryExecutor for GA4."""

    def __init__(self, transport_factory=None, *, sleep=time.sleep, rng=None):
        self._transport_factory = transport_factory or _authorized_transport
        self._sleep = sleep
        self._rng = rng

    def preflight(self, config: dict) -> dict:
        """No role wall to check (the OAuth scope is read-only), but the
        property must be configured — fail at startup, not first query."""
        if not config.get("property_id"):
            raise ConfigError("ga4 execution requires config.property_id")
        return {"property_id": config["property_id"]}

    def execute(
        self,
        config: dict,
        request: ExecuteRequest,
        guardrails: Guardrails,
        identity: Identity,
    ) -> ExecuteResult:
        if request.dialect != "api":
            raise ConfigError(f"ga4 executes the api dialect, got {request.dialect!r}")
        if request.operation not in DOCUMENTED_OPERATIONS:
            raise GuardrailViolation(
                f"operation {request.operation!r} is not documented for ga4 "
                f"(documented: {', '.join(DOCUMENTED_OPERATIONS)})",
                capability_code="schema_mismatch",
            )
        body = dict(request.body or {})
        if not body.get("metrics") and not body.get("dimensions"):
            raise GuardrailViolation(
                "runReport requires at least one dimension or metric",
                capability_code="syntax_error",
            )

        client = GA4Client(
            self._transport_factory(config),
            QuotaPolicy.from_rate_limit(MANIFEST.rate_limit),
            sleep=self._sleep,
            rng=self._rng,
        )
        url = f"{DATA_API}/v1beta/properties/{config['property_id']}:runReport"
        started = time.monotonic()

        rows: list[list] = []
        truncated = False
        columns: list[dict] = []
        offset = 0
        while len(rows) < guardrails.row_cap:
            page_size = min(guardrails.row_cap - len(rows) + 1, MAX_PAGE_SIZE)
            page = self._run_report(client, url, {**body, "limit": page_size, "offset": offset})
            if not columns:
                columns = _columns(page)
            page_rows = _rows(page)
            for row in page_rows:
                if len(rows) >= guardrails.row_cap:
                    truncated = True
                    break
                rows.append(row)
            # A short page means the source has no more rows — stop
            # rather than paging into an empty response.
            if truncated or len(page_rows) < page_size:
                break
            offset += len(page_rows)
            total = page.get("rowCount")
            if isinstance(total, int) and offset >= total:
                break

        return ExecuteResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
            source={"executed_on": "api", "engine_version": "ga4-data-v1beta"},
        )

    @staticmethod
    def _run_report(client: GA4Client, url: str, body: dict) -> dict:
        try:
            return client.post_json(url, body)
        except ConfigError as exc:
            # The client maps 400/404 to ConfigError. For an interactive
            # execute, a rejected field is the validate/execute race, not
            # a misconfigured connector — reclassify so the caller gets an
            # actionable answer and the ledger gets its class-1 signal.
            raise GuardrailViolation(
                f"GA4 rejected the request (an undocumented or unavailable "
                f"dimension/metric, or an invalid date range): {exc}",
                capability_code="schema_mismatch",
            ) from exc


def _columns(page: dict) -> list[dict]:
    return [
        {"name": header.get("name", ""), "type": "string"}
        for header in page.get("dimensionHeaders", [])
    ] + [
        {"name": header.get("name", ""), "type": header.get("type", "metric")}
        for header in page.get("metricHeaders", [])
    ]


def _rows(page: dict) -> list[list]:
    out: list[list] = []
    for row in page.get("rows", []):
        values = [v.get("value") for v in row.get("dimensionValues", [])]
        values += [v.get("value") for v in row.get("metricValues", [])]
        out.append(values)
    return out
