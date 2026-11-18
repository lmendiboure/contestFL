#!/usr/bin/env bash
# Focused v4 causal-chain extension. Does NOT rerun v3 or replace v3 CSVs.
set -Eeuo pipefail
export LC_ALL=C LANG=C
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-smoke}"
case "$MODE" in check|smoke|run) ;; *) echo 'Usage: ./review/run_causal_v4.sh check|smoke|run' >&2; exit 2;; esac
BASE_RUN_ID="${BASE_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
case "$BASE_RUN_ID" in ''|*[!a-zA-Z0-9_-]*) echo 'BASE_RUN_ID requires letters/digits/-/_ only' >&2; exit 2;; esac
OUT="review_outputs/${BASE_RUN_ID}_v4_causal_${MODE}"
if [[ -e "$OUT" ]]; then
  echo "Refusing to overwrite previous results: $OUT" >&2
  exit 2
fi
mkdir -p "$OUT/logs"
STATUS="$OUT/STAGE_STATUS.tsv"
printf 'stage\tstatus\tunix_utc\n' > "$STATUS"
step() {
  local name="$1" rc=0; shift
  echo "### $name | $(date -u +%FT%TZ)" | tee "$OUT/logs/$name.log"
  "$@" >>"$OUT/logs/$name.log" 2>&1 || rc=$?
  tail -n 35 "$OUT/logs/$name.log"
  printf '%s\t%s\t%s\n' "$name" "$([[ $rc == 0 ]] && echo PASS || echo FAIL_$rc)" "$(date -u +%s)" >> "$STATUS"
  if (( rc != 0 )); then
    echo "FAILED $name ($rc): $OUT/logs/$name.log — raw measurements retained" >&2
    exit "$rc"
  fi
}
step review_v4_unit_tests python3 -m unittest discover -s tests -p test_causal_chain_v4.py -v
step review_v4_static bash -c 'bash -n review/run_causal_v4.sh && python3 -m py_compile review/causal_chain.py review/analyze_causal_chain.py review/deactivation_probe_v4.py'
if [[ "$MODE" == check ]]; then
  echo 'Static checks passed, no new blockchain observations.'
  exit 0
fi
source scripts/common.sh
ensure_env_file "$ROOT"
for cmd in docker make; do require_command "$cmd"; done
if ! docker info >/dev/null 2>&1; then echo 'Docker daemon unavailable' >&2; exit 1; fi
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)"
export CHALLENGER_ACCOUNTS="${CHALLENGER_ACCOUNTS:-16}"
export BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000
step docker_preflight bash scripts/preflight.sh
step build_tools make tools
cleanup() { make down >/dev/null 2>&1 || true; }
trap cleanup EXIT
start_chain() {
  make down
  make network-clean
  make bootstrap VALIDATORS=4 BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000 CHALLENGER_ACCOUNTS="$CHALLENGER_ACCOUNTS"
  make up
  sleep "${STARTUP_WAIT_SECONDS:-5}"
  make status VALIDATORS=4
  make deploy
}
step start_chain_30m start_chain
if [[ "$MODE" == run ]]; then
  REPS="${REVIEW_CHAIN_REPS:-20}"
  CLIENTS="${REVIEW_CHAIN_CLIENTS:-100}"
  DIM="${REVIEW_CHAIN_UPDATE_DIM:-262144}"
  WARMUP="${REVIEW_CHAIN_WARMUP:-1}"
else
  REPS=1 CLIENTS=10 DIM=1024 WARMUP=0
fi
WINDOW="${REVIEW_CHAIN_WINDOW_BLOCKS:-11}"
RESPONSE="${REVIEW_CHAIN_RESPONSE_BLOCKS:-120}"
for name in REPS CLIENTS DIM WINDOW RESPONSE; do
  if [[ ! "${!name}" =~ ^[0-9]+$ ]] || (( ${!name} < 1 )); then echo "Invalid $name=${!name}" >&2; exit 2; fi
done
if [[ ! "$WARMUP" =~ ^[0-9]+$ ]]; then echo 'WARMUP must be a nonnegative integer' >&2; exit 2; fi
if (( CLIENTS < 2 )); then echo 'CLIENTS must be >=2' >&2; exit 2; fi
# 3 on-chain corrections require 3 non-renewable publication retries.
step causal_chain_onchain docker compose --profile tools -f network/docker-compose.generated.yml run --rm tools \
  python review/causal_chain.py --validators 4 --clients "$CLIENTS" \
  --rounds "$REPS" --warmup "$WARMUP" --challenge-blocks "$WINDOW" \
  --response-blocks "$RESPONSE" --retry-budget 3 --update-dim "$DIM" \
  --tag "${BASE_RUN_ID}_v4_chain" --output-dir "$OUT/causal_chain"
step admit_to_reject_probe docker compose --profile tools -f network/docker-compose.generated.yml run --rm tools \
  python review/deactivation_probe_v4.py --challenge-blocks "$WINDOW" --output "$OUT/conformance/admit_to_reject.json"
step causal_chain_analysis python3 review/analyze_causal_chain.py \
  --input "$OUT/causal_chain/causal_chain_raw.csv" \
  --output-dir "$OUT/analysis"
step down_chain make down
# Record the final status *before* computing SHA-256 and archiving.  A generic
# step() here would modify STAGE_STATUS.tsv after packaging and invalidate its
# checksum; this is an explicitly integrity-safe finalization.
printf 'finalize_manifest\tPASS\t%s\n' "$(date -u +%s)" >> "$STATUS"
if ! python3 review/package_results.py --root "$ROOT" --result-dir "$OUT" --profile causal \
  >"$OUT/logs/finalize_manifest.log" 2>&1; then
  sed -i '$d' "$STATUS"
  printf 'finalize_manifest\tFAIL\t%s\n' "$(date -u +%s)" >> "$STATUS"
  cat "$OUT/logs/finalize_manifest.log" >&2
  exit 1
fi
cat "$OUT/logs/finalize_manifest.log"
printf '\nDONE: %s\nARCHIVE: %s.zip\n' "$OUT" "$OUT"
