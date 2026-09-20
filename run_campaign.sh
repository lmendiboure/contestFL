#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PROFILE="${1:-quick}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_${PROFILE}}"
RESULT_DIR="results/runs/${RUN_ID}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "The Docker Compose plugin is required." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not reachable." >&2
  exit 1
fi
free_kb=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
if [[ "${free_kb:-0}" -lt 2097152 ]]; then
  echo "At least 2 GiB of free disk space is required." >&2
  exit 1
fi

[[ -e .env ]] || cp .env.example .env
set -a
# shellcheck disable=SC1091
source .env
set +a
if ! docker image inspect "${BESU_IMAGE:-hyperledger/besu:26.7.0}" >/dev/null 2>&1; then
  echo "Pulling Besu image before the campaign..."
  docker pull "${BESU_IMAGE:-hyperledger/besu:26.7.0}"
fi
make tools
# shellcheck disable=SC2046
eval "$(docker run --rm --env-file .env -u "$(id -u):$(id -g)" -v "$ROOT:/workspace" -w /workspace "${TOOLS_IMAGE:-contestfl-eval-tools:local}" python tools/profile.py "$PROFILE")"

VALIDATOR_LIST="${VALIDATOR_LIST_OVERRIDE:-$VALIDATOR_LIST}"
CLIENTS="${CLIENTS_OVERRIDE:-$CLIENTS}"
ROUNDS="${ROUNDS_OVERRIDE:-$ROUNDS}"
WARMUP="${WARMUP_OVERRIDE:-$WARMUP}"
SCENARIOS="${SCENARIOS_OVERRIDE:-$SCENARIOS}"

run_tools_python() {
  docker run --rm --env-file .env -e MPLCONFIGDIR=/tmp/matplotlib \
    -u "$(id -u):$(id -g)" -v "$ROOT:/workspace" -w /workspace \
    "${TOOLS_IMAGE:-contestfl-eval-tools:local}" python "$@"
}

# The stable profile intentionally excludes the optional network-delay sweep and
# the slow serial flooding configuration. These defaults remain overridable.
if [[ "$PROFILE" == "stable" ]]; then
  SKIP_NETWORK_SWEEP="${SKIP_NETWORK_SWEEP:-1}"
  CAPACITY_CLIENTS="${CAPACITY_CLIENTS:-10,50,100,200,500}"
  CAPACITY_BATCH_SIZES="${CAPACITY_BATCH_SIZES:-25 50 100}"
  WINDOW_CLIENTS="${WINDOW_CLIENTS:-100}"
  CHALLENGE_WINDOW_LIST="${CHALLENGE_WINDOW_LIST:-1 5 10}"
  FLOOD_CLIENTS="${FLOOD_CLIENTS:-100}"
  FLOOD_COUNT_LIST="${FLOOD_COUNT_LIST:-1 20 50}"
  FLOOD_PARALLELISM_LIST="${FLOOD_PARALLELISM_LIST:-5 20}"
  FLOOD_CHALLENGE_BLOCKS="${FLOOD_CHALLENGE_BLOCKS:-12}"
  SWEEP_ROUNDS="${SWEEP_ROUNDS:-3}"
  SWEEP_WARMUP="${SWEEP_WARMUP:-1}"
  OPTIMISTIC_CLIENTS="${OPTIMISTIC_CLIENTS:-10,50}"
  UPDATE_BYTES_LIST="${UPDATE_BYTES_LIST:-4096,1048576,10485760}"
  CHALLENGE_RATES="${CHALLENGE_RATES:-0,0.01,0.1,0.5,1}"
  OPTIMISTIC_ROUNDS="${OPTIMISTIC_ROUNDS:-5}"
  OPTIMISTIC_LARGE_ROUNDS="${OPTIMISTIC_LARGE_ROUNDS:-2}"
  FUZZ_SEQUENCES="${FUZZ_SEQUENCES:-5000}"
  FUZZ_MAX_STEPS="${FUZZ_MAX_STEPS:-40}"
fi

EXTENDED=0
if [[ "$PROFILE" == "stable" || "$PROFILE" == "paper" || "$PROFILE" == "exhaustive" ]]; then
  EXTENDED=1
fi

CAPACITY_CLIENTS="${CAPACITY_CLIENTS:-10,25,50,75,100,150,200,300,500}"
CAPACITY_BATCH_SIZES="${CAPACITY_BATCH_SIZES:-10 25 50 100}"
WINDOW_CLIENTS="${WINDOW_CLIENTS:-50,100}"
CHALLENGE_WINDOW_LIST="${CHALLENGE_WINDOW_LIST:-1 2 5 10}"
FLOOD_CLIENTS="${FLOOD_CLIENTS:-100}"
FLOOD_COUNT_LIST="${FLOOD_COUNT_LIST:-1 5 10 20 50 100}"
FLOOD_PARALLELISM_LIST="${FLOOD_PARALLELISM_LIST:-1 5 10 20}"
FLOOD_CHALLENGE_BLOCKS="${FLOOD_CHALLENGE_BLOCKS:-10}"
NETWORK_CLIENTS="${NETWORK_CLIENTS:-50,100}"
NETWORK_RTT_LIST="${NETWORK_RTT_LIST:-0 10 25 50}"

if [[ "$PROFILE" == "exhaustive" ]]; then
  SWEEP_ROUNDS="${SWEEP_ROUNDS:-30}"
  SWEEP_WARMUP="${SWEEP_WARMUP:-3}"
  NETWORK_ROUNDS="${NETWORK_ROUNDS:-10}"
else
  SWEEP_ROUNDS="${SWEEP_ROUNDS:-10}"
  SWEEP_WARMUP="${SWEEP_WARMUP:-2}"
  NETWORK_ROUNDS="${NETWORK_ROUNDS:-5}"
fi

mkdir -p "$RESULT_DIR/raw" "$RESULT_DIR/figures"
cat > "$RESULT_DIR/campaign.json" <<JSON
{
  "profile": "$PROFILE",
  "runId": "$RUN_ID",
  "validators": "$VALIDATOR_LIST",
  "clients": "$CLIENTS",
  "rounds": $ROUNDS,
  "warmup": $WARMUP,
  "scenarios": "$SCENARIOS",
  "batchSize": ${BATCH_SIZE:-50},
  "challengeBlocks": ${CHALLENGE_BLOCKS:-1},
  "responseBlocks": ${RESPONSE_BLOCKS:-2},
  "retryBudget": ${RETRY_BUDGET:-1},
  "updateDim": ${UPDATE_DIM:-1024},
  "floodCount": ${FLOOD_COUNT:-20},
  "floodParallelism": ${FLOOD_PARALLELISM:-20},
  "floodChallengeBlocks": $FLOOD_CHALLENGE_BLOCKS,
  "extended": $EXTENDED,
  "capacityClients": "$CAPACITY_CLIENTS",
  "capacityBatchSizes": "$CAPACITY_BATCH_SIZES",
  "challengeWindowList": "$CHALLENGE_WINDOW_LIST",
  "floodCountList": "$FLOOD_COUNT_LIST",
  "floodParallelismList": "$FLOOD_PARALLELISM_LIST",
  "networkRttList": "$NETWORK_RTT_LIST"
}
JSON

echo "ContestFL campaign: $RUN_ID"
echo "  profile:    $PROFILE"
echo "  validators: $VALIDATOR_LIST"
echo "  clients:    $CLIENTS"
echo "  rounds:     $ROUNDS (+ $WARMUP warm-up)"
echo "  scenarios:  $SCENARIOS"
if [[ "$EXTENDED" -eq 1 ]]; then
  echo "  targeted sweeps: enabled"
fi

CURRENT_VALIDATORS=0
cleanup() {
  if [[ "$CURRENT_VALIDATORS" -gt 0 && -f network/docker-compose.generated.yml ]]; then
    tools/netem.sh clear "$CURRENT_VALIDATORS" >/dev/null 2>&1 || true
  fi
  make down >/dev/null 2>&1 || true
}
trap cleanup EXIT

run_benchmark() {
  local validators="$1" clients="$2" rounds="$3" warmup="$4" scenarios="$5" tag="$6"
  local batch_size="${7:-${BATCH_SIZE:-50}}"
  local challenge_blocks="${8:-${CHALLENGE_BLOCKS:-1}}"
  local flood_count="${9:-${FLOOD_COUNT:-20}}"
  local flood_parallelism="${10:-${FLOOD_PARALLELISM:-20}}"
  local network_rtt_ms="${11:-0}"
  local response_blocks="${12:-${RESPONSE_BLOCKS:-2}}"
  local safe_tag="${tag//[^a-zA-Z0-9_-]/_}"
  local result_file="$RESULT_DIR/raw/rounds_${safe_tag}_v${validators}.csv"
  if [[ "${RESUME:-1}" == "1" && -s "$result_file" ]]; then
    if run_tools_python tools/check_result.py \
      --file "$result_file" --clients "$clients" --rounds "$rounds" --scenarios "$scenarios"
    then
      echo "--- resume: skipping complete tag=$tag validators=$validators ---"
      return 0
    fi
  fi
  echo "--- tag=$tag validators=$validators clients=$clients rounds=$rounds scenarios=$scenarios ---"
  make benchmark \
    VALIDATORS="$validators" \
    CLIENTS="$clients" \
    ROUNDS="$rounds" \
    WARMUP="$warmup" \
    SCENARIOS="$scenarios" \
    RESULT_DIR="$RESULT_DIR" \
    BATCH_SIZE="$batch_size" \
    CHALLENGE_BLOCKS="$challenge_blocks" \
    RESPONSE_BLOCKS="$response_blocks" \
    RETRY_BUDGET="${RETRY_BUDGET:-1}" \
    UPDATE_DIM="${UPDATE_DIM:-1024}" \
    FLOOD_COUNT="$flood_count" \
    FLOOD_PARALLELISM="$flood_parallelism" \
    FLOOD_CHALLENGE_BLOCKS="$FLOOD_CHALLENGE_BLOCKS" \
    SMT_DEPTH="${SMT_DEPTH:-32}" \
    TAG="$tag" \
    NETWORK_RTT_MS="$network_rtt_ms"
}

run_integration_preflight() {
  local preflight_dir="results/preflight/${RUN_ID}"
  echo "=== Integration preflight: known stress paths ==="
  rm -rf "$preflight_dir"
  make down || true
  make network-clean || true
  make bootstrap VALIDATORS=4
  make up
  sleep "${STARTUP_WAIT_SECONDS:-4}"
  make status VALIDATORS=4
  make deploy
  make benchmark \
    VALIDATORS=4 CLIENTS="100" ROUNDS=1 WARMUP=0 \
    SCENARIOS="concurrent_moot,correction_laundering,challenge_flooding" \
    RESULT_DIR="$preflight_dir" BATCH_SIZE="${BATCH_SIZE:-50}" \
    CHALLENGE_BLOCKS="${CHALLENGE_BLOCKS:-1}" RESPONSE_BLOCKS=16 \
    RETRY_BUDGET="${RETRY_BUDGET:-1}" UPDATE_DIM="${UPDATE_DIM:-1024}" \
    FLOOD_COUNT=50 FLOOD_PARALLELISM=20 FLOOD_CHALLENGE_BLOCKS=12 \
    SMT_DEPTH="${SMT_DEPTH:-32}" TAG=integration_preflight NETWORK_RTT_MS=0
  make down
  echo "=== Integration preflight passed ==="
}

make selftest
if [[ "$PROFILE" == "stable" && "${SKIP_INTEGRATION_PREFLIGHT:-0}" != "1" ]]; then
  run_integration_preflight
fi
for validators in $VALIDATOR_LIST; do
  CURRENT_VALIDATORS="$validators"
  echo "=== QBFT network with $validators validators ==="
  make down || true
  make network-clean || true
  make bootstrap VALIDATORS="$validators"
  make up
  sleep "${STARTUP_WAIT_SECONDS:-4}"
  make status VALIDATORS="$validators"
  make deploy

  run_benchmark "$validators" "$CLIENTS" "$ROUNDS" "$WARMUP" "$SCENARIOS" core

  if [[ "$EXTENDED" -eq 1 && "$validators" -eq 4 && "${SKIP_CAPACITY_SWEEP:-0}" != "1" ]]; then
    for batch in $CAPACITY_BATCH_SIZES; do
      run_benchmark "$validators" "$CAPACITY_CLIENTS" "$SWEEP_ROUNDS" "$SWEEP_WARMUP" \
        "logging_only,nominal" "capacity_b${batch}" "$batch"
    done
  fi

  if [[ "$EXTENDED" -eq 1 && "$validators" -eq 4 && "${SKIP_WINDOW_SWEEP:-0}" != "1" ]]; then
    for window in $CHALLENGE_WINDOW_LIST; do
      run_benchmark "$validators" "$WINDOW_CLIENTS" "$SWEEP_ROUNDS" "$SWEEP_WARMUP" \
        "nominal" "window_c${window}" "${BATCH_SIZE:-50}" "$window"
    done
  fi

  if [[ "$EXTENDED" -eq 1 && "$validators" -eq 4 && "${SKIP_FLOOD_SWEEP:-0}" != "1" ]]; then
    for count in $FLOOD_COUNT_LIST; do
      for parallelism in $FLOOD_PARALLELISM_LIST; do
        resolution_batches=$(( (count + parallelism - 1) / parallelism ))
        # Response deadlines do not delay successful finalization; they only
        # bound how long an unresolved challenge may remain open.  Reserve a
        # conservative margin for evidence generation, RPC jitter, and block
        # packing instead of running exactly at the theoretical batch bound.
        flood_response_blocks=$(( 2 * resolution_batches + 8 ))
        if [[ "$flood_response_blocks" -lt 12 ]]; then
          flood_response_blocks=12
        fi
        run_benchmark "$validators" "$FLOOD_CLIENTS" "$SWEEP_ROUNDS" "$SWEEP_WARMUP" \
          "challenge_flooding" "flood_n${count}_p${parallelism}" "${BATCH_SIZE:-50}" \
          "${CHALLENGE_BLOCKS:-1}" "$count" "$parallelism" 0 "$flood_response_blocks"
      done
    done
  fi

  if [[ "$EXTENDED" -eq 1 && "${SKIP_NETWORK_SWEEP:-0}" != "1" ]]; then
    for rtt in $NETWORK_RTT_LIST; do
      tools/netem.sh apply "$validators" "$rtt" "${NETWORK_JITTER_MS:-0}"
      sleep "${NETWORK_SETTLE_SECONDS:-2}"
      tools/netem.sh probe "$validators" "$rtt" "$RESULT_DIR/network_probe.csv" >/dev/null
      run_benchmark "$validators" "$NETWORK_CLIENTS" "$NETWORK_ROUNDS" 1 \
        "nominal" "network_rtt${rtt}" "${BATCH_SIZE:-50}" "${CHALLENGE_BLOCKS:-1}" \
        "${FLOOD_COUNT:-20}" "${FLOOD_PARALLELISM:-20}" "$rtt" "${NETWORK_RESPONSE_BLOCKS:-4}"
      tools/netem.sh clear "$validators" >/dev/null
    done
  fi

  make down
  CURRENT_VALIDATORS=0
done

make local CLIENTS="$CLIENTS" ROUNDS="$ROUNDS" WARMUP="$WARMUP" \
  RESULT_DIR="$RESULT_DIR" UPDATE_DIM="${UPDATE_DIM:-1024}" SMT_DEPTH="${SMT_DEPTH:-32}"

if [[ "$EXTENDED" -eq 1 ]]; then
  if [[ "${SKIP_OPTIMISTIC_SWEEP:-0}" != "1" ]]; then
    make optimistic RESULT_DIR="$RESULT_DIR" \
      OPTIMISTIC_CLIENTS="${OPTIMISTIC_CLIENTS:-10,25,50}" \
      UPDATE_BYTES_LIST="${UPDATE_BYTES_LIST:-4096,262144,1048576,10485760}" \
      CHALLENGE_RATES="${CHALLENGE_RATES:-0,0.01,0.05,0.1,0.2,0.5,1}" \
      OPTIMISTIC_ROUNDS="${OPTIMISTIC_ROUNDS:-10}" \
      OPTIMISTIC_LARGE_ROUNDS="${OPTIMISTIC_LARGE_ROUNDS:-3}"
  fi
  make fuzz RESULT_DIR="$RESULT_DIR" \
    FUZZ_SEQUENCES="${FUZZ_SEQUENCES:-10000}" FUZZ_MAX_STEPS="${FUZZ_MAX_STEPS:-40}"
else
  make fuzz RESULT_DIR="$RESULT_DIR" FUZZ_SEQUENCES="${FUZZ_SEQUENCES:-1000}" FUZZ_MAX_STEPS=30
fi

make analyze RESULT_DIR="$RESULT_DIR"

echo
echo "Campaign complete."
echo "  Report: $RESULT_DIR/REPORT.md"
echo "  Core CSV: $RESULT_DIR/core_summary.csv"
echo "  Adapter CSV: $RESULT_DIR/adapter_summary.csv"
echo "  Plots: $RESULT_DIR/figures/"
echo "  Bundle: $RESULT_DIR.zip"
