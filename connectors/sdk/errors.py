"""Connector-side exception taxonomy (job spec §6.7).

Connectors raise these from `introspect`; the runner maps them to the
protocol's `error.code` / `retryable` semantics. A bare exception maps
to `internal` (retryable — remotely it would surface via `fail` or
lease expiry). `QuotaExceeded` is not a failure at all: it maps to a
deferral (J-5) so quota exhaustion never consumes a retry attempt.

Messages and details must never contain secret material (J-4/JC-8);
credential handling stays reference-only on this side of the boundary.
"""


class ConnectorError(Exception):
    """Base taxonomy error. Subclasses pin `code` and `retryable`."""

    code = "internal"
    retryable = True

    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


class ConfigError(ConnectorError):
    """Invalid source config or unsupported mode — non-retryable."""

    code = "config_error"
    retryable = False


class AuthError(ConnectorError):
    """Credential invalid/expired at source or vault — triggers re-auth."""

    code = "auth_error"
    retryable = False


class SourceUnavailable(ConnectorError):
    """Network/source down/replica lag — retried with backoff."""

    code = "source_unavailable"
    retryable = True


class Cancelled(ConnectorError):
    """Producer cancellation acknowledged by the connector."""

    code = "cancelled"
    retryable = False


class QuotaExceeded(ConnectorError):
    """API quota/rate ceiling — a deferral (J-5), never a failure."""

    code = "quota"

    def __init__(self, message: str, *, retry_after_s: int, detail: dict | None = None):
        super().__init__(message, detail=detail)
        self.retry_after_s = retry_after_s


class EmissionError(ConnectorError):
    """Snapshot rejected by the pre-delivery gate (J-6 connector-side).

    Downstream this would dead-letter as `validation_error`; failing
    loudly here keeps the contract enforcement at the producer.
    """

    code = "validation_error"
    retryable = False

    def __init__(self, problems: list[str]):
        joined = "\n  ".join(problems)
        super().__init__(
            f"snapshot failed pre-delivery validation:\n  {joined}",
            detail={"errors": problems},
        )
        self.problems = problems
