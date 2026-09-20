#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_publication_extension}"
RESULT_DIR="results/runs/${RUN_ID}"
RESUME="${RESUME:-1}"

CONFIRM_ROUNDS="${CONFIRM_ROUNDS:-30}"
CONFIRM_WARMUP="${CONFIRM_WARMUP:-2}"
CORRECTION_ROUNDS="${CORRECTION_ROUNDS:-20}"
CORRECTION_WARMUP="${CORRECTION_WARMUP:-2}"
VALIDATOR_ROUNDS="${VALIDATOR_ROUNDS:-10}"
VALIDATOR_WARMUP="${VALIDATOR_WARMUP:-1}"

REPLAY_CLIENTS="${REPLAY_CLIENTS:-10,50,100}"
REPLAY_UPDATE_BYTES="${REPLAY_UPDATE_BYTES:-4096,262144,1048576,10485760}"
REPLAY_ROUNDS="${REPLAY_ROUNDS:-30}"
REPLAY_LARGE_ROUNDS="${REPLAY_LARGE_ROUNDS:-10}"
REPLAY_HUGE_ROUNDS="${REPLAY_HUGE_ROUNDS:-3}"

NETWORK_CLIENTS="${NETWORK_CLIENTS:-100}"
NETWORK_SCENARIOS="${NETWORK_SCENARIOS:-nominal,correction_laundering}"
NETWORK_ROUNDS="${NETWORK_ROUNDS:-5}"
NETWORK_WARMUP="${NETWORK_WARMUP:-1}"
NETWORK_RTT_4="${NETWORK_RTT_4:-0 10 25 50}"
NETWORK_RTT_7="${NETWORK_RTT_7:-0 25}"
NETWORK_JITTER_MS="${NETWORK_JITTER_MS:-0}"
NETWORK_RESPONSE_BLOCKS="${NETWORK_RESPONSE_BLOCKS:-4}"
NETWORK_SETTLE_SECONDS="${NETWORK_SETTLE_SECONDS:-2}"

ACTIVE_VALIDATORS=0

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "Docker is required."
docker compose version >/dev/null 2>&1 || fail "The Docker Compose plugin is required."
docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable."

free_kb=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
[[ "${free_kb:-0}" -ge 2097152 ]] || fail "At least 2 GiB of free disk space is required."

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

run_tools_python() {
  docker run --rm --env-file .env -e MPLCONFIGDIR=/tmp/matplotlib \
    -u "$(id -u):$(id -g)" -v "$ROOT:/workspace" -w /workspace \
    "${TOOLS_IMAGE:-contestfl-eval-tools:local}" python "$@"
}

mkdir -p "$RESULT_DIR/raw" "$RESULT_DIR/figures" "results/preflight/${RUN_ID}"
cat > "$RESULT_DIR/publication_extension_campaign.json" <<JSON
{
  "runId": "$RUN_ID",
  "confirmation": {
    "validators": 4,
    "nominalClients": [10, 50, 100],
    "nominalRounds": $CONFIRM_ROUNDS,
    "correctionClients": [100],
    "correctionRounds": $CORRECTION_ROUNDS
  },
  "validatorSensitivity": {
    "validators": [4, 7],
    "clients": [50, 100],
    "roundsAtSevenValidators": $VALIDATOR_ROUNDS,
    "sameHost": true
  },
  "replay": {
    "clients": "$REPLAY_CLIENTS",
    "updateBytes": "$REPLAY_UPDATE_BYTES",
    "rounds": $REPLAY_ROUNDS,
    "largeRounds": $REPLAY_LARGE_ROUNDS,
    "hugeRounds": $REPLAY_HUGE_ROUNDS
  },
  "networkEmulation": {
    "enabled": $([[ "${SKIP_NETWORK_CAMPAIGN:-0}" == "1" ]] && echo false || echo true),
    "mechanism": "tc/netem on the validator P2P interface only",
    "validators4RttMs": "$NETWORK_RTT_4",
    "validators7RttMs": "$NETWORK_RTT_7",
    "clients": "$NETWORK_CLIENTS",
    "scenarios": "$NETWORK_SCENARIOS",
    "rounds": $NETWORK_ROUNDS,
    "warmup": $NETWORK_WARMUP,
    "jitterMs": $NETWORK_JITTER_MS,
    "singleHost": true
  }
}
JSON

cleanup() {
  if [[ "$ACTIVE_VALIDATORS" -gt 0 && -f network/docker-compose.generated.yml ]]; then
    tools/netem.sh clear "$ACTIVE_VALIDATORS" >/dev/null 2>&1 || true
  fi
  make down >/dev/null 2>&1 || true
}
trap cleanup EXIT

run_benchmark() {
  local validators="$1" clients="$2" rounds="$3" warmup="$4" scenarios="$5" tag="$6"
  local network_rtt_ms="${7:-0}" response_blocks="${8:-${RESPONSE_BLOCKS:-2}}"
  local result_file="$RESULT_DIR/raw/rounds_${tag}_v${validators}.csv"

  if [[ "$RESUME" == "1" && -s "$result_file" ]]; then
    if run_tools_python tools/check_result.py \
      --file "$result_file" --clients "$clients" --rounds "$rounds" --scenarios "$scenarios"
    then
      echo "--- resume: skipping complete tag=$tag validators=$validators ---"
      return 0
    fi
  fi

  echo "--- tag=$tag validators=$validators clients=$clients rounds=$rounds scenarios=$scenarios RTT=${network_rtt_ms}ms ---"
  make benchmark \
    VALIDATORS="$validators" \
    CLIENTS="$clients" \
    ROUNDS="$rounds" \
    WARMUP="$warmup" \
    SCENARIOS="$scenarios" \
    RESULT_DIR="$RESULT_DIR" \
    BATCH_SIZE="${BATCH_SIZE:-50}" \
    CHALLENGE_BLOCKS="${CHALLENGE_BLOCKS:-1}" \
    RESPONSE_BLOCKS="$response_blocks" \
    RETRY_BUDGET="${RETRY_BUDGET:-1}" \
    UPDATE_DIM="${UPDATE_DIM:-1024}" \
    FLOOD_COUNT=1 \
    FLOOD_PARALLELISM=1 \
    FLOOD_CHALLENGE_BLOCKS=12 \
    SMT_DEPTH="${SMT_DEPTH:-32}" \
    TAG="$tag" \
    NETWORK_RTT_MS="$network_rtt_ms"
}

start_network() {
  local validators="$1"
  echo "=== Starting a fresh $validators-validator QBFT network ==="
  if [[ "$ACTIVE_VALIDATORS" -gt 0 && -f network/docker-compose.generated.yml ]]; then
    tools/netem.sh clear "$ACTIVE_VALIDATORS" >/dev/null 2>&1 || true
  fi
  make down || true
  make network-clean || true
  make bootstrap VALIDATORS="$validators"
  make up
  ACTIVE_VALIDATORS="$validators"
  sleep "${STARTUP_WAIT_SECONDS:-5}"
  make status VALIDATORS="$validators"
  make deploy
}

integration_preflight() {
  local validators="$1"
  local output="results/preflight/${RUN_ID}/v${validators}"
  rm -rf "$output"
  echo "=== Integration preflight with $validators validators ==="
  make benchmark \
    VALIDATORS="$validators" CLIENTS="10" ROUNDS=1 WARMUP=0 \
    SCENARIOS="nominal,correction_laundering" \
    RESULT_DIR="$output" BATCH_SIZE="${BATCH_SIZE:-50}" \
    CHALLENGE_BLOCKS="${CHALLENGE_BLOCKS:-1}" RESPONSE_BLOCKS=4 \
    RETRY_BUDGET="${RETRY_BUDGET:-1}" UPDATE_DIM="${UPDATE_DIM:-1024}" \
    FLOOD_COUNT=1 FLOOD_PARALLELISM=1 FLOOD_CHALLENGE_BLOCKS=12 \
    SMT_DEPTH="${SMT_DEPTH:-32}" TAG="preflight_v${validators}" NETWORK_RTT_MS=0
}

network_capability_preflight() {
  [[ "${SKIP_NETWORK_CAMPAIGN:-0}" == "1" ]] && return 0
  echo "=== Early tc/netem preflight before long measurements ==="
  tools/netem.sh preflight 4 "${NETEM_PREFLIGHT_RTT_MS:-20}"
  make status VALIDATORS=4
}

run_network_sweep() {
  local validators="$1" rtt_list="$2"
  local rtt tag
  start_network "$validators"
  for rtt in $rtt_list; do
    tag="network_rtt${rtt}"
    if [[ "$validators" == "7" ]]; then
      tag="network7_rtt${rtt}"
    else
      tag="network4_rtt${rtt}"
    fi

    tools/netem.sh apply "$validators" "$rtt" "$NETWORK_JITTER_MS"
    sleep "$NETWORK_SETTLE_SECONDS"
    tools/netem.sh probe "$validators" "$rtt" "$RESULT_DIR/network_probe.csv" >/dev/null
    make status VALIDATORS="$validators"
    run_benchmark "$validators" "$NETWORK_CLIENTS" "$NETWORK_ROUNDS" "$NETWORK_WARMUP" \
      "$NETWORK_SCENARIOS" "$tag" "$rtt" "$NETWORK_RESPONSE_BLOCKS"
    tools/netem.sh clear "$validators"
  done
  make down
  ACTIVE_VALIDATORS=0
}

make selftest

echo
printf '%s\n' \
  "ContestFL publication extension: $RUN_ID" \
  "  4-validator confirmation: $CONFIRM_ROUNDS nominal runs; $CORRECTION_ROUNDS correction runs" \
  "  7-validator sensitivity: $VALIDATOR_ROUNDS runs" \
  "  Replay sizes: $REPLAY_UPDATE_BYTES" \
  "  Network RTTs, 4 validators: $NETWORK_RTT_4" \
  "  Network RTTs, 7 validators: $NETWORK_RTT_7" \
  "  Network emulator: tc/netem on P2P only (no Pumba)"

# Fail fast on contract integration and NET_ADMIN support before hours of work.
start_network 4
if [[ "${SKIP_PREFLIGHT:-0}" != "1" ]]; then
  integration_preflight 4
fi
network_capability_preflight
make down
ACTIVE_VALIDATORS=0

if [[ "${SKIP_CONFIRMATION:-0}" != "1" ]]; then
  start_network 4
  run_benchmark 4 "10,50,100" "$CONFIRM_ROUNDS" "$CONFIRM_WARMUP" \
    "logging_only,nominal" "confirm_nominal"
  run_benchmark 4 "100" "$CORRECTION_ROUNDS" "$CORRECTION_WARMUP" \
    "bad_aggregate,bad_omission,resolver_fallback,correction_laundering" "confirm_corrections"
  make down
  ACTIVE_VALIDATORS=0
fi

if [[ "${SKIP_7_VALIDATORS:-0}" != "1" ]]; then
  start_network 7
  if [[ "${SKIP_PREFLIGHT:-0}" != "1" ]]; then
    integration_preflight 7
    echo "=== Recreating a clean seven-validator network after preflight ==="
    start_network 7
  fi
  run_benchmark 7 "50,100" "$VALIDATOR_ROUNDS" "$VALIDATOR_WARMUP" \
    "logging_only,nominal" "validator_nominal"
  run_benchmark 7 "100" "$VALIDATOR_ROUNDS" "$VALIDATOR_WARMUP" \
    "bad_aggregate,correction_laundering" "validator_corrections"
  make down
  ACTIVE_VALIDATORS=0
fi

if [[ "${SKIP_REPLAY_SCALING:-0}" != "1" ]]; then
  if [[ "$RESUME" == "1" && -s "$RESULT_DIR/replay_scaling_summary.csv" ]]; then
    echo "--- resume: skipping replay scaling ---"
  else
    echo "=== Memory-bounded replay scaling ==="
    run_tools_python bench/replay_scaling.py \
      --clients "$REPLAY_CLIENTS" \
      --update-bytes "$REPLAY_UPDATE_BYTES" \
      --rounds "$REPLAY_ROUNDS" \
      --large-rounds "$REPLAY_LARGE_ROUNDS" \
      --huge-rounds "$REPLAY_HUGE_ROUNDS" \
      --warmup 1 \
      --run-dir "$RESULT_DIR"
  fi
fi

if [[ "${SKIP_NETWORK_CAMPAIGN:-0}" != "1" ]]; then
  echo "=== Controlled inter-validator RTT campaign ==="
  run_network_sweep 4 "$NETWORK_RTT_4"
  run_network_sweep 7 "$NETWORK_RTT_7"
fi

echo "=== Analysis and publication artifacts ==="
run_tools_python bench/analyze_final_extension.py --run-dir "$RESULT_DIR"
run_tools_python -c "import shutil; shutil.make_archive('$RESULT_DIR', 'zip', '$RESULT_DIR')"

echo
echo "Publication extension complete."
echo "  Report:     $RESULT_DIR/FINAL_EXTENSION_REPORT.md"
echo "  Summary:    $RESULT_DIR/final_confirmation_summary.csv"
echo "  Validators: $RESULT_DIR/validator_comparison.csv"
echo "  Replay:     $RESULT_DIR/replay_scaling_summary.csv"
echo "  Network:    $RESULT_DIR/network_sensitivity_summary.csv"
echo "  Probes:     $RESULT_DIR/network_probe.csv"
echo "  Figures:    $RESULT_DIR/figures/"
echo "  Bundle:     $RESULT_DIR.zip"
