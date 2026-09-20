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
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_smt_offchain}"
RESULT_DIR="results/runs/${RUN_ID}"
SMT_OFFCHAIN_CLIENTS="${SMT_OFFCHAIN_CLIENTS:-10,100,500}"
SMT_OFFCHAIN_REPETITIONS="${SMT_OFFCHAIN_REPETITIONS:-30}"
SMT_OFFCHAIN_WARMUP="${SMT_OFFCHAIN_WARMUP:-5}"
SMT_DEPTH="${SMT_DEPTH:-32}"

make tools
mkdir -p "$RESULT_DIR"
docker run --rm --env-file .env \
  -u "$(id -u):$(id -g)" -v "$ROOT:/workspace" -w /workspace \
  "${TOOLS_IMAGE:-contestfl-eval-tools:local}" \
  python bench/benchmark_smt_offchain.py \
    --clients "$SMT_OFFCHAIN_CLIENTS" \
    --depth "$SMT_DEPTH" \
    --repetitions "$SMT_OFFCHAIN_REPETITIONS" \
    --warmup "$SMT_OFFCHAIN_WARMUP" \
    --output-dir "$RESULT_DIR"

docker run --rm --env-file .env \
  -u "$(id -u):$(id -g)" -v "$ROOT:/workspace" -w /workspace \
  "${TOOLS_IMAGE:-contestfl-eval-tools:local}" \
  python -c "import shutil; shutil.make_archive('$RESULT_DIR', 'zip', '$RESULT_DIR')"

echo "Off-chain SMT microbenchmark complete"
echo "  Report: $RESULT_DIR/SMT_OFFCHAIN_REPORT.md"
echo "  Bundle: $RESULT_DIR.zip"
