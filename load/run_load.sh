#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ARP local k6 load proof — orchestrates the full $0 experiment end to end.
#
#   1. Build the load image (shipped backend-dev + the redis extra).
#   2. Bring up Redis + 1 ARP replica, run the scale/throughput scenario.
#   3. Scale to N replicas (default 3), re-run the SAME scenario.
#   4. Run the Redis-CAS consistency scenario at N replicas.
#   5. Run the Redis-CAS probe (live exact-sum CAS proof + key snapshot).
#   6. Snapshot each replica's /api/health/ready (proves shared Redis).
#   7. Tear the stack down.
#
# All k6 JSON summaries + the probe JSON land in load/results/ and are the ONLY
# data source for the Pages report (scripts/build_load_report.py). No metric is
# hand-typed.
#
# Usage:   bash load/run_load.sh [N_REPLICAS]
# Env:     KEEP_UP=1 to skip teardown for debugging.
# ---------------------------------------------------------------------------
set -euo pipefail

# On Git Bash / MSYS2 (Windows), a leading-slash argument like /workspace/... is
# rewritten to a host path before it reaches the container. We do NOT disable
# this globally (host-path args such as the build context and -v sources DO need
# conversion); instead the few in-container paths are protected at the call site
# with a leading "//" (the runner detects MSYS and doubles the slash).
case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*) IN_CTR="/" ;;  # double-slash guard prefix on Windows
  *) IN_CTR="" ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
COMPOSE="docker compose -f $HERE/docker-compose.load.yml"
RESULTS="$HERE/results"
K6_IMAGE="grafana/k6:latest"
N_REPLICAS="${1:-3}"

# k6 needs the scripts + a writable results dir mounted in. We run the
# grafana/k6 image attached to the load network so BASE_URL=http://lb:80 works.
NETWORK="arp-load_loadnet"

mkdir -p "$RESULTS"

run_k6() {
  # $1 = script basename, $2 = output json basename, $3.. = extra -e env.
  # k6 exits non-zero on a threshold breach; we capture the JSON regardless and
  # keep going (set -e must not abort the sweep on a soft threshold miss).
  local script="$1"; shift
  local out="$1"; shift
  echo ">>> k6: $script -> results/$out"
  docker run --rm \
    --network "$NETWORK" \
    -v "$HERE/k6:/scripts:ro" \
    -v "$RESULTS:/results" \
    "$@" \
    "$K6_IMAGE" run \
      --summary-export "/results/$out" \
      "/scripts/$script" \
  && echo ">>> k6 $script OK" \
  || echo "!!! k6 $script returned non-zero (threshold breach or error) — JSON still captured"
}

wait_for_lb() {
  # Poll the lb with a lightweight curl container (alpine/curl). Avoids spinning
  # a k6 container per attempt and avoids heredoc/pipefail fragility.
  echo ">>> waiting for lb -> backend to answer /api/health"
  local i
  for i in $(seq 1 60); do
    if docker run --rm --network "$NETWORK" curlimages/curl:latest \
        -fsS -m 3 http://lb:80/api/health >/dev/null 2>&1; then
      echo ">>> lb is serving"
      return 0
    fi
    sleep 2
  done
  echo "!!! lb never became ready"
  return 1
}

snapshot_health() {
  # $1 = output basename. Hits /api/health/ready via the lb (round-robins across
  # replicas) a few times and stores the raw responses — evidence the replicas
  # share the same Redis dependency.
  local out="$1"
  echo ">>> snapshotting /api/health/ready -> results/$out"
  docker run --rm --network "$NETWORK" \
    -v "$RESULTS:/results" \
    --entrypoint sh "$K6_IMAGE" -c '
      for i in 1 2 3 4 5; do
        wget -q -O - http://lb:80/api/health/ready || true
        echo
      done
    ' > "$RESULTS/$out" 2>/dev/null || echo "!!! health snapshot failed (non-fatal)"
}

echo "=== [1/7] Build load image ==="
# Build the repo dev image first (the load image FROM-references it by tag),
# then the load image via compose.
docker build -f "$ROOT/Dockerfile" --target backend-dev -t agentic-runtime-platform:backend-dev "$ROOT"
$COMPOSE build

echo "=== [2/7] Up: Redis + 1 replica ==="
$COMPOSE up -d --scale backend=1
wait_for_lb
sleep 3  # let the single replica settle
run_k6 "scale_throughput.js" "scale_1replica.json" -e REPLICAS=1 -e BASE_URL=http://lb:80

echo "=== [3/7] Scale to $N_REPLICAS replicas, re-run scale scenario ==="
$COMPOSE up -d --scale backend="$N_REPLICAS"
wait_for_lb
sleep 5  # let new replicas register in DNS + settle
run_k6 "scale_throughput.js" "scale_${N_REPLICAS}replica.json" -e REPLICAS="$N_REPLICAS" -e BASE_URL=http://lb:80

echo "=== [4/7] Redis-CAS consistency scenario at $N_REPLICAS replicas ==="
run_k6 "redis_cas_consistency.js" "redis_cas_run.json" -e REPLICAS="$N_REPLICAS" -e BASE_URL=http://lb:80 -e TARGET_RUNS=600 -e ARRIVAL_RATE=60
sleep 4  # let the fire-and-forget CAS save tasks drain into Redis

echo "=== [5/7] Redis-CAS probe (live exact-sum proof + key snapshot) ==="
$COMPOSE run --rm --no-deps \
  -v "$RESULTS:/results" \
  -e CAS_RESULT_PATH=/results/cas_consistency.json \
  -e CAS_TORTURE_WORKERS=4 \
  -e CAS_TORTURE_FAILURES=50 \
  --entrypoint python \
  backend "${IN_CTR}/workspace/load/probe_redis_cas.py" || echo "!!! probe returned non-zero (see cas_consistency.json)"

echo "=== [6/7] Health snapshot (shared-Redis evidence) ==="
snapshot_health "health_ready.txt"

echo "=== [7/7] Teardown ==="
if [ "${KEEP_UP:-0}" = "1" ]; then
  echo ">>> KEEP_UP=1 set — leaving stack running. Tear down later with:"
  echo "    $COMPOSE down -v"
else
  $COMPOSE down -v
fi

echo "=== Done. Results in load/results/ ==="
ls -la "$RESULTS"
