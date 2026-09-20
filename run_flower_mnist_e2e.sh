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
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_flower_mnist}"
RESULT_DIR="results/runs/${RUN_ID}"
FLOWER_IMAGE="${FLOWER_IMAGE:-contestfl-flower-mnist:local}"
FLOWER_CLIENTS="${FLOWER_CLIENTS:-2}"
FLOWER_SAMPLES_PER_CLIENT="${FLOWER_SAMPLES_PER_CLIENT:-512}"
FLOWER_LOCAL_EPOCHS="${FLOWER_LOCAL_EPOCHS:-1}"
FLOWER_FIXED_POINT_SCALE="${FLOWER_FIXED_POINT_SCALE:-1000000}"

fail() { echo "ERROR: $*" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || fail "Docker is required"
docker compose version >/dev/null 2>&1 || fail "Docker Compose is required"
docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable"
make tools
mkdir -p "$RESULT_DIR/flower" ml/cache
chmod a+rwx ml/cache "$RESULT_DIR/flower"

cleanup() { make down >/dev/null 2>&1 || true; }
trap cleanup EXIT

make down || true
make network-clean || true
make bootstrap VALIDATORS=4
make up
sleep "${STARTUP_WAIT_SECONDS:-5}"
make status VALIDATORS=4
make deploy

if ! docker image inspect "$FLOWER_IMAGE" >/dev/null 2>&1; then
  docker build -t "$FLOWER_IMAGE" -f Dockerfile.flower .
fi

docker run --rm \
  -u "$(id -u):$(id -g)" \
  --network "${CONTROL_NETWORK_NAME:-contestfl-control-net}" \
  -e RPC_URL=http://node1:8545 \
  -e HOME=/tmp \
  -v "$ROOT:/workspace" \
  -v "$ROOT/ml/cache:/data" \
  -w /workspace \
  "$FLOWER_IMAGE" \
  python ml/flower_mnist_e2e.py \
    --clients "$FLOWER_CLIENTS" \
    --samples-per-client "$FLOWER_SAMPLES_PER_CLIENT" \
    --local-epochs "$FLOWER_LOCAL_EPOCHS" \
    --scale "$FLOWER_FIXED_POINT_SCALE" \
    --data-dir /data \
    --output-dir "$RESULT_DIR/flower" \
    --rpc http://node1:8545

docker run --rm --env-file .env \
  -u "$(id -u):$(id -g)" -v "$ROOT:/workspace" -w /workspace \
  "${TOOLS_IMAGE:-contestfl-eval-tools:local}" \
  python -c "import shutil; shutil.make_archive('$RESULT_DIR', 'zip', '$RESULT_DIR')"

echo "Flower/MNIST integration complete"
echo "  Report: $RESULT_DIR/flower/FLOWER_MNIST_E2E_REPORT.md"
echo "  Bundle: $RESULT_DIR.zip"
