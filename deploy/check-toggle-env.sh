#!/bin/sh
# Guard: a feature toggle exported into the shell is a silent no-op
# (D-110.2), so say so loudly instead of starting a stack that ignores it.
#
# Since the toggles left `environment:`, compose no longer interpolates
# them from the shell — `CORE_MCP_ENABLED=1 docker compose up` reads as an
# instruction and behaves as nothing. That is the very failure mode this
# ruling exists to end, so it must not be reintroduced by habit. The old
# habit is three checkpoints deep (D-84.2, D-109.8), which is why this
# check errors rather than warns.
#
# Exit 0 when clean; exit 1 naming every toggle it found and where to
# put it instead. Names only — this never prints a value.
set -eu

# The canonical toggle set. Every name here must have a default in
# deploy/core.defaults.env and appear in no compose `environment:` block —
# both asserted by tests/test_compose_env_passthrough.py, so this list and
# the compose files cannot drift apart quietly.
TOGGLES="CORE_MCP_ENABLED CORE_DASHBOARD_ENABLED SYNC_ENABLED CORE_MIGRATE_ON_START"

found=""
for name in $TOGGLES; do
  eval "value=\${$name-__unset__}"
  [ "$value" = "__unset__" ] || found="$found $name"
done

[ -n "$found" ] || exit 0

echo "refusing to start: feature toggle(s) set in the shell:$found" >&2
cat >&2 <<'HINT'

Compose does not read these from the shell any more (D-110.2). They are
set in env files, in list order, later wins:

  deploy/core.defaults.env      base stack, everything off
  deploy/core.live.env          live/mcp overlays: MCP + dashboard on
  .secrets/sync.env             this pilot's own values
  deploy/baseline/*.env         the three baseline conditions

Arming a surface for a one-off run is an overlay, not an export:

  docker compose -f docker-compose.yml -f deploy/compose.mcp.yml up -d --build

Then check what the process actually resolved, which is the only answer
that counts:

  curl -sS http://127.0.0.1:8100/healthz | python3 -m json.tool
HINT
exit 1
