#!/bin/bash
# Flip a connection's credential references from env:// to vault://,
# through the governed API (A-4, act 6).
#
#   CL_TOKEN=... results/phase2/a4/flip-references.sh                 # dry run, all
#   CL_TOKEN=... results/phase2/a4/flip-references.sh --apply supabase
#
# WHY A SCRIPT AND NOT THE BROWSER. The B-2 Connections module can add,
# test and remove a connection, but has no *edit* affordance: changing one
# reference means re-submitting the add form with the whole config JSON
# retyped from memory, because the card does not show config either. On a
# five-connection estate that is five chances to silently drop a config
# key. So the migration uses this instead — a client of the same governed
# API the module uses, doing a read-modify-write so nothing but the
# references changes. The gap itself is a finding, filed rather than
# worked around quietly: see results/phase2/a4/FINDINGS.md.
#
# Holds no database credential and prints no secret value: it moves
# *references*, which is the whole point of the product it is migrating.
#
# Environment:
#   CL_API    base URL of the core (default http://127.0.0.1:8100)
#   CL_TOKEN  an OIDC access token for an identity holding an `ops` role
#             (connection writes are ops-gated server-side; a steward
#             token is a 403 here, which is the endpoint working)
set -euo pipefail
cd "$(dirname "$0")"

APPLY=0
SYSTEMS=()
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) SYSTEMS+=("$arg") ;;
  esac
done

if [ -z "${CL_TOKEN:-}" ]; then
  echo "CL_TOKEN is required (an OIDC access token for an ops identity)" >&2
  exit 2
fi

CL_API="${CL_API:-http://127.0.0.1:8100}"
export CL_API CL_TOKEN APPLY
SYSTEMS_CSV=$(IFS=,; echo "${SYSTEMS[*]:-}")
export SYSTEMS_CSV

"${CL_PYTHON:-python3}" - <<'PYTHON'
"""Read each connection, rewrite its env:// refs to vault://, PUT it back.

The mapping below is the pilot's, stated once here so the runbook's table
and this script cannot disagree. Everything else is generic.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ["CL_API"].rstrip("/")
TOKEN = os.environ["CL_TOKEN"]
APPLY = os.environ["APPLY"] == "1"
ONLY = [s for s in os.environ.get("SYSTEMS_CSV", "").split(",") if s]

# env:// reference  ->  vault:// reference. The pilot's five, per the
# secrets seeded in act 4. `ga4` and `gsc` share one Google service-account
# key, so both map to the same secret — one credential in Google's eyes
# rotates once, not twice.
MAPPING = {
    "env://CL_INTROSPECT_DSN": "vault://secret/contextlayer/connections/supabase#introspect_dsn",
    "env://CL_EXEC_DSN": "vault://secret/contextlayer/connections/supabase#exec_dsn",
    "env://GOOGLE_SA_KEY_JSON": "vault://secret/contextlayer/connections/google#sa_key_json",
    "env://POWERBI_CLIENT_SECRET": "vault://secret/contextlayer/connections/powerbi#client_secret",
}


def call(path, method="GET", body=None):
    request = urllib.request.Request(
        f"{API}{path}",
        method=method,
        headers={"authorization": f"Bearer {TOKEN}", "content-type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(request) as response:
            text = response.read().decode()
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as err:
        sys.exit(f"{method} {path} failed: HTTP {err.code} {err.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as err:
        sys.exit(f"{path} unreachable at {API}: {err.reason}")


listing = call("/v1/dashboard/connections")
changed = skipped = 0

for row in listing.get("connections", []):
    system = row.get("system")
    if ONLY and system not in ONLY:
        continue

    detail = call(f"/v1/dashboard/connections/{urllib.parse.quote(system)}")
    conn = detail.get("connection", detail)
    credentials = conn.get("credentials") or []

    updated, moves = [], []
    for cred in credentials:
        ref = cred.get("ref")
        new = MAPPING.get(ref)
        entry = dict(cred)
        if new:
            entry["ref"] = new
            moves.append(f"      {cred.get('key')}: {ref}  ->  {new}")
        updated.append({k: v for k, v in entry.items() if k in ("key", "ref", "required_for")})

    if not moves:
        state = "already on vault://" if any(
            str(c.get("ref", "")).startswith("vault://") for c in credentials
        ) else "no credential to move"
        print(f"  {system:<15} — {state}")
        skipped += 1
        continue

    print(f"  {system:<15} {len(moves)} reference(s):")
    print("\n".join(moves))

    if not APPLY:
        continue

    # Read-modify-write: config and connector are carried through
    # untouched, so the only difference on the wire is the references.
    result = call(
        f"/v1/dashboard/connections/{urllib.parse.quote(system)}",
        method="PUT",
        body={
            "connector": conn.get("connector"),
            "payload": {"config": conn.get("config") or {}, "credentials": updated},
        },
    )
    # A-3's read-back: what the server answers is what the store now
    # holds, not an echo of the request (D-109.1). Verify it took.
    stored = [c.get("ref") for c in (result.get("connection") or {}).get("credentials") or []]
    expected = [c["ref"] for c in updated]
    if stored != expected:
        sys.exit(f"{system}: the store did not take the change — holds {stored}")
    print(f"      applied, read back: {', '.join(stored)}")
    changed += 1

print()
if APPLY:
    print(f"{changed} connection(s) flipped, {skipped} needed no change.")
    print("Now press Test on each in the dashboard — a reference that resolves")
    print("is the only proof that counts.")
else:
    print(f"DRY RUN — nothing was written. {skipped} needed no change.")
    print("Re-run with --apply once the mapping above looks right.")
PYTHON
