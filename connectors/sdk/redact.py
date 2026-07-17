"""Runner-side secret scrub (job spec §7, security review #1 F3 / D-66
point 2).

A connector exception can echo a resolved credential — a driver whose
error message includes the DSN, a traceback line carrying it. This module
scrubs exception messages and tracebacks by pattern *before* they are
placed into a ``JobError`` (runner.py), so no resolved secret travels the
`fail` wire call into `jobs.error` / `health_events.detail`. The core runs
the same pass again as defense in depth (core/src/redact.ts).

Pattern-based, not value-based: connection URIs with userinfo
(``postgres://user:pass@host/db``), libpq keyword secrets (``password=…``),
and bearer tokens. A match collapses to a fixed marker.
"""

import re
from typing import Any

REDACTION_MARKER = "[redacted:credential]"

_CREDENTIAL_URI = re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s/@]+@\S+", re.IGNORECASE)
_KEYWORD_SECRET = re.compile(
    r"\b(password|passwd|pwd|secret|token|api[_-]?key)\s*=\s*(\"[^\"]*\"|'[^']*'|\S+)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)


def redact_text(value: str) -> str:
    """Redact credential-shaped substrings in one string (no-op when none)."""
    value = _CREDENTIAL_URI.sub(REDACTION_MARKER, value)
    value = _KEYWORD_SECRET.sub(lambda m: f"{m.group(1)}={REDACTION_MARKER}", value)
    value = _BEARER.sub(REDACTION_MARKER, value)
    return value


def redact_deep(value: Any) -> Any:
    """Recursively redact every string in a JSON-ish value; structure kept."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_deep(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_deep(v) for v in value)
    if isinstance(value, dict):
        return {k: redact_deep(v) for k, v in value.items()}
    return value
