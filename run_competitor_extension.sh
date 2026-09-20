#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_competitors}"
RUN_DIR="results/runs/${RUN_ID}"
PREFLIGHT_DIR="results/preflight/${RUN_ID}"
VALIDATORS="${VALIDATORS:-4}"
CLEAN_ROUNDS="${COMPETITOR_CLEAN_ROUNDS:-10}"
FAULT_ROUNDS="${COMPETITOR_FAULT_ROUNDS:-3}"
WARMUP="${COMPETITOR_WARMUP:-1}"
CLIENTS="${COMPETITOR_CLIENTS:-10,50,100}"
FAULT_CLIENTS="${COMPETITOR_FAULT_CLIENTS:-100}"
UPDATE_DIM="${UPDATE_DIM:-1024}"
BATCH_SIZE="${BATCH_SIZE:-50}"
CHALLENGE_BLOCKS="${CHALLENGE_BLOCKS:-1}"
RESPONSE_BLOCKS="${RESPONSE_BLOCKS:-6}"
RUN_REPLAY="${RUN_REPLAY:-1}"

cleanup() {
  make down >/dev/null 2>&1 || true
}
trap cleanup EXIT

mkdir -p "$RUN_DIR/baselines/raw" "$RUN_DIR/contestfl/raw" "$PREFLIGHT_DIR"

echo "=== ContestFL representative competitor extension ==="
echo "RUN_ID=$RUN_ID"
echo "Results: $RUN_DIR"
echo "No Pumba, tc/netem, or network-delay campaign is used."

echo "=== Static self-tests ==="
make selftest

echo "=== Fresh 4-validator QBFT network ==="
make network-clean || true
make bootstrap VALIDATORS="$VALIDATORS"
make up
make status VALIDATORS="$VALIDATORS"
make deploy

echo "=== Early competitor preflight ==="
make competitor-benchmark \
  VALIDATORS="$VALIDATORS" \
  CLIENTS=10 \
  COMPETITOR_ROUNDS=1 \
  COMPETITOR_WARMUP=0 \
  COMPETITOR_DESIGNS=eager_full,single_shot \
  COMPETITOR_WORKLOADS=clean,correction_laundering,resolver_unavailable \
  COMPETITOR_TAG=preflight_competitors \
  RESPONSE_BLOCKS="$RESPONSE_BLOCKS" \
  RESULT_DIR="$PREFLIGHT_DIR/baselines"

make benchmark \
  VALIDATORS="$VALIDATORS" \
  CLIENTS=10 \
  ROUNDS=1 \
  WARMUP=0 \
  SCENARIOS=nominal,correction_laundering,resolver_timeout_abort \
  TAG=preflight_contestfl \
  RESPONSE_BLOCKS="$RESPONSE_BLOCKS" \
  RESULT_DIR="$PREFLIGHT_DIR/contestfl"

echo "=== Clean-path competitor costs ==="
make competitor-benchmark \
  VALIDATORS="$VALIDATORS" \
  CLIENTS="$CLIENTS" \
  COMPETITOR_ROUNDS="$CLEAN_ROUNDS" \
  COMPETITOR_WARMUP="$WARMUP" \
  COMPETITOR_DESIGNS=plain_fl,ledger_audit,eager_full,single_shot \
  COMPETITOR_WORKLOADS=clean \
  COMPETITOR_TAG=competitor_clean \
  BATCH_SIZE="$BATCH_SIZE" \
  RESPONSE_BLOCKS="$RESPONSE_BLOCKS" \
  UPDATE_DIM="$UPDATE_DIM" \
  RESULT_DIR="$RUN_DIR/baselines"

make benchmark \
  VALIDATORS="$VALIDATORS" \
  CLIENTS="$CLIENTS" \
  ROUNDS="$CLEAN_ROUNDS" \
  WARMUP="$WARMUP" \
  SCENARIOS=nominal \
  TAG=competitor_contestfl_clean \
  BATCH_SIZE="$BATCH_SIZE" \
  CHALLENGE_BLOCKS="$CHALLENGE_BLOCKS" \
  RESPONSE_BLOCKS="$RESPONSE_BLOCKS" \
  UPDATE_DIM="$UPDATE_DIM" \
  RESULT_DIR="$RUN_DIR/contestfl"

echo "=== Aggregate-dispute scaling across client counts ==="
make competitor-benchmark \
  VALIDATORS="$VALIDATORS" \
  CLIENTS="$CLIENTS" \
  COMPETITOR_ROUNDS="$FAULT_ROUNDS" \
  COMPETITOR_WARMUP="$WARMUP" \
  COMPETITOR_DESIGNS=plain_fl,ledger_audit,eager_full,single_shot \
  COMPETITOR_WORKLOADS=bad_aggregate \
  COMPETITOR_TAG=competitor_aggregate_scaling \
  BATCH_SIZE="$BATCH_SIZE" \
  CHALLENGE_BLOCKS="$CHALLENGE_BLOCKS" \
  RESPONSE_BLOCKS="$RESPONSE_BLOCKS" \
  UPDATE_DIM="$UPDATE_DIM" \
  RESULT_DIR="$RUN_DIR/baselines"

make benchmark \
  VALIDATORS="$VALIDATORS" \
  CLIENTS="$CLIENTS" \
  ROUNDS="$FAULT_ROUNDS" \
  WARMUP="$WARMUP" \
  SCENARIOS=bad_aggregate \
  TAG=competitor_contestfl_aggregate_scaling \
  BATCH_SIZE="$BATCH_SIZE" \
  CHALLENGE_BLOCKS="$CHALLENGE_BLOCKS" \
  RESPONSE_BLOCKS="$RESPONSE_BLOCKS" \
  UPDATE_DIM="$UPDATE_DIM" \
  RESULT_DIR="$RUN_DIR/contestfl"

echo "=== Fault semantics and challenged costs at ${FAULT_CLIENTS} clients ==="
make competitor-benchmark \
  VALIDATORS="$VALIDATORS" \
  CLIENTS="$FAULT_CLIENTS" \
  COMPETITOR_ROUNDS="$FAULT_ROUNDS" \
  COMPETITOR_WARMUP="$WARMUP" \
  COMPETITOR_DESIGNS=plain_fl,ledger_audit,eager_full,single_shot \
  COMPETITOR_WORKLOADS=bad_admission,bad_omission,bad_aggregate,dependent_fault,correction_laundering,resolver_unavailable \
  COMPETITOR_TAG=competitor_faults \
  BATCH_SIZE="$BATCH_SIZE" \
  CHALLENGE_BLOCKS="$CHALLENGE_BLOCKS" \
  RESPONSE_BLOCKS="$RESPONSE_BLOCKS" \
  UPDATE_DIM="$UPDATE_DIM" \
  RESULT_DIR="$RUN_DIR/baselines"

make benchmark \
  VALIDATORS="$VALIDATORS" \
  CLIENTS="$FAULT_CLIENTS" \
  ROUNDS="$FAULT_ROUNDS" \
  WARMUP="$WARMUP" \
  SCENARIOS=bad_admission,bad_omission,bad_aggregate,concurrent_moot,correction_laundering,resolver_timeout_abort \
  TAG=competitor_contestfl_faults \
  BATCH_SIZE="$BATCH_SIZE" \
  CHALLENGE_BLOCKS="$CHALLENGE_BLOCKS" \
  RESPONSE_BLOCKS="$RESPONSE_BLOCKS" \
  UPDATE_DIM="$UPDATE_DIM" \
  RESULT_DIR="$RUN_DIR/contestfl"

if [[ "$RUN_REPLAY" == "1" ]]; then
  echo "=== Replay scaling for eager/optimistic projections ==="
  make replay-scaling \
    RESULT_DIR="$RUN_DIR" \
    REPLAY_CLIENTS=10,50,100 \
    REPLAY_UPDATE_BYTES=4096,262144,1048576,10485760 \
    REPLAY_ROUNDS="${REPLAY_ROUNDS:-15}" \
    REPLAY_LARGE_ROUNDS="${REPLAY_LARGE_ROUNDS:-8}" \
    REPLAY_HUGE_ROUNDS="${REPLAY_HUGE_ROUNDS:-3}"
fi

echo "=== Publication figures and tables ==="
make analyze-competitors RESULT_DIR="$RUN_DIR"

echo "=== Completed ==="
echo "Report: $RUN_DIR/COMPETITOR_EXTENSION_REPORT.md"
echo "Bundle: $RUN_DIR.zip"
