"""Strict front-matter emission and parsing (KB §4, K-5, D-37).

Front-matter is a normative machine contract: strict YAML between `---`
fences at byte 0. Emission is a byte contract, so it is hand-rolled with
a fixed per-class key order and fixed quoting rules — `yaml.dump` style
defaults are not one (D-37). Parsing uses `yaml.safe_load` and normalizes
YAML dates back to `YYYY-MM-DD` strings so schema validation sees JSON
types only.
"""

import datetime
import json
import re
from typing import Any

import yaml

FENCE = "---\n"

# Plain (unquoted) YAML scalar: conservative charset, no leading digit
# ambiguity risks beyond what the classes emit (kinds, modes, statuses,
# system/schema/object names without specials).
_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_./-]*$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def scalar(value: Any) -> str:
    """Render one scalar with deterministic quoting.

    Dates (YYYY-MM-DD strings) stay unquoted per the §4.1 example; strings
    that are plain-safe stay plain; everything else is JSON-double-quoted
    (a valid subset of YAML double-quote escaping).
    """
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if _DATE.match(value) or _PLAIN.match(value):
        return value
    return json.dumps(value, ensure_ascii=False)


def emit(fields: list[tuple[str, Any]]) -> str:
    """Emit a front-matter block from an ordered field list.

    A value given as ``("objects", [...])`` renders as the §4.1 roster:
    one flow-mapped entry per line, `object`/`schema_hash` quoted, `kind`
    plain — matching the spec example byte-for-byte in style.
    """
    lines = [FENCE.rstrip("\n")]
    for key, value in fields:
        if key == "objects":
            lines.append("objects:")
            for entry in value:
                lines.append(
                    "  - { object: %s, kind: %s, schema_hash: %s }"
                    % (
                        json.dumps(entry["object"], ensure_ascii=False),
                        entry["kind"],
                        json.dumps(entry["schema_hash"], ensure_ascii=False),
                    )
                )
        else:
            lines.append(f"{key}: {scalar(value)}")
    lines.append(FENCE.rstrip("\n"))
    return "\n".join(lines) + "\n"


def _normalize(value: Any) -> Any:
    """yaml.safe_load types → JSON types (dates become YYYY-MM-DD strings)."""
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def split(text: str) -> tuple[dict | None, str]:
    """Split a doc into (front-matter dict | None, body).

    Returns ``(None, text)`` when there is no parseable front-matter block
    at byte 0 — callers decide whether that is a finding (KB-1) or an
    exempt file (§4.6).
    """
    if not text.startswith(FENCE):
        return None, text
    end = text.find("\n---\n", len(FENCE) - 1)
    if end == -1:
        return None, text
    raw = text[len(FENCE) : end + 1]
    body = text[end + len("\n---\n") :]
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None, text
    if not isinstance(loaded, dict):
        return None, text
    return _normalize(loaded), body
