#!/bin/bash
# JC-4 verification per D-96.3f: three consecutive FULL core-suite runs
# UNDER DELIBERATE LOAD. The point is to reproduce the contention that
# expired a live lease, not to avoid it — a green run on an idle machine
# proves nothing about this flake.
#
# Load generator: a --no-cache docker build of the core image looping
# beside the suite, plus a CPU saturation ring sized to the box.
set -uo pipefail
cd $HOME/Desktop/DataProject

OUT=/private/tmp/claude-501/-Users-alpercamli-Desktop-DataProject/fe26579c-8838-4335-b721-07a3ef758059/scratchpad
CORES=$(sysctl -n hw.ncpu)
echo "host cores: $CORES"

# --- load: looping no-cache docker build -------------------------------
( while :; do
    docker build --no-cache -f core/Dockerfile -t cl-loadgen:scratch core \
      >> "$OUT/loadgen-docker.log" 2>&1
  done ) &
LOAD_DOCKER=$!

# --- load: CPU ring, cores-1 spinners ----------------------------------
SPINNERS=()
for _ in $(seq 1 $((CORES - 1))); do
  ( while :; do :; done ) &
  SPINNERS+=($!)
done

cleanup() {
  kill $LOAD_DOCKER 2>/dev/null
  pkill -P $LOAD_DOCKER 2>/dev/null
  for p in "${SPINNERS[@]}"; do kill $p 2>/dev/null; done
}
trap cleanup EXIT

sleep 20   # let the load spin up before the first run

PASS=0
for RUN in 1 2 3; do
  echo "=== run $RUN starting $(date -u +%FT%TZ) ==="
  ( cd core && npx vitest run --no-file-parallelism ) \
    > "$OUT/jc4-run-$RUN.log" 2>&1
  CODE=$?
  echo "=== run $RUN exit=$CODE $(date -u +%FT%TZ) ==="
  tail -20 "$OUT/jc4-run-$RUN.log"
  if [ $CODE -eq 0 ]; then PASS=$((PASS + 1)); else
    echo "RUN $RUN FAILED — full output kept at $OUT/jc4-run-$RUN.log"
  fi
done

echo "==== JC-4 VERIFICATION: $PASS/3 green under load ===="
