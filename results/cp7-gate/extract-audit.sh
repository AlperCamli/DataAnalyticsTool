#!/bin/bash
# Extract the M3 gate demo's evidence — through the governed read APIs.
#
# Run on machine 1 AFTER the reporter session on machine 2 finishes:
#
#   CL_TOKEN=... results/cp7-gate/extract-audit.sh '2026-07-27T14:00:00Z'
#
# The argument is the demo's start instant (UTC) — everything the
# reporter did after it is captured. Writes five files next to this
# script; they are the committed gate evidence (B.4).
#
# Since B-0 this script is a **client of the dashboard read APIs**
# (dashboard spec §5), not of the database. The direct database path is
# gone. That matters for more than tidiness: reading the same
# endpoints the dashboard reads means the evidence is produced through
# the governed, role-filtered path, so an extraction that works is also
# a demonstration that the path works. It also means the extractor holds
# no database credential — it holds the operator's own identity, and
# sees exactly what that identity is allowed to see.
#
# Nothing here is a summary written by an agent: each file is a direct
# rendering of what the server recorded, so a reviewer can check the
# claims in the gate note against the rows rather than against prose.
#
# Environment:
#   CL_API     base URL of the core (default http://127.0.0.1:8100)
#   CL_OUT     directory to write the five files into (default: beside
#              this script). Later windows — A-2's second-human run, say
#              — extract with the same code into their own evidence
#              directory rather than a forked copy of it.
#   CL_TOKEN   an OIDC access token for a steward identity — required,
#              because §5's audit read is subject-filtered: a reporter's
#              token would return that reporter's rows only, which is
#              the point of the endpoint, not a bug in this script.
#
# If CL_TOKEN is unset, and CL_IDP/CL_USER/CL_PASSWORD are set, the
# script mints one with the IdP's password grant (the pilot's dev IdP
# supports it; a production IdP may not — mint the token however that
# IdP wants and pass CL_TOKEN).
set -euo pipefail
cd "$(dirname "$0")"

SINCE="${1:-}"
if [ -z "$SINCE" ]; then
  echo "usage: $0 <since-utc-iso8601>   e.g. $0 '2026-07-27T14:00:00Z'" >&2
  exit 2
fi

CL_API="${CL_API:-http://127.0.0.1:8100}"
# Interpreter override for environments whose python3 is not on PATH.
PY="${CL_PYTHON:-python3}"

if [ -z "${CL_TOKEN:-}" ] && [ -n "${CL_IDP:-}" ] && [ -n "${CL_USER:-}" ]; then
  CL_TOKEN="$(
    curl -sS -X POST "${CL_IDP%/}/token" \
      --data-urlencode "grant_type=password" \
      --data-urlencode "username=${CL_USER}" \
      --data-urlencode "password=${CL_PASSWORD:-}" |
      "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))'
  )"
fi

if [ -z "${CL_TOKEN:-}" ]; then
  cat >&2 <<'HINT'
CL_TOKEN is required (an OIDC access token for a steward identity).

  Pilot dev IdP:
    export CL_TOKEN=$(curl -sS -X POST "$CL_IDP/token" \
      -d grant_type=password -d username=<steward> -d password=<pw> |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

  Or let this script do it:
    CL_IDP=http://127.0.0.1:8180 CL_USER=<steward> CL_PASSWORD=<pw> \
      results/cp7-gate/extract-audit.sh '<since>'
HINT
  exit 2
fi

if [ -n "${CL_OUT:-}" ]; then
  mkdir -p "$CL_OUT"
  cd "$CL_OUT"
fi

export CL_API CL_TOKEN SINCE
"$PY" - "$SINCE" <<'PYTHON'
"""Render the gate evidence from the §5 read APIs.

Field order, separators and the `-` placeholders reproduce what the
retired SQL dumps produced, so the committed evidence and a fresh
extraction are comparable line for line. Timestamps are rendered the way
Postgres renders a timestamptz, from the microsecond-precision value the
API returns — the API does not round them, and neither does this.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ["CL_API"].rstrip("/")
TOKEN = os.environ["CL_TOKEN"]
SINCE = sys.argv[1]
PAGE = 200


def get(path, params):
    """One GET as the operator's own identity."""
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", "replace")
        sys.exit(f"{path} failed: HTTP {err.code} {body}")
    except urllib.error.URLError as err:
        sys.exit(f"{path} unreachable at {API}: {err.reason}")


def pages(path, params, key):
    """Follow the keyset cursor to the end of the result set."""
    out, cursor = [], None
    while True:
        page = dict(params, limit=PAGE)
        if cursor:
            page["cursor"] = cursor
        body = get(path, page)
        out.extend(body[key])
        cursor = body["page"]["next_cursor"]
        if not cursor:
            return out


def ts(value):
    """ISO-8601 from the API → the timestamptz rendering the SQL dump printed."""
    if not value:
        return ""
    text = value.replace("T", " ")
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")] + "+00"
    return text


def jsonb(value):
    """Postgres' jsonb text rendering: `, ` and `: ` separators, key
    order as stored (the API returns it unchanged)."""
    if value is None:
        return None
    return json.dumps(value, separators=(", ", ": "), ensure_ascii=False)


def pretty(value, indent=0):
    """`jsonb_pretty`, reproduced: four-space indent, and an empty array
    or object spread over two lines the way Postgres writes it. Matching
    it exactly is what lets a fresh extraction be diffed against the
    committed evidence rather than merely compared field by field."""
    pad = " " * indent
    inner = " " * (indent + 4)
    if isinstance(value, dict):
        if not value:
            return "{\n" + pad + "}"
        body = ",\n".join(
            f"{inner}{json.dumps(k, ensure_ascii=False)}: {pretty(v, indent + 4)}"
            for k, v in value.items()
        )
        return "{\n" + body + "\n" + pad + "}"
    if isinstance(value, list):
        if not value:
            return "[\n" + pad + "]"
        body = ",\n".join(inner + pretty(item, indent + 4) for item in value)
        return "[\n" + body + "\n" + pad + "]"
    return json.dumps(value, ensure_ascii=False)


def dash(value):
    return "-" if value in (None, "") else value


def blank(value):
    return "" if value is None else value


def line(*fields):
    return "|".join(str(f) for f in fields)


def write(name, text):
    with open(name, "w", encoding="utf-8") as handle:
        handle.write(text)


# 1. The audit chain, in order, as the MCP server wrote it (MCP §7).
#    statement_text is included deliberately: for execute/validate/publish
#    the product spec §8 stores the full text, and the demo's whole claim
#    is that what ran is what the KB grounded.
#
#    setup_stamp is the last field (D-108.4 / PA-3): which compiled
#    bundle the session presented, or `unstamped` when it presented
#    none. It is appended rather than inserted so every earlier field
#    keeps its position and a fresh extraction still diffs line-for-line
#    against evidence extracted before the column existed. A `-` here
#    means the row predates the column, which is not the same statement
#    as `unstamped` — that one is something the server observed.
audit = pages("/v1/dashboard/audit", {"since": SINCE, "order": "asc"}, "rows")

write(
    "audit-chain.txt",
    "".join(
        line(
            ts(row["ts"]),
            row["tool"],
            row["decision"],
            dash(row["decision_reason"]),
            row["subject"],
            blank(row["profile"]),
            dash(row["session_id"]),
            dash(jsonb(row["result_meta"])),
            blank(row["statement_text"]).replace("\n", " ") or "-",
            dash(row.get("setup_stamp")),
        )
        + "\n"
        for row in audit
    ),
)

# 2. Same rows as JSON, for anything that needs to parse them.
write("audit-chain.json", pretty(audit) + "\n")

# 3. Fault-ledger events raised during the demo — the flag_gap path
#    (B.3: missing_join_path must be here, not merely refused inline).
#    Ledger text arrives LED-R5-neutralized: §5.3 requires the read to
#    serve scrubbed, inert text, so this column is the governed rendering
#    rather than the raw column the retired SQL dump printed.
events = pages("/v1/dashboard/ledger/events", {"since": SINCE}, "events")

write(
    "ledger-events.txt",
    "".join(
        line(
            ts(event["ts"]),
            event["detector_class"],
            event["kind"],
            blank(event["system"]),
            dash(event["object_fqn"]),
            blank(event.get("subject")),
            dash(event["audit_ref"]),
            blank(event["description"]),
            dash(event["issue_status"]),
            dash(event["routed_to"]),
        )
        + "\n"
        for event in events
    ),
)

# 4. Publish outcomes: what was created, at which revision, for whom.
published = [row for row in audit if row["tool"] == "publish_report"]
write("publish-results.json", pretty(published) + "\n")

# 5. The two-call publish trail (amended gate, Act 4): per report, the
#    deliver_model/attest pair from audit plus the server's permanent
#    delivery and attestation records. A delivery row with no matching
#    attestation row is the DANGLING state — loud by design.
trail = [
    line(
        ts(row["ts"]),
        blank((row["result_meta"] or {}).get("artifact_id")),
        blank((row["result_meta"] or {}).get("mode")),
        row["decision"],
        dash((row["result_meta"] or {}).get("error")),
        dash((row["result_meta"] or {}).get("dataset_id")),
    )
    + "\n"
    for row in published
]

# The delivery records are the estate's current state, not a window:
# the retired dump listed every row, and so does this.
deliveries = pages("/v1/dashboard/deliveries", {}, "rows")
by_delivery = sorted(deliveries, key=lambda r: r["delivery"]["delivered_at"])

trail.append("-- model_deliveries --\n")
trail += [
    line(
        row["artifact_id"],
        row["target"],
        row["delivery"]["revision"],
        row["delivery"]["workspace_id"],
        row["delivery"]["dataset_id"],
        ts(row["delivery"]["delivered_at"]),
    )
    + "\n"
    for row in by_delivery
]

attestations = sorted(
    (
        (row, attestation)
        for row in deliveries
        for attestation in row["attestations"]
    ),
    key=lambda pair: pair[1]["attested_at"],
)
trail.append("-- report_attestations --\n")
trail += [
    line(
        row["artifact_id"],
        row["target"],
        attestation["revision"],
        attestation["report_id"],
        attestation["definition_hash"],
        ts(attestation["verified_at"]),
        ts(attestation["attested_at"]),
    )
    + "\n"
    for row, attestation in attestations
]

trail.append("-- dangling (deliveries whose revision has no attestation) --\n")
trail += [
    line(row["artifact_id"], row["target"], row["delivery"]["revision"], row["delivery"]["dataset_id"])
    + "\n"
    for row in by_delivery
    if row["dangling"]
]

write("publish-trail.txt", "".join(trail))

print("wrote:")
for name in (
    "audit-chain.txt",
    "audit-chain.json",
    "ledger-events.txt",
    "publish-results.json",
    "publish-trail.txt",
):
    with open(name, encoding="utf-8") as handle:
        count = sum(1 for _ in handle)
    print(f"  {name:<22} {count} lines")

denied = sum(1 for row in audit if row["decision"] == "denied")
modes = sum(
    1
    for row in published
    if (row["result_meta"] or {}).get("mode") in ("deliver_model", "attest")
)
print()
print("Denials in the window (expect the two Act-3 cases):")
print(f"  {denied}" if denied else "  none — Act-3 evidence is missing")
print("publish_report mode calls in the window (expect deliver_model+attest per report):")
print(f"  {modes}")

# PA-3: which compiled setups produced this window. One line, because a
# gate note that says "the session ran a current bundle" should be able
# to cite a column rather than an inference from timestamps.
stamps = {}
for row in audit:
    stamps[row.get("setup_stamp") or "(pre-PA-3 row: no column)"] = (
        stamps.get(row.get("setup_stamp") or "(pre-PA-3 row: no column)", 0) + 1
    )
print()
print("Setup stamps presented in the window (D-108.4):")
for stamp, count in sorted(stamps.items(), key=lambda kv: (-kv[1], kv[0])):
    print(f"  {stamp:<34} {count} row(s)")
PYTHON
