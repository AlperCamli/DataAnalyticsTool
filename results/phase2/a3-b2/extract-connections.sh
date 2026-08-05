#!/bin/bash
# Extract the A-3/B-2 gate demo's evidence — through the governed APIs.
#
#   CL_TOKEN=... results/phase2/a3-b2/extract-connections.sh '<since-utc>'
#
# Like its CP-7 sibling (results/cp7-gate/extract-audit.sh), this script
# holds no database credential. It reads the same endpoints the dashboard
# reads, as the operator's own identity, so an extraction that works is
# itself a demonstration that the path works.
#
# Environment:
#   CL_API    base URL of the core (default http://127.0.0.1:8100)
#   CL_OUT    directory to write into (default: beside this script)
#   CL_TOKEN  an OIDC access token for an identity holding an ops role —
#             required, because connection reads are role-gated server-
#             side. A reporter's token is a 403 here, which is the
#             endpoint working, not this script failing.
set -euo pipefail
cd "$(dirname "$0")"

SINCE="${1:-}"
if [ -z "$SINCE" ]; then
  echo "usage: $0 <since-utc-iso8601>   e.g. $0 '2026-08-06T09:00:00Z'" >&2
  exit 2
fi

CL_API="${CL_API:-http://127.0.0.1:8100}"
PY="${CL_PYTHON:-python3}"

if [ -z "${CL_TOKEN:-}" ]; then
  cat >&2 <<'HINT'
CL_TOKEN is required (an OIDC access token for an identity with an ops role).

  Pilot dev IdP:
    export CL_TOKEN=$(curl -sS -X POST "$CL_IDP/token" \
      -d grant_type=password -d username=<ops-user> -d password=<pw> |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
HINT
  exit 2
fi

if [ -n "${CL_OUT:-}" ]; then
  mkdir -p "$CL_OUT"
  cd "$CL_OUT"
fi

export CL_API CL_TOKEN SINCE
"$PY" - "$SINCE" <<'PYTHON'
"""Render the A-3 gate evidence from the governed APIs.

Two questions this has to answer for a reviewer who was not in the room:
what did the estate look like when the demo ended, and who pressed test
on what. Both are read from stores the product already keeps — the
connection registry with its computed health, and the jobs table, whose
`triggers` array records the acting identity for every dashboard-
initiated probe.
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


def get(path, params=None):
    url = f"{API}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", "replace")
        sys.exit(f"{path} failed: HTTP {err.code} {body}")
    except urllib.error.URLError as err:
        sys.exit(f"{path} unreachable at {API}: {err.reason}")


def write(name, text):
    with open(name, "w", encoding="utf-8") as handle:
        handle.write(text)


# 1. The estate as the API serves it: every connection, its connector,
#    its credential REFERENCES (never values), and its health with the
#    reason the server computed.
listing = get("/v1/dashboard/connections")
connections = listing.get("connections", [])

lines = []
if not listing.get("policy_readable", True):
    lines.append("# sync-policy.yaml unreadable at extraction — freshness reported unknown\n")
for row in connections:
    health = row.get("health") or {}
    snapshot = health.get("snapshot") or {}
    policy = health.get("policy") or {}
    last = health.get("last_job") or {}
    refs = ",".join(c.get("ref") or "-" for c in row.get("credentials") or []) or "-"
    lines.append(
        "|".join(
            str(field)
            for field in (
                row.get("system"),
                (row.get("connector") or {}).get("name"),
                health.get("status"),
                health.get("freshness"),
                snapshot.get("age_s", "-"),
                snapshot.get("object_count", "-"),
                policy.get("threshold_s", "-"),
                policy.get("trigger_mode", "-"),
                last.get("type", "-"),
                last.get("state", "-"),
                (last.get("error") or {}).get("code", "-"),
                refs,
                health.get("reason"),
            )
        )
        + "\n"
    )
write("connections.txt", "".join(lines))
write("connections.json", json.dumps(listing, indent=2, ensure_ascii=False) + "\n")

# 2. Who pressed test on what. The job's trigger carries the acting
#    identity because the dashboard sets it from the resolved session —
#    the same rule every write inlet follows (LED-R3's shape).
jobs = get("/v1/jobs", {"type": "test_connection", "limit": "200"}).get("jobs", [])
window = [j for j in jobs if (j.get("created_at") or "") >= SINCE]

probe_lines = []
for job in sorted(window, key=lambda j: j.get("created_at") or ""):
    triggers = job.get("triggers") or []
    actor = "-"
    for trigger in triggers:
        detail = trigger.get("detail") or {}
        if detail.get("actor"):
            actor = detail["actor"]
    error = job.get("error") or {}
    # The job's own result envelope (the per-capability checks) is
    # deliberately not on this wire shape — `/v1/jobs` serves
    # `result_meta`, never `result`, because an execute job's result is
    # customer rows. What is durable here is the fact of the probe: which
    # system, when, by whom, and how it ended. The per-check detail is in
    # the response the operator saw and in the run's screenshots.
    probe_lines.append(
        "|".join(
            str(field)
            for field in (
                job.get("created_at"),
                job.get("system"),
                job.get("state"),
                actor,
                error.get("code", "-"),
                (error.get("message") or "-").replace("\n", " "),
                job.get("job_id"),
            )
        )
        + "\n"
    )
write("test-jobs.txt", "".join(probe_lines))

print("wrote:")
for name in ("connections.txt", "connections.json", "test-jobs.txt"):
    with open(name, encoding="utf-8") as handle:
        count = sum(1 for _ in handle)
    print(f"  {name:<20} {count} lines")

print()
print(f"Connections registered: {len(connections)}")
statuses = {}
for row in connections:
    key = (row.get("health") or {}).get("status", "?")
    statuses[key] = statuses.get(key, 0) + 1
for status, count in sorted(statuses.items()):
    print(f"  {status:<9} {count}")
print()
print(f"test_connection jobs in the window: {len(window)}")
failed = [j for j in window if j.get("state") != "succeeded"]
if failed:
    print(f"  {len(failed)} did not succeed — read test-jobs.txt for the codes")
    print("  (an auth_error here is the re-auth path firing, which is evidence, not a defect)")
PYTHON
