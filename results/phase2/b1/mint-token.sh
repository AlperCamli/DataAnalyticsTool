#!/bin/bash
# Mint an access token for one pilot identity, for the governed-API
# extraction steps (§4 of the runbook) and for headless skill sessions.
#
#   export CL_TOKEN=$(results/phase2/b1/mint-token.sh alper)
#   export CL_TOKEN=$(results/phase2/b1/mint-token.sh eda)
#
# Why this exists: every extraction script in results/ documents the
# password-grant recipe in a comment and leaves the operator to retype it.
# It is the same four lines every time, and typing a password on a command
# line puts it in shell history — which is exactly the class of thing
# JC-8 exists to stop.
#
# It reads the pilot's git-ignored `.secrets/idp-users.json` (JC-8) and
# prints ONLY the token, on stdout, with no newline. It never prints the
# password, and it holds no credential of its own.
#
# DEV IdP ONLY. A real customer IdP has no password grant and this script
# has no place there — the operator signs in through the browser flow.
set -euo pipefail
cd "$(dirname "$0")/../../.."

USER_NAME="${1:-}"
if [ -z "$USER_NAME" ]; then
  echo "usage: $0 <username>   (pilot identities live in .secrets/idp-users.json)" >&2
  exit 2
fi

CL_IDP="${CL_IDP:-http://127.0.0.1:8180}"
SECRETS="${CL_IDP_USERS:-.secrets/idp-users.json}"
if [ ! -f "$SECRETS" ]; then
  echo "no $SECRETS on this machine — this script is pilot-local (JC-8)" >&2
  exit 2
fi

python3 - "$USER_NAME" "$CL_IDP" "$SECRETS" <<'PY'
import json, sys, urllib.parse, urllib.request

want, idp, path = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
doc = json.load(open(path))
users = doc["users"] if isinstance(doc, dict) and "users" in doc else doc
match = [u for u in users if u.get("username") == want]
if not match:
    names = ", ".join(sorted(u.get("username", "?") for u in users))
    sys.exit(f"no identity {want!r} in {path}; known: {names}")

body = urllib.parse.urlencode({
    "grant_type": "password",
    "username": match[0]["username"],
    "password": match[0]["password"],
}).encode()
try:
    with urllib.request.urlopen(urllib.request.Request(f"{idp}/token", data=body)) as res:
        token = json.load(res)["access_token"]
except Exception as err:                                  # noqa: BLE001
    sys.exit(f"token request to {idp} failed: {err}")
sys.stdout.write(token)
PY
