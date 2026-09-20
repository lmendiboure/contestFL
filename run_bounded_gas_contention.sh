#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
ensure_env_file "$ROOT"
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

require_command docker
require_command make
PYTHON_BIN="$(resolve_python)"
docker compose version >/dev/null 2>&1 || { echo "Docker Compose plugin is required." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is not reachable." >&2; exit 1; }

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_bounded_gas_contention}"
RESULT_DIR="${RESULT_DIR:-results/runs/${RUN_ID}}"
VALIDATORS="${VALIDATORS:-4}"
# The default reproduces the proposed 30 M gas operating point. A broader,
# still small sweep can be requested with BLOCK_GAS_LIMITS="5000000 10000000 30000000".
BLOCK_GAS_LIMITS="${BLOCK_GAS_LIMITS:-30000000}"
FLOOD_COUNTS="${FLOOD_COUNTS:-0,10,25,50,100}"
CONTENTION_ROUNDS="${CONTENTION_ROUNDS:-5}"
CONTENTION_WARMUP="${CONTENTION_WARMUP:-1}"
RESOLVER_PARALLELISM="${RESOLVER_PARALLELISM:-20}"
HONEST_TX_DELAY_MS="${HONEST_TX_DELAY_MS:-100}"
ALIGNMENT_DELAY_MS="${ALIGNMENT_DELAY_MS:-50}"
BROADCAST_PARALLELISM="${BROADCAST_PARALLELISM:-64}"
CHALLENGE_BLOCKS="${CONTENTION_CHALLENGE_BLOCKS:-40}"
RESPONSE_BLOCKS="${CONTENTION_RESPONSE_BLOCKS:-120}"

BLOCK_GAS_LIMITS="${BLOCK_GAS_LIMITS//,/ }"
max_flood="$($PYTHON_BIN - <<PY
values=[int(x.strip(), 0) for x in ${FLOOD_COUNTS@Q}.split(',') if x.strip()]
print(max(values or [0]))
PY
)"
CHALLENGER_ACCOUNTS_CONTENTION="${CHALLENGER_ACCOUNTS_CONTENTION:-$max_flood}"
if [[ "$CHALLENGER_ACCOUNTS_CONTENTION" -lt 1 ]]; then
  CHALLENGER_ACCOUNTS_CONTENTION=1
fi

mkdir -p "$RESULT_DIR"
make tools

cleanup() {
  make down >/dev/null 2>&1 || true
}
trap cleanup EXIT

start_network() {
  local gas_limit="$1"
  echo "=== Fresh QBFT network: block gas limit ${gas_limit} ==="
  make down || true
  make network-clean || true
  make bootstrap \
    VALIDATORS="$VALIDATORS" \
    BLOCK_GAS_LIMIT="$gas_limit" \
    TARGET_GAS_LIMIT="$gas_limit" \
    CHALLENGER_ACCOUNTS="$CHALLENGER_ACCOUNTS_CONTENTION"
  make up
  sleep "${STARTUP_WAIT_SECONDS:-5}"
  make status VALIDATORS="$VALIDATORS"
  make deploy
}

for gas_limit in $BLOCK_GAS_LIMITS; do
  [[ "$gas_limit" =~ ^(0[xX][0-9a-fA-F]+|[0-9]+)$ ]] || {
    echo "Invalid block gas limit: $gas_limit" >&2
    exit 2
  }
  start_network "$gas_limit"
  limit_decimal="$($PYTHON_BIN - <<PY
print(int(${gas_limit@Q}, 0))
PY
)"
  limit_dir="$RESULT_DIR/gas_${limit_decimal}"
  mkdir -p "$limit_dir"
  echo "=== Contention experiment at ${limit_decimal} gas/block ==="
  LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)" \
    docker compose --profile tools -f network/docker-compose.generated.yml run --rm tools \
    python bench/bounded_gas_contention.py \
      --validators "$VALIDATORS" \
      --flood-counts "$FLOOD_COUNTS" \
      --rounds "$CONTENTION_ROUNDS" \
      --warmup "$CONTENTION_WARMUP" \
      --resolver-parallelism "$RESOLVER_PARALLELISM" \
      --challenge-blocks "$CHALLENGE_BLOCKS" \
      --response-blocks "$RESPONSE_BLOCKS" \
      --honest-delay-ms "$HONEST_TX_DELAY_MS" \
      --alignment-delay-ms "$ALIGNMENT_DELAY_MS" \
      --broadcast-parallelism "$BROADCAST_PARALLELISM" \
      --tag "bounded_gas_${limit_decimal}" \
      --output-dir "$limit_dir"
done

DOCKER_TOOL=(
  docker run --rm --env-file .env
  -e MPLCONFIGDIR=/tmp/matplotlib
  -u "$(id -u):$(id -g)"
  -v "$ROOT:/workspace" -w /workspace
  "${TOOLS_IMAGE:-contestfl-eval-tools:local}"
)
"${DOCKER_TOOL[@]}" python bench/merge_bounded_gas_contention.py --run-dir "$RESULT_DIR"

python_bin="$(resolve_python)"
"$python_bin" - <<PY
from pathlib import Path
import shutil
root = Path(${RESULT_DIR@Q})
archive = shutil.make_archive(str(root), "zip", root)
print(f"Bounded-gas contention completed.\n  Results: {root}\n  Archive: {archive}")
PY
