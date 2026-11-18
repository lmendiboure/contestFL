#!/usr/bin/env bash
# One launch for v4 causal correction + 500-client scaling + 256-depth roots
# + late honest-challenge terminal outcomes + measured Flower/EVM policy replay.
# Does not repeat the historical v3 focused campaign.
set -Eeuo pipefail
export LC_ALL=C LANG=C
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-smoke}"
case "$MODE" in check|smoke|run) ;; *) echo 'Usage: ./review/run_v4_extended.sh check|smoke|run' >&2; exit 2;; esac
BASE_RUN_ID="${BASE_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
case "$BASE_RUN_ID" in ''|*[!a-zA-Z0-9_-]*) echo 'BASE_RUN_ID needs only letters/digits/-/_' >&2; exit 2;; esac
OUT="review_outputs/${BASE_RUN_ID}_v4_extended_${MODE}"
if [[ -e "$OUT" ]]; then echo "Refusing to overwrite measured outputs: $OUT" >&2; exit 2; fi
mkdir -p "$OUT/logs"
STATUS="$OUT/STAGE_STATUS.tsv"
printf 'stage\tstatus\tunix_utc\n' > "$STATUS"
step() {
  local name="$1" rc=0
  shift
  echo "### $name | $(date -u +%FT%TZ)"
  # The child writes its own log; output is tailed even on errors.
  "$@" >"$OUT/logs/$name.log" 2>&1 || rc=$?
  tail -n 18 "$OUT/logs/$name.log" || true
  printf '%s\t%s\t%s\n' "$name" "$( (( rc == 0 )) && echo PASS || echo FAIL_$rc )" "$(date -u +%s)" >> "$STATUS"
  if (( rc != 0 )); then
    echo "FAILED $name ($rc): see $OUT/logs/$name.log. Earlier measurements retained." >&2
    exit "$rc"
  fi
}
docker_tools() {
  docker compose --profile tools -f network/docker-compose.generated.yml run --rm tools "$@"
}
step local_v4extended_tests python3 -m unittest discover -s tests -p 'test_v4_extended.py' -v
step local_v4_tests python3 -m unittest discover -s tests -p 'test_causal_chain_v4.py' -v
step source_syntax bash -c 'bash -n review/run_v4_extended.sh && python3 -m py_compile review/flower_policy_replay.py review/consolidate_v4_extended.py review/late_challenge_flood.py review/causal_chain.py ml/flower_mnist_e2e.py'
if [[ "$MODE" == check ]]; then echo "CHECK PASSED. No blockchain results produced."; exit 0; fi
source scripts/common.sh
ensure_env_file "$ROOT"
for cmd in docker make python3; do require_command "$cmd"; done
if ! docker info >/dev/null 2>&1; then echo 'Docker daemon unavailable' >&2; exit 2; fi
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)"
export CHALLENGER_ACCOUNTS="${CHALLENGER_ACCOUNTS:-16}"
export BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000
step docker_preflight bash scripts/preflight.sh
# Tool image is immutable for these scripts: repository sources are bind-mounted.
if [[ "${EXT_REBUILD_TOOLS:-0}" == 1 ]] || ! docker image inspect "${TOOLS_IMAGE:-contestfl-eval-tools:local}" >/dev/null 2>&1; then
  step build_tools make tools
fi
NETEM_ACTIVE=0
cleanup() {
  if (( NETEM_ACTIVE )); then bash tools/netem.sh clear 4 >/dev/null 2>&1 || true; fi
  make down >/dev/null 2>&1 || true
}
trap cleanup EXIT
start_chain() {
  make down || true
  make network-clean
  # tools has already been built; do not rebuild on every bootstrap.
  make -o tools bootstrap VALIDATORS=4 BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000 CHALLENGER_ACCOUNTS="$CHALLENGER_ACCOUNTS"
  make up
  sleep "${STARTUP_WAIT_SECONDS:-5}"
  make status VALIDATORS=4
  make deploy
}
step network_and_contracts start_chain
if [[ "$MODE" == smoke ]]; then
  SPECS=("n10_d1024_r1")
else
  # n25/100/500 with constant update payload (16 KiB per client), plus
  # n100 with 1 MiB/client = 100 MiB total artifact sensitivity.
  SPECS=("n25_d4096_r8" "n100_d4096_r20" "n500_d4096_r6" "n100_d262144_r12")
  if [[ "${EXT_HEAVY_500MB:-0}" == 1 ]]; then SPECS+=("n500_d262144_r3"); fi
fi
for spec in "${SPECS[@]}"; do
  IFS=_ read -r n d r <<< "$spec"
  clients="${n#n}"; dim="${d#d}"; reps="${r#r}"
  dest="$OUT/scale/$spec"
  step "causal_${spec}" docker_tools python review/causal_chain.py \
    --validators 4 --clients "$clients" --rounds "$reps" --warmup 1 \
    --challenge-blocks "${EXT_WINDOW_BLOCKS:-11}" --response-blocks 120 --retry-budget 3 \
    --update-dim "$dim" --tag "${BASE_RUN_ID}_${spec}" --output-dir "$dest"
  step "analyze_${spec}" python3 review/analyze_causal_chain.py \
    --input "$dest/causal_chain_raw.csv" --output-dir "$OUT/scale_analysis/$spec"
done
# A real EVM 256-depth Merkle challenged path; distinct from a complete
# root-only recovery system. The smoke deliberately skips the large ablation.
if [[ "$MODE" == run && "${EXT_ROOT_DEPTH:-1}" == 1 ]]; then
  for depth in 32 256; do
    step "root_depth_${depth}" make root-only-benchmark VALIDATORS=4 CLIENTS=500 \
      ROOT_ONLY_ROUNDS="${EXT_ROOT_REPS:-3}" ROOT_ONLY_WARMUP=1 \
      ROOT_ONLY_WORKLOADS=bad_admission RESULT_DIR="$OUT/root_depth" \
      UPDATE_DIM=1024 SMT_DEPTH="$depth" CHALLENGE_BLOCKS=11 \
      RESPONSE_BLOCKS=120 RETRY_BUDGET=1 TAG="depth_d${depth}"
  done
  step root_depth_analysis docker_tools python bench/analyze_root_depth_sensitivity.py \
    --run-dir "$OUT/root_depth"
fi
# Timeout outcomes require *actual* expireChallenge receipts. Injecting a
# resolver outage is clearly labeled, while C1 coverage misses are separate.
if [[ "${EXT_TIMEOUTS:-1}" == 1 ]]; then
  if [[ "$MODE" == smoke ]]; then FLOODS=0,8; QUOTAS=0,1; ROUNDS=1
  else FLOODS="${EXT_FLOOD_COUNTS:-0,90,360}"; QUOTAS=0,1; ROUNDS="${EXT_FLOOD_REPS:-4}"; fi
  step late_challenges_and_timeouts docker_tools python review/late_challenge_flood.py \
    --validators 4 --flood-counts "$FLOODS" --quotas "$QUOTAS" \
    --rounds "$ROUNDS" --attacker-identities 4 --waves 3 \
    --challenge-blocks 40 --response-blocks "${EXT_RESPONSE_BLOCKS:-12}" \
    --lead-blocks 2 --resolver-timeout-probe --output-dir "$OUT/timeouts"
fi
# An actual Flower MNIST round is trained for each seed, then its IDENTICAL
# canonical artifacts are replayed under Eager and ContestFL on the same Besu.
if [[ "$MODE" == run && "${EXT_FLOWER:-1}" == 1 ]] || [[ "$MODE" == smoke && "${EXT_SMOKE_FLOWER:-0}" == 1 ]]; then
  export FLOWER_IMAGE="${FLOWER_IMAGE:-contestfl-flower-mnist:local}"
  if ! docker image inspect "$FLOWER_IMAGE" >/dev/null 2>&1; then
    step build_flower_image docker build -t "$FLOWER_IMAGE" -f Dockerfile.flower .
  fi
  mkdir -p ml/cache
  chmod a+rwx ml/cache
  F_REPS=1
  if [[ "$MODE" == run ]]; then F_REPS="${EXT_FLOWER_REPS:-3}"; fi
  for ((k=0;k<F_REPS;k++)); do
    seed=$((20261111 + 101*k))
    dest="$OUT/flower/seed_$seed"
    mkdir -p "$dest"
    step "flower_train_${seed}" docker run --rm -u "$(id -u):$(id -g)" \
      --network "${CONTROL_NETWORK_NAME:-contestfl-control-net}" \
      -e RPC_URL=http://node1:8545 -e HOME=/tmp \
      -v "$ROOT:/workspace" -v "$ROOT/ml/cache:/data" -w /workspace \
      "$FLOWER_IMAGE" python ml/flower_mnist_e2e.py --skip-chain \
      --clients "${EXT_FLOWER_CLIENTS:-4}" --samples-per-client "${EXT_FLOWER_SAMPLES:-128}" \
      --local-epochs 1 --seed "$seed" --data-dir /data --port 8087 \
      --output-dir "$dest"
    step "flower_policies_${seed}" docker_tools python review/flower_policy_replay.py \
      --flower-dir "$dest" --window-blocks "${EXT_WINDOW_BLOCKS:-11}" \
      --response-blocks 120 --output "$dest/paired_flower_policies.csv"
  done
fi
# Optional synthetic same-host P2P delay. Not a true multi-site deployment.
if [[ "$MODE" == run && "${EXT_NETEM:-1}" == 1 ]]; then
  mkdir -p "$OUT/netem"
  step netem_preflight make netem-preflight VALIDATORS=4
  NETEM_ACTIVE=1
  step netem_apply bash tools/netem.sh apply 4 "${EXT_NETEM_RTT_MS:-100}" 0
  step netem_probe bash tools/netem.sh probe 4 "${EXT_NETEM_RTT_MS:-100}" "$OUT/netem/network_probe.csv"
  step netem_causal_100 docker_tools python review/causal_chain.py \
    --validators 4 --clients 100 --rounds "${EXT_NETEM_REPS:-4}" --warmup 1 \
    --challenge-blocks "${EXT_WINDOW_BLOCKS:-11}" --response-blocks 120 --retry-budget 3 \
    --update-dim 4096 --tag "${BASE_RUN_ID}_netem_${EXT_NETEM_RTT_MS:-100}" \
    --output-dir "$OUT/netem/causal_chain"
  step netem_analyze python3 review/analyze_causal_chain.py \
    --input "$OUT/netem/causal_chain/causal_chain_raw.csv" --output-dir "$OUT/netem/analysis"
  step netem_clear bash tools/netem.sh clear 4
  NETEM_ACTIVE=0
fi
# Optional zero-cost reanalysis of verified *existing* 100-client v3 trials.
# Choose an explicit source via EXT_V3_RESULTS_DIR or auto-discover the most
# recent finished v3 package; never rerun or alter the archived v3 observations.
V3_SOURCE="${EXT_V3_RESULTS_DIR:-}"
if [[ -z "$V3_SOURCE" ]]; then
  V3_SOURCE="$(python3 - <<'PYFIND'
from pathlib import Path
import json
for d in sorted(Path('review_outputs').glob('*_v3_focused'),key=lambda p:p.stat().st_mtime,reverse=True):
    source=d/'paired_policies/sized/paired_policies_raw.csv'
    manifest=d/'REVIEW_RUN_MANIFEST.json'
    if source.is_file() and manifest.is_file():
        try:
            if json.loads(manifest.read_text()).get('completed_all_stages'):
                print(d);break
        except (ValueError,OSError):pass
PYFIND
)"
fi
if [[ -n "$V3_SOURCE" ]]; then
  V3_CSV="$V3_SOURCE/paired_policies/sized/paired_policies_raw.csv"
  if [[ ! -f "$V3_CSV" ]]; then echo "Missing v3 source: $V3_CSV" >&2; exit 2; fi
  step v3_fault_rate_sensitivity python3 review/fault_mix_from_v3.py \
    --source "$V3_CSV" --output-dir "$OUT/fault_mix_derived"
fi
step consolidate_extended_v4 python3 -m review.consolidate_v4_extended --run-dir "$OUT"
step shutdown_chain make down
# Record the closing status before hashing/archiving (status is checksummed).
printf 'finalize_manifest\tPASS\t%s\n' "$(date -u +%s)" >> "$STATUS"
if ! python3 review/package_results.py --root "$ROOT" --result-dir "$OUT" --profile extended >"$OUT/logs/finalize_manifest.log" 2>&1; then
  sed -i '$d' "$STATUS"
  printf 'finalize_manifest\tFAIL\t%s\n' "$(date -u +%s)" >> "$STATUS"
  cat "$OUT/logs/finalize_manifest.log" >&2
  exit 1
fi
cat "$OUT/logs/finalize_manifest.log"
printf '\nDONE: %s\nARCHIVE: %s.zip\n' "$OUT" "$OUT"
