#!/usr/bin/env bash
# ContestFL JISAS revision v3: focused replacement experiment suite.
# No 'paper' claim is made until fresh Besu receipts are checked by the author.
set -Eeuo pipefail
export LC_ALL=C LANG=C
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-smoke}"
case "$MODE" in check|smoke|focused) ;; *) echo "Usage: $0 check|smoke|focused" >&2; exit 2;; esac
BASE_RUN_ID="${BASE_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
case "$BASE_RUN_ID" in *[!a-zA-Z0-9_-]*|'') echo "BASE_RUN_ID must use only letters, digits, underscore or dash" >&2; exit 2;; esac
OUT="review_outputs/${BASE_RUN_ID}_v3_${MODE}"
STATUS="$OUT/STAGE_STATUS.tsv"
if [[ -e "$STATUS" ]]; then
  echo "Existing run with same BASE_RUN_ID: $OUT. Refusing to overwrite measured outputs." >&2
  exit 2
fi
mkdir -p "$OUT/logs"
printf 'stage\tstatus\tunix_utc\n' > "$STATUS"

step() {
  local label="$1"; shift
  echo "### $label | $(date -u +%FT%TZ)" | tee "$OUT/logs/$label.log"
  local rc=0
  "$@" >> "$OUT/logs/$label.log" 2>&1 || rc=$?
  cat "$OUT/logs/$label.log" | tail -n 45
  printf '%s\t%s\t%s\n' "$label" "$([[ "$rc" -eq 0 ]] && echo PASS || echo "FAIL_$rc")" "$(date -u +%s)" >> "$STATUS"
  if [[ "$rc" -ne 0 ]]; then
    echo "FAILED $label (code $rc); see $OUT/logs/$label.log; existing results retained" >&2
    exit "$rc"
  fi
}

finalize() {
  printf 'finalize_manifest\tPASS\t%s\n' "$(date -u +%s)" >> "$STATUS"
  if ! python3 review/package_results.py --root "$ROOT" --result-dir "$OUT" --profile "$MODE"; then
    sed -i '$d' "$STATUS"
    printf 'finalize_manifest\tFAIL\t%s\n' "$(date -u +%s)" >> "$STATUS"
    exit 1
  fi
  echo "RESULTS: $OUT; archive: $OUT.zip"
}

step host_repository_check bash scripts/check_repository.sh
step reference_window_check python3 review/window_sensitivity.py \
  --watcher-summary results/reference/summaries/watcher_extension/watcher_pipeline_summary.csv \
  --output-dir "$OUT/reference_window_only"
if [[ "$MODE" == check ]]; then
  echo 'Host-only validation: no Besu, no new blockchain measurements.'
  finalize
  exit 0
fi

source scripts/common.sh
ensure_env_file "$ROOT"
for cmd in docker make; do require_command "$cmd"; done
docker compose version >/dev/null
docker info >/dev/null || { echo 'Docker daemon unavailable' >&2; exit 1; }
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)"
export CHALLENGER_ACCOUNTS="${CHALLENGER_ACCOUNTS:-128}"
export BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000
step docker_preflight bash scripts/preflight.sh
step build_tools make tools

# The selected watcher size must correspond to the generated protocol payload.
# This is only a *model* linkage: the protocol benchmark does not send the
# generated payload over a WAN or object store.
SELECTED_UPDATE_DIM="${REVIEW_UPDATE_DIM:-262144}"
if [[ "$MODE" == focused ]]; then
  case "$SELECTED_UPDATE_DIM" in
    262144|2621440) ;; # 1MiB or 10MiB per client
    *) echo 'REVIEW_UPDATE_DIM must match a measured watcher size (262144 or 2621440 int32 values)' >&2; exit 2;;
  esac
  step fresh_watcher env \
    RUN_ID="${BASE_RUN_ID}_v3_watcher" WATCHER_CLIENTS=100 \
    WATCHER_UPDATE_BYTES=1048576,10485760 \
    WATCHER_ROUNDS="${WATCHER_ROUNDS:-30}" WATCHER_WARMUP=2 \
    WATCHER_CACHE_MODES=warm,fadvise WATCHER_RETAIN_DATASETS=0 \
    bash run_watcher_extension.sh
  mkdir -p "$OUT/fresh_watcher"
  cp "results/runs/${BASE_RUN_ID}_v3_watcher/watcher_pipeline_summary.csv" "$OUT/fresh_watcher/"
  cp "results/runs/${BASE_RUN_ID}_v3_watcher/watcher_pipeline_metadata.json" "$OUT/fresh_watcher/" 2>/dev/null || true
  step derive_window python3 review/window_sensitivity.py \
    --watcher-summary "$OUT/fresh_watcher/watcher_pipeline_summary.csv" \
    --primary-update-bytes "$((SELECTED_UPDATE_DIM * 4))" \
    --output-dir "$OUT/window_model"
else
  mkdir -p "$OUT/window_model"
  cp "$OUT/reference_window_only/"* "$OUT/window_model/"
  printf '%s\n' 'SMOKE ONLY: sized window comes from historical watcher rows; not a fresh measurement.' > "$OUT/window_model/SMOKE_NOT_NEW_EVIDENCE.txt"
fi
SIZED_WINDOW="$(python3 - "$OUT/window_model/recommended_window.json" <<'PY'
import json,sys
w=int(json.load(open(sys.argv[1]))['challenge_blocks'])
assert 2 <= w <= 100000, w
print(w)
PY
)"
WINDOW_RESPONSE="${REVIEW_RESPONSE_BLOCKS:-120}"
if [[ "$MODE" == focused ]]; then
  REPS="${REVIEW_REPS:-20}"
  NCLIENTS="${REVIEW_CLIENTS:-100}"
  WORKLOADS="${REVIEW_WORKLOADS:-clean,bad_admission,bad_aggregate}"
  SHORT_REPS="${REVIEW_SHORT_REPS:-6}"
  FLOOD_REPS="${REVIEW_FLOOD_REPS:-8}"
  FLOOD_COUNTS="${REVIEW_FLOOD_COUNTS:-0,90,360}"
  UPDATE_DIM="$SELECTED_UPDATE_DIM"  # 1/10MiB per client, not measured network transfer
else
  REPS=1 NCLIENTS=10 WORKLOADS='clean,bad_admission,bad_aggregate'
  SHORT_REPS=1 FLOOD_REPS=1 FLOOD_COUNTS='0,8'
  UPDATE_DIM=1024
fi
for var in REPS SHORT_REPS FLOOD_REPS UPDATE_DIM; do
  if [[ "${!var}" =~ ^[0-9]+$ ]] && (( ${!var} >= 1 )); then : ; else echo "Invalid $var" >&2; exit 2; fi
done

cleanup() { make down >/dev/null 2>&1 || true; }
trap cleanup EXIT
start_chain() {
  local gas="$1"
  make down
  make network-clean
  make bootstrap VALIDATORS=4 BLOCK_GAS_LIMIT="$gas" TARGET_GAS_LIMIT="$gas" CHALLENGER_ACCOUNTS="$CHALLENGER_ACCOUNTS"
  make up
  sleep "${STARTUP_WAIT_SECONDS:-5}"
  make status VALIDATORS=4
  make deploy
}
docker_python() {
  docker compose --profile tools -f network/docker-compose.generated.yml run --rm tools python "$@"
}

step start_chain_protocol_30m start_chain 30000000
step onchain_conformance make benchmark \
  VALIDATORS=4 CLIENTS=10 ROUNDS=1 WARMUP=0 \
  SCENARIOS='adversarial_moot_guard,review_quota_dedupe,concurrent_moot,bad_admission,correction_laundering' \
  CHALLENGE_BLOCKS=30 RESPONSE_BLOCKS=120 RETRY_BUDGET=2 \
  TAG=v3_conformance RESULT_DIR="$OUT/conformance"
step trust_boundary docker_python review/trust_boundary_probe.py \
  --output "$OUT/trust_boundary.json" --validators 4
step matched_policies_sized docker_python review/paired_policies.py \
  --validators 4 --clients "$NCLIENTS" --workloads "$WORKLOADS" \
  --rounds "$REPS" --warmup 1 --challenge-blocks "$SIZED_WINDOW" \
  --response-blocks "$WINDOW_RESPONSE" --retry-budget 2 --update-dim "$UPDATE_DIM" \
  --window-label sized --tag="${BASE_RUN_ID}_v3_sized" \
  --output-dir "$OUT/paired_policies/sized"
# Deliberate one-block diagnostic. Failures must be retained, not dismissed.
step matched_policies_short docker_python review/paired_policies.py \
  --validators 4 --clients "$NCLIENTS" --workloads 'clean,bad_admission' \
  --rounds "$SHORT_REPS" --warmup 0 --challenge-blocks 1 \
  --response-blocks "$WINDOW_RESPONSE" --retry-budget 2 --update-dim "$UPDATE_DIM" \
  --window-label short --tag="${BASE_RUN_ID}_v3_short" --allow-failures \
  --output-dir "$OUT/paired_policies/short"
step replace_existing_cost_latency python3 review/consolidate_focused_v3.py \
  --inputs "$OUT/paired_policies/sized/paired_policies_raw.csv" \
  "$OUT/paired_policies/short/paired_policies_raw.csv" \
  --output-dir "$OUT/paper_replacements"
step down_protocol make down

# The 5-Mgas network is a deliberately tighter capacity bound, not a new WAN.
step start_chain_capacity_5m start_chain 5000000
step honest_challenge_under_load docker_python review/late_challenge_flood.py \
  --validators 4 --rounds "$FLOOD_REPS" --flood-counts "$FLOOD_COUNTS" \
  --quotas '0,1' --waves 3 --attacker-identities 4 \
  --challenge-blocks 40 --response-blocks 120 \
  --output-dir "$OUT/robustness"
step down_capacity make down

# Flower integration is preserved as an optional independent check; this script
# creates its own Docker/Besu network and must never overlap the other stages.
if [[ "${REVIEW_RUN_FLOWER:-0}" == 1 ]]; then
  step optional_flower_e2e env RUN_ID="${BASE_RUN_ID}_v3_flower" bash run_flower_mnist_e2e.sh
  mkdir -p "$OUT/flower"
  cp -a "results/runs/${BASE_RUN_ID}_v3_flower/flower/." "$OUT/flower/"
fi
finalize
