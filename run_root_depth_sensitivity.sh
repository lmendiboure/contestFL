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

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_root_depth}"
RESULT_DIR="results/runs/${RUN_ID}"
ROOT_DEPTHS="${ROOT_DEPTHS:-32 64 128 256}"
ROOT_DEPTH_ROUNDS="${ROOT_DEPTH_ROUNDS:-3}"
ROOT_DEPTH_WARMUP="${ROOT_DEPTH_WARMUP:-1}"
ROOT_DEPTH_CLIENTS="${ROOT_DEPTH_CLIENTS:-500}"

command -v docker >/dev/null 2>&1 || { echo "Docker is required" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose is required" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is unavailable" >&2; exit 1; }

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

for depth in $ROOT_DEPTHS; do
  echo "=== Root-only challenged path at sparse-Merkle depth ${depth} ==="
  make root-only-benchmark \
    VALIDATORS=4 CLIENTS="$ROOT_DEPTH_CLIENTS" \
    ROOT_ONLY_ROUNDS="$ROOT_DEPTH_ROUNDS" ROOT_ONLY_WARMUP="$ROOT_DEPTH_WARMUP" \
    ROOT_ONLY_WORKLOADS=bad_admission RESULT_DIR="$RESULT_DIR" \
    SMT_DEPTH="$depth" CHALLENGE_BLOCKS=2 RESPONSE_BLOCKS=4 RETRY_BUDGET=1 \
    TAG="depth_d${depth}"
done

run_tools_python bench/analyze_root_depth_sensitivity.py --run-dir "$RESULT_DIR"
run_tools_python -c "import shutil; shutil.make_archive('$RESULT_DIR', 'zip', '$RESULT_DIR')"

echo "Sparse-Merkle depth sensitivity complete"
echo "  Report: $RESULT_DIR/ROOT_DEPTH_SENSITIVITY_REPORT.md"
echo "  Bundle: $RESULT_DIR.zip"
