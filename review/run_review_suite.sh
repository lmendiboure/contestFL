#!/usr/bin/env bash
# ContestFL major-revision reproducibility campaign.
# Usage: ./review/run_review_suite.sh check|smoke|full
set -Eeuo pipefail
export LC_ALL=C
export LANG=C
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-smoke}"
case "$MODE" in check|smoke|full) ;; *) echo "Usage: $0 check|smoke|full" >&2; exit 2;; esac
BASE_RUN_ID="${BASE_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
case "$BASE_RUN_ID" in *[!a-zA-Z0-9_-]*|'') echo "BASE_RUN_ID must contain only alphanumerics, underscore or dash" >&2; exit 2;; esac
REVIEW_DIR="review_outputs/${BASE_RUN_ID}_${MODE}"
mkdir -p "$REVIEW_DIR/logs"
STATUS_FILE="$REVIEW_DIR/STAGE_STATUS.tsv"
printf 'stage\tstatus\tunix_utc\n' > "$STATUS_FILE"

step() {
  local name="$1"; shift
  echo "### ${name} | $(date -u +%FT%TZ)" | tee "$REVIEW_DIR/logs/${name}.log"
  if "$@" 2>&1 | tee -a "$REVIEW_DIR/logs/${name}.log"; then
    printf '%s\tPASS\t%s\n' "$name" "$(date -u +%s)" >> "$STATUS_FILE"
  else
    local rc="${PIPESTATUS[0]}"
    printf '%s\tFAIL_%s\t%s\n' "$name" "$rc" "$(date -u +%s)" >> "$STATUS_FILE"
    echo "FAILED: ${name}. The log and prior observations remain in ${REVIEW_DIR}." >&2
    exit "$rc"
  fi
}

step host_static bash scripts/check_repository.sh
step window_reference_preflight python3 review/window_sensitivity.py \
  --watcher-summary results/reference/summaries/watcher_extension/watcher_pipeline_summary.csv \
  --output-dir "$REVIEW_DIR/reference_window_model"
if [[ "$MODE" == "check" ]]; then
  echo "Host checks complete. The reference window model is NOT a new WAN measurement."
  echo "Results: $REVIEW_DIR"
  exit 0
fi

source scripts/common.sh
ensure_env_file "$ROOT"
step preflight bash scripts/preflight.sh
step build_tools make tools
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)"
export CHALLENGER_ACCOUNTS="${CHALLENGER_ACCOUNTS:-128}"
export TARGET_GAS_LIMIT=30000000
export BLOCK_GAS_LIMIT=30000000

# Pure model sensitivity and C1 source. In full mode collect *fresh* watcher
# measurements. Smoke draws on retained reference data and is not publishable.
if [[ "$MODE" == "full" ]]; then
  step watcher_fresh env \
    RUN_ID="${BASE_RUN_ID}_review_watcher" \
    WATCHER_CLIENTS=100 WATCHER_UPDATE_BYTES=1048576,10485760 \
    WATCHER_ROUNDS="${WATCHER_ROUNDS:-30}" WATCHER_WARMUP=2 \
    WATCHER_CACHE_MODES=warm,fadvise WATCHER_RETAIN_DATASETS=0 \
    bash run_watcher_extension.sh
  step window_fresh python3 review/window_sensitivity.py \
    --watcher-summary "results/runs/${BASE_RUN_ID}_review_watcher/watcher_pipeline_summary.csv" \
    --output-dir "$REVIEW_DIR/window_model"
else
  cp "$REVIEW_DIR/reference_window_model/recommended_window.json" "$REVIEW_DIR/reference_window_model/SMOKE_ONLY_not_new_measurement.json"
  mkdir -p "$REVIEW_DIR/window_model"
  cp "$REVIEW_DIR/reference_window_model/"* "$REVIEW_DIR/window_model/"
fi

CHALLENGE_WINDOW="$(python3 - "$REVIEW_DIR/window_model/recommended_window.json" <<'PY'
import json,sys
v=int(json.load(open(sys.argv[1]))['challenge_blocks'])
assert 1 <= v <= 10000
print(v)
PY
)"
RESPONSE_BLOCKS="${REVIEW_RESPONSE_BLOCKS:-120}"
ROUNDS="${REVIEW_ROUNDS:-1}"
CLIENTS="10"
UPDATE_DIM="1024"
if [[ "$MODE" == full ]]; then
  ROUNDS="${REVIEW_ROUNDS:-12}"
  CLIENTS="10,50,100"
  UPDATE_DIM="${REVIEW_UPDATE_DIM:-262144}" # 1 MiB per client
fi

cleanup() {
  make down >/dev/null 2>&1 || true
}
trap cleanup EXIT

start_besu() {
  local gas_limit="$1"
  make down || true
  make network-clean || true
  make bootstrap VALIDATORS=4 CHALLENGER_ACCOUNTS="$CHALLENGER_ACCOUNTS" \
    BLOCK_GAS_LIMIT="$gas_limit" TARGET_GAS_LIMIT="$gas_limit"
  make up
  sleep "${STARTUP_WAIT_SECONDS:-5}"
  make status VALIDATORS=4
  make deploy
}

docker_python() {
  docker compose --profile tools -f network/docker-compose.generated.yml run --rm tools python "$@"
}

step new_qbft_30m start_besu 30000000
step onchain_conformance make benchmark \
  VALIDATORS=4 CLIENTS=10 ROUNDS="$ROUNDS" WARMUP=0 \
  CHALLENGE_BLOCKS="${REVIEW_CONFORMANCE_BLOCKS:-30}" \
  RESPONSE_BLOCKS="$RESPONSE_BLOCKS" RETRY_BUDGET=2 \
  SCENARIOS='adversarial_moot_guard,review_quota_dedupe,concurrent_moot,bad_admission,correction_laundering' \
  TAG=review_conformance RESULT_DIR="$REVIEW_DIR/conformance"
step trusted_resolver_boundary docker_python review/trust_boundary_probe.py \
  --output "$REVIEW_DIR/trust_boundary.json" --validators 4
step paired_policies docker_python review/paired_policies.py \
  --validators 4 --clients "$CLIENTS" --rounds "$ROUNDS" --warmup 1 \
  --challenge-blocks "$CHALLENGE_WINDOW" --response-blocks "$RESPONSE_BLOCKS" \
  --retry-budget 2 --update-dim "$UPDATE_DIM" \
  --output-dir "$REVIEW_DIR/paired_policies"
step paired_analysis python3 review/analyze_policies.py \
  --input "$REVIEW_DIR/paired_policies/paired_policies_raw.csv" \
  --output-dir "$REVIEW_DIR/paired_policies"
step down_30m make down

# Fresh bounded-block-capacity chain, not the original unlimited-gas genesis.
step new_qbft_5m start_besu 5000000
if [[ "$MODE" == "smoke" ]]; then
  FLOOD_COUNTS=0,8
  FLOOD_ROUNDS=1
  FLOOD_WAVES=2
else
  FLOOD_COUNTS="${REVIEW_FLOOD_COUNTS:-0,30,90}"
  FLOOD_ROUNDS="${REVIEW_FLOOD_ROUNDS:-10}"
  FLOOD_WAVES=3
fi
step late_challenge_flood docker_python review/late_challenge_flood.py \
  --validators 4 --rounds "$FLOOD_ROUNDS" \
  --flood-counts "$FLOOD_COUNTS" --quotas '0,1' \
  --waves "$FLOOD_WAVES" --attacker-identities 4 \
  --challenge-blocks 40 --response-blocks 120 \
  --output-dir "$REVIEW_DIR/late_challenges"
step down_5m make down

if [[ "$MODE" == "full" ]]; then
  # Preserve/extend the original full paper experiments, Flower, formal TLC,
  # merkle/256-bit depth, root-only, watcher, and bounded contention. This may
  # take substantial compute and disk, particularly the 100/1000 MiB watcher.
  step original_paper_full env \
    BASE_RUN_ID="${BASE_RUN_ID}_original" SUITE=paper RESUME=0 \
    bash run_all_from_scratch.sh
  # Control P2P RTT on same-host 4/7 validators (not actual cross-site WAN).
  step p2p_rtt_150ms env RUN_ID="${BASE_RUN_ID}_rtt150" \
    NETWORK_RTT_MS=150 NETWORK_ROUNDS=6 NETWORK_WARMUP=1 \
    NETWORK_CLIENTS=100 NETWORK_RESPONSE_BLOCKS=30 \
    bash run_network_smoke.sh
fi

# Write the final PASS status before calculating checksums; otherwise the
# manifest would hash a status file that changes after archive creation.
printf 'finalize_manifest\tPASS\t%s\n' "$(date -u +%s)" >> "$STATUS_FILE"
if ! python3 review/package_results.py --root "$ROOT" \
      --result-dir "$REVIEW_DIR" --profile "$MODE"; then
  sed -i '$d' "$STATUS_FILE"
  printf 'finalize_manifest\tFAIL\t%s\n' "$(date -u +%s)" >> "$STATUS_FILE"
  echo "Final archive failed; stage log files remain in $REVIEW_DIR." >&2
  exit 1
fi
echo "Review suite finished; files: $REVIEW_DIR"
echo "Results ZIP: ${REVIEW_DIR}.zip"
