#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_targeted_extension}"
RESULT_DIR="results/runs/${RUN_ID}"
PREFLIGHT_DIR="results/preflight/${RUN_ID}"
RESUME="${RESUME:-1}"
VALIDATORS="${VALIDATORS:-4}"

SCALING_CLIENTS="${SCALING_CLIENTS:-10,25,50,75,100,150,200,300,500}"
SCALING_ROUNDS="${SCALING_ROUNDS:-3}"
SCALING_WARMUP="${SCALING_WARMUP:-1}"
AFFECTED_VALUES="${AFFECTED_VALUES:-1 2 5 10 20 50}"
REPLACEMENT_VALUES="${REPLACEMENT_VALUES:-0 1 2 3 4 5}"
FLOOD_VALUES="${FLOOD_VALUES:-1 5 10 20 50 100}"
FLOOD_PARALLELISMS="${FLOOD_PARALLELISMS:-5 20}"
ROBUSTNESS_ROUNDS="${ROBUSTNESS_ROUNDS:-3}"
ROBUSTNESS_WARMUP="${ROBUSTNESS_WARMUP:-1}"
PHASE_REFERENCE_ROUNDS="${PHASE_REFERENCE_ROUNDS:-3}"
PHASE_REFERENCE_WARMUP="${PHASE_REFERENCE_WARMUP:-1}"

REPLAY_CLIENTS="${REPLAY_CLIENTS:-10,50,100}"
REPLAY_UPDATE_BYTES="${REPLAY_UPDATE_BYTES:-4096,65536,262144,1048576,4194304,10485760}"
REPLAY_ROUNDS="${REPLAY_ROUNDS:-10}"

BATCH_SIZE="${BATCH_SIZE:-50}"
UPDATE_DIM="${UPDATE_DIM:-1024}"
SMT_DEPTH="${SMT_DEPTH:-32}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "Docker is required."
docker compose version >/dev/null 2>&1 || fail "The Docker Compose plugin is required."
docker info >/dev/null 2>&1 || fail "The Docker daemon is not reachable."

free_kb=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
[[ "${free_kb:-0}" -ge 2097152 ]] || fail "At least 2 GiB of free disk space is required."

[[ -e .env ]] || cp .env.example .env
set -a
# shellcheck disable=SC1091
source .env
set +a

if ! docker image inspect "${BESU_IMAGE:-hyperledger/besu:26.7.0}" >/dev/null 2>&1; then
  echo "Pulling the configured Besu image before the campaign..."
  docker pull "${BESU_IMAGE:-hyperledger/besu:26.7.0}"
fi

make tools

run_tools_python() {
  docker run --rm --env-file .env -e MPLCONFIGDIR=/tmp/matplotlib \
    -u "$(id -u):$(id -g)" -v "$ROOT:/workspace" -w /workspace \
    "${TOOLS_IMAGE:-contestfl-eval-tools:local}" python "$@"
}

mkdir -p "$RESULT_DIR/raw" "$PREFLIGHT_DIR/baselines/raw" "$PREFLIGHT_DIR/contestfl/raw"
cat > "$RESULT_DIR/targeted_campaign.json" <<JSON
{
  "runId": "$RUN_ID",
  "validators": $VALIDATORS,
  "cleanScaling": {
    "clients": "$SCALING_CLIENTS",
    "designs": ["Audit-only", "Eager verification", "ContestFL"],
    "rounds": $SCALING_ROUNDS,
    "warmup": $SCALING_WARMUP,
    "batchSize": $BATCH_SIZE
  },
  "affectedDecisions": {
    "values": "$AFFECTED_VALUES",
    "clients": 100,
    "rounds": $ROBUSTNESS_ROUNDS
  },
  "faultyReplacementChain": {
    "values": "$REPLACEMENT_VALUES",
    "retryBudget": 5,
    "clients": 100,
    "rounds": $ROBUSTNESS_ROUNDS
  },
  "challengeFlooding": {
    "counts": "$FLOOD_VALUES",
    "parallelisms": "$FLOOD_PARALLELISMS",
    "clients": 100,
    "rounds": $ROBUSTNESS_ROUNDS
  },
  "replay": {
    "clients": "$REPLAY_CLIENTS",
    "updateBytes": "$REPLAY_UPDATE_BYTES",
    "roundsPerConfiguration": $REPLAY_ROUNDS,
    "isolatedProcesses": true
  },
  "networkEmulation": false
}
JSON

cleanup() {
  make down >/dev/null 2>&1 || true
}
trap cleanup EXIT

start_network() {
  echo "=== Starting a fresh ${VALIDATORS}-validator QBFT network ==="
  make down || true
  make network-clean || true
  make bootstrap VALIDATORS="$VALIDATORS"
  make up
  sleep "${STARTUP_WAIT_SECONDS:-5}"
  make status VALIDATORS="$VALIDATORS"
  make deploy
}

baseline_complete() {
  local tag="$1" clients="$2" rounds="$3" designs="$4" workloads="$5"
  local file="$RESULT_DIR/raw/baseline_rounds_${tag}_v${VALIDATORS}.csv"
  [[ "$RESUME" == "1" && -s "$file" ]] || return 1
  run_tools_python tools/check_baseline_result.py \
    --file "$file" --clients "$clients" --rounds "$rounds" \
    --designs "$designs" --workloads "$workloads"
}

contest_complete() {
  local tag="$1" clients="$2" rounds="$3" scenarios="$4"
  local file="$RESULT_DIR/raw/rounds_${tag}_v${VALIDATORS}.csv"
  [[ "$RESUME" == "1" && -s "$file" ]] || return 1
  run_tools_python tools/check_result.py \
    --file "$file" --clients "$clients" --rounds "$rounds" --scenarios "$scenarios"
}

run_baselines() {
  local tag="$1" clients="$2" rounds="$3" warmup="$4" designs="$5" workloads="$6"
  if baseline_complete "$tag" "$clients" "$rounds" "$designs" "$workloads"; then
    echo "--- resume: skipping complete baseline tag=$tag ---"
    return
  fi
  echo "--- baseline tag=$tag clients=$clients designs=$designs workloads=$workloads ---"
  make competitor-benchmark \
    VALIDATORS="$VALIDATORS" CLIENTS="$clients" \
    COMPETITOR_ROUNDS="$rounds" COMPETITOR_WARMUP="$warmup" \
    COMPETITOR_DESIGNS="$designs" COMPETITOR_WORKLOADS="$workloads" \
    COMPETITOR_TAG="$tag" BATCH_SIZE="$BATCH_SIZE" \
    CHALLENGE_BLOCKS=1 RESPONSE_BLOCKS=12 UPDATE_DIM="$UPDATE_DIM" \
    SMT_DEPTH="$SMT_DEPTH" RESULT_DIR="$RESULT_DIR"
}

run_contestfl() {
  local tag="$1" clients="$2" rounds="$3" warmup="$4" scenarios="$5"
  local affected="${6:-1}" replacements="${7:-0}" retry_budget="${8:-1}"
  local flood_count="${9:-1}" flood_parallelism="${10:-20}" challenge_blocks="${11:-1}"
  local response_blocks="${12:-12}"
  if contest_complete "$tag" "$clients" "$rounds" "$scenarios"; then
    echo "--- resume: skipping complete ContestFL tag=$tag ---"
    return
  fi
  echo "--- ContestFL tag=$tag clients=$clients scenarios=$scenarios ---"
  make benchmark \
    VALIDATORS="$VALIDATORS" CLIENTS="$clients" ROUNDS="$rounds" WARMUP="$warmup" \
    SCENARIOS="$scenarios" TAG="$tag" RESULT_DIR="$RESULT_DIR" \
    BATCH_SIZE="$BATCH_SIZE" CHALLENGE_BLOCKS="$challenge_blocks" \
    RESPONSE_BLOCKS="$response_blocks" RETRY_BUDGET="$retry_budget" \
    UPDATE_DIM="$UPDATE_DIM" SMT_DEPTH="$SMT_DEPTH" \
    FLOOD_COUNT="$flood_count" FLOOD_PARALLELISM="$flood_parallelism" \
    FLOOD_CHALLENGE_BLOCKS=12 AFFECTED_DECISIONS="$affected" \
    FAULTY_REPLACEMENTS="$replacements" NETWORK_RTT_MS=0
}

preflight() {
  echo "=== Targeted live preflight ==="
  rm -rf "$PREFLIGHT_DIR"
  mkdir -p "$PREFLIGHT_DIR/baselines/raw" "$PREFLIGHT_DIR/contestfl/raw"

  make competitor-benchmark \
    VALIDATORS="$VALIDATORS" CLIENTS=500 COMPETITOR_ROUNDS=1 COMPETITOR_WARMUP=0 \
    COMPETITOR_DESIGNS=eager_full COMPETITOR_WORKLOADS=clean \
    COMPETITOR_TAG=preflight_eager_500 BATCH_SIZE="$BATCH_SIZE" \
    CHALLENGE_BLOCKS=1 RESPONSE_BLOCKS=70 UPDATE_DIM="$UPDATE_DIM" \
    SMT_DEPTH="$SMT_DEPTH" RESULT_DIR="$PREFLIGHT_DIR/baselines"

  make benchmark \
    VALIDATORS="$VALIDATORS" CLIENTS=500 ROUNDS=1 WARMUP=0 SCENARIOS=nominal \
    TAG=preflight_contestfl_500 RESULT_DIR="$PREFLIGHT_DIR/contestfl" \
    BATCH_SIZE="$BATCH_SIZE" CHALLENGE_BLOCKS=1 RESPONSE_BLOCKS=12 \
    RETRY_BUDGET=1 UPDATE_DIM="$UPDATE_DIM" SMT_DEPTH="$SMT_DEPTH" \
    FLOOD_COUNT=1 FLOOD_PARALLELISM=20 FLOOD_CHALLENGE_BLOCKS=12 \
    AFFECTED_DECISIONS=1 FAULTY_REPLACEMENTS=0 NETWORK_RTT_MS=0

  make benchmark \
    VALIDATORS="$VALIDATORS" CLIENTS=100 ROUNDS=1 WARMUP=0 \
    SCENARIOS=affected_decisions,faulty_replacement_chain \
    TAG=preflight_targeted_robustness RESULT_DIR="$PREFLIGHT_DIR/contestfl" \
    BATCH_SIZE="$BATCH_SIZE" CHALLENGE_BLOCKS=12 RESPONSE_BLOCKS=30 \
    RETRY_BUDGET=5 UPDATE_DIM="$UPDATE_DIM" SMT_DEPTH="$SMT_DEPTH" \
    FLOOD_COUNT=1 FLOOD_PARALLELISM=20 FLOOD_CHALLENGE_BLOCKS=12 \
    AFFECTED_DECISIONS=50 FAULTY_REPLACEMENTS=5 NETWORK_RTT_MS=0

  make benchmark \
    VALIDATORS="$VALIDATORS" CLIENTS=100 ROUNDS=1 WARMUP=0 \
    SCENARIOS=challenge_flooding TAG=preflight_flood_100_p5 \
    RESULT_DIR="$PREFLIGHT_DIR/contestfl" BATCH_SIZE="$BATCH_SIZE" \
    CHALLENGE_BLOCKS=12 RESPONSE_BLOCKS=60 RETRY_BUDGET=1 \
    UPDATE_DIM="$UPDATE_DIM" SMT_DEPTH="$SMT_DEPTH" FLOOD_COUNT=100 \
    FLOOD_PARALLELISM=5 FLOOD_CHALLENGE_BLOCKS=12 \
    AFFECTED_DECISIONS=1 FAULTY_REPLACEMENTS=0 NETWORK_RTT_MS=0
}

start_network
preflight

echo "=== Figure 2: clean-path scaling ==="
run_baselines target_clean_scaling "$SCALING_CLIENTS" "$SCALING_ROUNDS" "$SCALING_WARMUP" \
  ledger_audit,eager_full clean
run_contestfl target_contestfl_clean_scaling "$SCALING_CLIENTS" "$SCALING_ROUNDS" \
  "$SCALING_WARMUP" nominal

echo "=== Figure 5(a): affected client-level decisions ==="
for value in $AFFECTED_VALUES; do
  run_contestfl "target_affected_k${value}" 100 "$ROBUSTNESS_ROUNDS" \
    "$ROBUSTNESS_WARMUP" affected_decisions "$value" 0 1 1 20 20 30
done

echo "=== Figure 5(b): faulty replacement chain ==="
for value in $REPLACEMENT_VALUES; do
  run_contestfl "target_replacement_d${value}" 100 "$ROBUSTNESS_ROUNDS" \
    "$ROBUSTNESS_WARMUP" faulty_replacement_chain 1 "$value" 5 1 20 3 12
done

echo "=== Figure 5(c): challenge flooding ==="
for count in $FLOOD_VALUES; do
  for parallelism in $FLOOD_PARALLELISMS; do
    response=$(( 2 * ((count + parallelism - 1) / parallelism) + 12 ))
    run_contestfl "target_flood_f${count}_p${parallelism}" 100 "$ROBUSTNESS_ROUNDS" \
      "$ROBUSTNESS_WARMUP" challenge_flooding 1 0 1 "$count" "$parallelism" 12 "$response"
  done
done

if [[ "${RUN_PHASE_REFERENCES:-1}" == "1" ]]; then
  echo "=== Figure 6: compact reference paths for phase decomposition ==="
  run_contestfl target_phase_references 100 "$PHASE_REFERENCE_ROUNDS" \
    "$PHASE_REFERENCE_WARMUP" bad_aggregate,resolver_fallback
fi

if [[ "${RUN_REPLAY:-1}" == "1" ]]; then
  if [[ "$RESUME" == "1" && -s "$RESULT_DIR/replay_scaling_summary.csv" ]]; then
    rows=$(run_tools_python -c "import pandas as pd; p='$RESULT_DIR/replay_scaling_summary.csv'; d=pd.read_csv(p); print(len(d) if d['runs'].min() >= $REPLAY_ROUNDS else 0)" 2>/dev/null || echo 0)
    if [[ "$rows" == "18" ]]; then
      echo "--- resume: skipping complete isolated replay sweep ---"
    else
      rm -f "$RESULT_DIR/raw/replay_scaling_raw.csv" "$RESULT_DIR/replay_scaling_summary.csv"
      make replay-scaling RESULT_DIR="$RESULT_DIR" REPLAY_CLIENTS="$REPLAY_CLIENTS" \
        REPLAY_UPDATE_BYTES="$REPLAY_UPDATE_BYTES" REPLAY_ROUNDS="$REPLAY_ROUNDS" \
        REPLAY_LARGE_ROUNDS="$REPLAY_ROUNDS" REPLAY_HUGE_ROUNDS="$REPLAY_ROUNDS" \
        REPLAY_ISOLATE_CONFIGS=1
    fi
  else
    make replay-scaling RESULT_DIR="$RESULT_DIR" REPLAY_CLIENTS="$REPLAY_CLIENTS" \
      REPLAY_UPDATE_BYTES="$REPLAY_UPDATE_BYTES" REPLAY_ROUNDS="$REPLAY_ROUNDS" \
      REPLAY_LARGE_ROUNDS="$REPLAY_ROUNDS" REPLAY_HUGE_ROUNDS="$REPLAY_ROUNDS" \
      REPLAY_ISOLATE_CONFIGS=1
  fi
fi

echo "=== Targeted summaries ==="
make analyze-targeted RESULT_DIR="$RESULT_DIR"

echo "=== Completed ==="
echo "Report: $RESULT_DIR/TARGETED_EXTENSION_REPORT.md"
echo "Bundle: $RESULT_DIR.zip"
