#!/usr/bin/env bash
# Isolated, sequential Flower multi-round FL evaluation, distinct from v4.
# 2 policies x 5 seeds x 20 real Flower rounds; never reuses one-round artifacts.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-check}"
case "$MODE" in check|smoke|run) ;; *) echo "Usage: $0 check|smoke|run" >&2; exit 2;; esac
if [[ "$MODE" == check ]]; then
  python3 -m unittest discover -s tests -p 'test_multiround_flower.py' -v
  python3 -m py_compile review/multiround_flower.py ml/multiround_state.py ml/flower_mnist_e2e.py
  bash -n "$0"
  exit 0
fi
BASE_RUN_ID="${BASE_RUN_ID:-multiround_$(date -u +%Y%m%dT%H%M%SZ)}"
case "$BASE_RUN_ID" in ''|*[!a-zA-Z0-9_-]*) echo 'Invalid BASE_RUN_ID' >&2; exit 2;; esac
OUT="review_outputs/${BASE_RUN_ID}_flower_multiround_${MODE}"
if [[ -e "$OUT" ]]; then echo "Refusing to overwrite: $OUT" >&2; exit 2; fi
mkdir -p "$OUT/logs"
OUT="$(realpath "$OUT")"
printf 'stage\tstatus\tUTC\n' > "$OUT/STAGE_STATUS.tsv"
step() {
  local label="$1"; shift
  echo "### $label | $(date -u +%FT%TZ)"
  local rc=0
  "$@" >"$OUT/logs/${label}.log" 2>&1 || rc=$?
  tail -n 12 "$OUT/logs/${label}.log" || true
  printf '%s\t%s\t%s\n' "$label" "$([[ $rc -eq 0 ]] && echo PASS || echo FAIL_$rc)" "$(date -u +%FT%TZ)" >> "$OUT/STAGE_STATUS.tsv"
  if [[ $rc -ne 0 ]]; then echo "FAILED $label; results retained: $OUT" >&2; exit "$rc"; fi
}
step offline_checks "$0" check
source scripts/common.sh
ensure_env_file "$ROOT"
for cmd in docker make python3; do require_command "$cmd"; done
if ! docker info >/dev/null 2>&1; then echo 'Docker unavailable' >&2; exit 2; fi
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)"
export BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000
if ! docker image inspect "${TOOLS_IMAGE:-contestfl-eval-tools:local}" >/dev/null 2>&1; then
  step build_tools make tools
fi
FLOWER_IMAGE="${FLOWER_IMAGE:-contestfl-flower-mnist:local}"
if ! docker image inspect "$FLOWER_IMAGE" >/dev/null 2>&1; then
  step build_flower docker build -t "$FLOWER_IMAGE" -f Dockerfile.flower .
fi
mkdir -p ml/cache
chmod a+rwx ml/cache
cleanup() { make down >/dev/null 2>&1 || true; }
trap cleanup EXIT
start_chain() {
  make down || true
  make network-clean
  make -o tools bootstrap VALIDATORS=4 BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000 CHALLENGER_ACCOUNTS=16
  make up
  sleep "${STARTUP_WAIT_SECONDS:-5}"
  make status VALIDATORS=4
  make deploy
}
if [[ "$MODE" == smoke ]]; then
  SEEDS=(20261201); ROUNDS=2; FAULTS=2
else
  SEEDS=(20261201 20261302 20261403 20261504 20261605); ROUNDS=20; FAULTS=6,13,19
fi
# Alternate order per seed to reduce the systematic warm-host confound.
for idx in "${!SEEDS[@]}"; do
  seed="${SEEDS[$idx]}"
  if ((idx % 2 == 0)); then POLICIES=(contestfl eager_full)
  else POLICIES=(eager_full contestfl); fi
  for policy in "${POLICIES[@]}"; do
    tag="s${seed}_${policy}"
    step "network_${tag}" start_chain
    dest="review_outputs/${BASE_RUN_ID}_flower_multiround_${MODE}/trajectories/$tag"
    step "trajectory_${tag}" docker run --rm -u "$(id -u):$(id -g)" \
      --network "${CONTROL_NETWORK_NAME:-contestfl-control-net}" \
      -e RPC_URL=http://node1:8545 -e HOME=/tmp \
      -v "$ROOT:/workspace" -v "$ROOT/ml/cache:/data" \
      -w /workspace "$FLOWER_IMAGE" python review/multiround_flower.py \
      --policy "$policy" --seed "$seed" --rounds "$ROUNDS" \
      --fault-rounds "$FAULTS" --clients 2 --samples-per-client 128 \
      --window-blocks 11 --response-blocks 120 --data-dir /data \
      --output-dir "$dest"
    step "down_${tag}" make down
  done
done
step aggregate python3 review/analyze_flower_multiround.py --run-dir "$OUT"
step package python3 review/package_multiround.py --run-dir "$OUT"
printf '\nDONE: %s\n' "$OUT"
