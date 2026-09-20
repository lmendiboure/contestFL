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
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_root_only}"
RESULT_DIR="results/runs/${RUN_ID}"
ROOT_ONLY_ROUNDS="${ROOT_ONLY_ROUNDS:-5}"
ROOT_ONLY_WARMUP="${ROOT_ONLY_WARMUP:-1}"
ROOT_ONLY_CLIENTS="${ROOT_ONLY_CLIENTS:-10,100,500}"

fail() { echo "ERROR: $*" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || fail "Docker is required"
docker compose version >/dev/null 2>&1 || fail "Docker Compose is required"
docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable"
make tools
mkdir -p "$RESULT_DIR/raw"

cleanup() { make down >/dev/null 2>&1 || true; }
trap cleanup EXIT

run_tools_python() {
  docker run --rm --env-file .env -e MPLCONFIGDIR=/tmp/matplotlib \
    -u "$(id -u):$(id -g)" -v "$ROOT:/workspace" -w /workspace \
    "${TOOLS_IMAGE:-contestfl-eval-tools:local}" python "$@"
}

make selftest
make down || true
make network-clean || true
make bootstrap VALIDATORS=4
make up
sleep "${STARTUP_WAIT_SECONDS:-5}"
make status VALIDATORS=4
make deploy

# Fail fast on the largest configuration for both storage representations.
make benchmark VALIDATORS=4 CLIENTS=500 ROUNDS=1 WARMUP=0 \
  SCENARIOS=nominal RESULT_DIR="results/preflight/${RUN_ID}/materialized" \
  BATCH_SIZE=50 CHALLENGE_BLOCKS=2 RESPONSE_BLOCKS=4 RETRY_BUDGET=1 \
  UPDATE_DIM="${UPDATE_DIM:-1024}" SMT_DEPTH="${SMT_DEPTH:-32}" \
  TAG=root_materialized_preflight
make root-only-benchmark VALIDATORS=4 CLIENTS=500 ROOT_ONLY_ROUNDS=1 ROOT_ONLY_WARMUP=0 \
  ROOT_ONLY_WORKLOADS=clean RESULT_DIR="results/preflight/${RUN_ID}/root_only" \
  CHALLENGE_BLOCKS=2 RESPONSE_BLOCKS=4 RETRY_BUDGET=1 TAG=root_only_preflight

# Controlled comparison on clean and one client-decision dispute.
make benchmark VALIDATORS=4 CLIENTS="$ROOT_ONLY_CLIENTS" \
  ROUNDS="$ROOT_ONLY_ROUNDS" WARMUP="$ROOT_ONLY_WARMUP" \
  SCENARIOS=nominal,bad_admission,bad_aggregate RESULT_DIR="$RESULT_DIR" \
  BATCH_SIZE=50 CHALLENGE_BLOCKS=2 RESPONSE_BLOCKS=4 RETRY_BUDGET=1 \
  UPDATE_DIM="${UPDATE_DIM:-1024}" SMT_DEPTH="${SMT_DEPTH:-32}" \
  TAG=root_materialized
make root-only-benchmark VALIDATORS=4 CLIENTS="$ROOT_ONLY_CLIENTS" \
  ROOT_ONLY_ROUNDS="$ROOT_ONLY_ROUNDS" ROOT_ONLY_WARMUP="$ROOT_ONLY_WARMUP" \
  ROOT_ONLY_WORKLOADS=clean,bad_admission,bad_aggregate RESULT_DIR="$RESULT_DIR" \
  CHALLENGE_BLOCKS=2 RESPONSE_BLOCKS=4 RETRY_BUDGET=1 TAG=root_only

run_tools_python bench/analyze_root_only_ablation.py --run-dir "$RESULT_DIR"
run_tools_python bench/analyze_merkle_gas_audit.py --run-dir "$RESULT_DIR"
run_tools_python -c "import shutil; shutil.make_archive('$RESULT_DIR', 'zip', '$RESULT_DIR')"

echo "Root-only ablation complete"
echo "  Report: $RESULT_DIR/ROOT_ONLY_ABLATION_REPORT.md"
echo "  Bundle: $RESULT_DIR.zip"
