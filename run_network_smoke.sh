#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
export LANG=C

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
[[ -e .env ]] || cp .env.example .env
set -a
# shellcheck disable=SC1091
source .env
set +a
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_network_smoke}"
RESULT_DIR="results/runs/${RUN_ID}"
NETWORK_RTT_MS="${NETWORK_RTT_MS:-50}"
NETWORK_ROUNDS="${NETWORK_ROUNDS:-5}"
NETWORK_WARMUP="${NETWORK_WARMUP:-1}"
NETWORK_CLIENTS="${NETWORK_CLIENTS:-100}"
NETWORK_RESPONSE_BLOCKS="${NETWORK_RESPONSE_BLOCKS:-8}"
ACTIVE_VALIDATORS=0


fail() { echo "ERROR: $*" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || fail "Docker is required"
docker compose version >/dev/null 2>&1 || fail "Docker Compose is required"
docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable"
[[ "$NETWORK_RTT_MS" =~ ^[0-9]+$ ]] || fail "NETWORK_RTT_MS must be an integer"

make tools
mkdir -p "$RESULT_DIR/raw"

cleanup() {
  if [[ "$ACTIVE_VALIDATORS" -gt 0 ]]; then
    tools/netem.sh clear "$ACTIVE_VALIDATORS" >/dev/null 2>&1 || true
  fi
  make down >/dev/null 2>&1 || true
}
trap cleanup EXIT

run_tools_python() {
  docker run --rm --env-file .env -e MPLCONFIGDIR=/tmp/matplotlib \
    -u "$(id -u):$(id -g)" -v "$ROOT:/workspace" -w /workspace \
    "${TOOLS_IMAGE:-contestfl-eval-tools:local}" python "$@"
}

start_network() {
  local validators="$1"
  make down || true
  make network-clean || true
  make bootstrap VALIDATORS="$validators"
  make up
  ACTIVE_VALIDATORS="$validators"
  sleep "${STARTUP_WAIT_SECONDS:-5}"
  make status VALIDATORS="$validators"
  make deploy
}

run_case() {
  local validators="$1" rtt="$2" scenarios="$3" tag="$4"
  tools/netem.sh clear "$validators" >/dev/null
  if [[ "$rtt" -gt 0 ]]; then
    tools/netem.sh apply "$validators" "$rtt" 0
  fi
  sleep 2
  tools/netem.sh probe "$validators" "$rtt" "$RESULT_DIR/network_probe.csv" >/dev/null
  make status VALIDATORS="$validators"
  make benchmark \
    VALIDATORS="$validators" CLIENTS="$NETWORK_CLIENTS" \
    ROUNDS="$NETWORK_ROUNDS" WARMUP="$NETWORK_WARMUP" \
    SCENARIOS="$scenarios" RESULT_DIR="$RESULT_DIR" \
    BATCH_SIZE="${BATCH_SIZE:-50}" CHALLENGE_BLOCKS=2 \
    RESPONSE_BLOCKS="$NETWORK_RESPONSE_BLOCKS" RETRY_BUDGET=1 \
    UPDATE_DIM="${UPDATE_DIM:-1024}" SMT_DEPTH="${SMT_DEPTH:-32}" \
    FLOOD_COUNT=1 FLOOD_PARALLELISM=1 FLOOD_CHALLENGE_BLOCKS=12 \
    TAG="$tag" NETWORK_RTT_MS="$rtt"
  tools/netem.sh clear "$validators" >/dev/null
}

make selftest

# Four validators: nominal and the longest correction path.
start_network 4
tools/netem.sh preflight 4 "$NETWORK_RTT_MS"
run_case 4 0 "nominal,correction_laundering" "rtt0_v4"
run_case 4 "$NETWORK_RTT_MS" "nominal,correction_laundering" "rtt${NETWORK_RTT_MS}_v4"
make down
ACTIVE_VALIDATORS=0

# Seven validators: nominal path only, to avoid conflating committee and fault-path effects.
start_network 7
tools/netem.sh preflight 7 "$NETWORK_RTT_MS"
run_case 7 0 "nominal" "rtt0_v7"
run_case 7 "$NETWORK_RTT_MS" "nominal" "rtt${NETWORK_RTT_MS}_v7"
make down
ACTIVE_VALIDATORS=0

run_tools_python bench/analyze_network_smoke.py --run-dir "$RESULT_DIR"
run_tools_python -c "import shutil; shutil.make_archive('$RESULT_DIR', 'zip', '$RESULT_DIR')"

echo "Network smoke complete"
echo "  Report: $RESULT_DIR/NETWORK_SMOKE_REPORT.md"
echo "  Bundle: $RESULT_DIR.zip"
