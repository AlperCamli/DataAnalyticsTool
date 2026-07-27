"""QE-5 result value encoding (capability spec §6, ruling D-85).

`rows` in an `execute` result carry JSON values only. This module holds
the one normative mapping every QueryExecutor obeys — not one engine's
idea of it — so a `date` from Postgres and a `date` from a future engine
reach the agent as the same shape.

Two rules do the work:

* **Fidelity over convenience.** `numeric` becomes a string, never a
  float: a float would silently change the fact, and the platform's whole
  claim is that it hands over what the source said (the execute-path
  cousin of the snapshot layer's S-8). Integers beyond JSON's safe range
  take the same treatment for the same reason.
* **Never dropped, never a crash.** Anything without a listed mapping is
  rendered as text rather than discarded or allowed to raise. Before
  D-85 an unmapped value did not degrade — it killed the runner process
  (a `date` reaching `json.dumps`), and the emptiness RLS imposed on the
  pilot was the only reason that went unnoticed for two checkpoints.

`columns[].type` still carries the source-native type name, so a
consumer always knows what a given string encodes.
"""

import base64
import datetime
import decimal
import math
import uuid

# Beyond this, IEEE-754 doubles (what a JSON consumer parses into) can no
# longer represent every integer exactly, so we hand over text instead.
JSON_SAFE_INT_MAX = 2**53 - 1


def json_value(value):
    """Encode one source value per QE-5.

    Idempotent on already-encoded values, so applying it twice — in an
    executor and again at the result boundary — is safe.

    Engine-specific text rendering (Postgres writing an array as `{a,b}`,
    say) belongs in the connector, which knows the column's type; it
    encodes those values before they reach here. What arrives here
    unrecognised is rendered with `str`, which for a driver's scalar
    objects is the source's own rendering.
    """
    if value is None or isinstance(value, (str, bool)):
        return value

    if isinstance(value, int):  # bool is handled above
        return value if abs(value) <= JSON_SAFE_INT_MAX else str(value)

    if isinstance(value, float):
        # NaN/Infinity have no JSON literal; `json.dumps` would emit
        # tokens no strict parser (the core's JSON.parse included) will
        # read back. Text keeps the value and keeps the result valid.
        return value if math.isfinite(value) else str(value)

    if isinstance(value, decimal.Decimal):
        return str(value)

    if isinstance(value, datetime.datetime):
        # RFC3339; the offset is preserved exactly as the source returned
        # it — naive stays naive, we do not invent a timezone.
        return value.isoformat()

    if isinstance(value, datetime.date):  # after datetime: date is its base
        return value.isoformat()

    if isinstance(value, datetime.time):
        return value.isoformat()

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")

    if isinstance(value, dict):  # json/jsonb: pass through as native JSON
        return {str(k): json_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        # Reached only when a connector did not classify the column (the
        # boundary net). Recursing keeps every element rather than
        # stringifying the container — never dropped, never a crash.
        return [json_value(v) for v in value]

    return str(value)


def json_row(row):
    return [json_value(v) for v in row]
