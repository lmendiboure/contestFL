#!/usr/bin/env bash
# Resume a v4-extended `run` that failed at flower_policies_<seed>.
# Previously completed scale, root-depth, timeout and Flower training results
# remain untouched. A NEW four-validator chain is bootstrapped for the
# remaining EVM experiments. Earlier failed logs and statuses are retained.
set -Eeuo pipefail
export LC_ALL=C LANG=C
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ $# -ne 1 ]]; then
  echo "Usage: ./review/resume_v4_extended_flower.sh review_outputs/<original>_v4_extended_run" >&2
  exit 2
fi
OUT="${1%/}"
case "$OUT" in
  review_outputs/*_v4_extended_run) ;;
  *) echo 'Expected the ORIGINAL relative review_outputs/*_v4_extended_run directory' >&2; exit 2;;
esac
STATUS="$OUT/STAGE_STATUS.tsv"
if [[ ! -f "$STATUS" ]]; then echo "Missing original stage journal: $STATUS" >&2; exit 2; fi
if [[ -e "$OUT/REVIEW_RUN_MANIFEST.json" ]]; then
  echo 'A final manifest already exists; refusing to resume a packaged run.' >&2; exit 2
fi
failed_stage="$(awk -F '\t' 'NR>1 {stage=$1; status=$2} END {if (status ~ /^FAIL_/) print stage}' "$STATUS")"
if [[ ! "$failed_stage" =~ ^flower_policies_[0-9]+$ ]]; then
  echo "Last stage must be a failed flower_policies_<seed>, got: ${failed_stage:-none}" >&2
  exit 2
fi
failed_seed="${failed_stage#flower_policies_}"
# Strictly require all earlier stages to have passed; in particular, every
# already-measured causal stage must stay in place and must never be rerun.
python3 - "$STATUS" "$OUT" "$failed_stage" <<'PY'
import csv,sys
from pathlib import Path
status,out,failed = Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
rows=list(csv.DictReader(status.open(),delimiter='\t'))
assert rows and rows[-1]['stage']==failed and rows[-1]['status'].startswith('FAIL_'), 'journal does not end in expected failure'
assert all(r['status']=='PASS' for r in rows[:-1]), 'earlier stages not all successful: manual audit required'
assert any(r['stage'].startswith('causal_') for r in rows[:-1]), 'no completed causal results'
assert any(r['stage'].startswith('flower_train_') for r in rows[:-1]), 'no completed Flower training'
for r in rows[:-1]:
    name=r['stage']
    if name.startswith('causal_'):
        assert (out/'scale'/name.removeprefix('causal_')/'causal_chain_raw.csv').is_file(), f'missing original causal CSV for {name}'
    if name=='late_challenges_and_timeouts':
        assert (out/'timeouts'/'late_challenge_raw.csv').is_file(), 'missing timeout source'
    if name.startswith('flower_train_'):
        seed=name.removeprefix('flower_train_')
        assert (out/'flower'/f'seed_{seed}'/'FLOWER_ARTIFACT_REPORT.json').is_file(), f'missing Flower report for {seed}'
print(f'Original passed stages: {len(rows)-1}. Will preserve all completed measurements.')
PY

source scripts/common.sh
ensure_env_file "$ROOT"
for c in docker make python3; do require_command "$c"; done
if ! docker info >/dev/null 2>&1; then echo 'Docker daemon unavailable' >&2; exit 2; fi
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)"
export CHALLENGER_ACCOUNTS="${CHALLENGER_ACCOUNTS:-16}"
export BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000
mkdir -p "$OUT/logs"
NETEM_ACTIVE=0
RUN_LOCK="$OUT/.flower_resume_lock"
if ! mkdir "$RUN_LOCK" 2>/dev/null; then
  echo "A resumed process may already be running (lock exists at $RUN_LOCK)." >&2; exit 2
fi
cleanup() {
  if (( NETEM_ACTIVE )); then bash tools/netem.sh clear 4 >/dev/null 2>&1 || true; fi
  make down >/dev/null 2>&1 || true
  rmdir "$RUN_LOCK" 2>/dev/null || true
}
trap cleanup EXIT
step() {
  local name="$1" rc=0 previous n=1
  shift
  echo "### $name | $(date -u +%FT%TZ)"
  previous="$OUT/logs/$name.log"
  if [[ -e "$previous" ]]; then
    while [[ -e "$OUT/logs/${name}.previous_${n}.log" ]]; do n=$((n+1)); done
    mv "$previous" "$OUT/logs/${name}.previous_${n}.log"
  fi
  "$@" >"$previous" 2>&1 || rc=$?
  tail -n 18 "$previous" || true
  printf '%s\t%s\t%s\n' "$name" "$( ((rc==0)) && echo PASS || echo FAIL_$rc )" "$(date -u +%s)" >> "$STATUS"
  if (( rc != 0 )); then
    echo "FAILED $name ($rc): $previous; original measurements retained." >&2
    exit "$rc"
  fi
}
docker_tools() {
  docker compose --profile tools -f network/docker-compose.generated.yml run --rm tools "$@"
}
start_chain() {
  make down || true
  make network-clean
  make -o tools bootstrap VALIDATORS=4 BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000 CHALLENGER_ACCOUNTS="$CHALLENGER_ACCOUNTS"
  make up
  sleep "${STARTUP_WAIT_SECONDS:-5}"
  make status VALIDATORS=4
  make deploy
}
# This is a different fresh QBFT chain instance than the one used by the
# original, already archived scaling/timeout runs. Never merge their block IDs.
if ! docker image inspect "${TOOLS_IMAGE:-contestfl-eval-tools:local}" >/dev/null 2>&1; then
  step resume_build_tools make tools
fi
step resume_network_and_contracts start_chain

export FLOWER_IMAGE="${FLOWER_IMAGE:-contestfl-flower-mnist:local}"
if ! docker image inspect "$FLOWER_IMAGE" >/dev/null 2>&1; then
  step resume_build_flower_image docker build -t "$FLOWER_IMAGE" -f Dockerfile.flower .
fi
mkdir -p ml/cache
chmod a+rwx ml/cache
F_REPS="${EXT_FLOWER_REPS:-3}"
[[ "$F_REPS" =~ ^[1-9][0-9]*$ ]] || { echo 'EXT_FLOWER_REPS must be a positive integer' >&2; exit 2; }
seen_failed=0
for ((k=0; k<F_REPS; k++)); do
  seed=$((20261111 + 101*k))
  dest="$OUT/flower/seed_$seed"
  mkdir -p "$dest"
  if [[ "${seen_failed}" == 0 && "$seed" != "$failed_seed" ]]; then
    if ! grep -q $'^flower_policies_'"$seed"$'\tPASS\t' "$STATUS"; then
      echo "Missing expected successful Flower policy run before seed $failed_seed (seed $seed)" >&2
      exit 2
    fi
    if [[ ! -s "$dest/paired_flower_policies.csv" ]]; then echo "Missing saved Flower result for $seed" >&2; exit 2; fi
    echo "REUSE completed Flower policy seed $seed"
    continue
  fi
  if [[ "$seed" == "$failed_seed" ]]; then seen_failed=1; fi
  if [[ ! -f "$dest/FLOWER_ARTIFACT_REPORT.json" ]]; then
    step "flower_train_${seed}" docker run --rm -u "$(id -u):$(id -g)" \
      --network "${CONTROL_NETWORK_NAME:-contestfl-control-net}" \
      -e RPC_URL=http://node1:8545 -e HOME=/tmp \
      -v "$ROOT:/workspace" -v "$ROOT/ml/cache:/data" -w /workspace \
      "$FLOWER_IMAGE" python ml/flower_mnist_e2e.py --skip-chain \
      --clients "${EXT_FLOWER_CLIENTS:-4}" --samples-per-client "${EXT_FLOWER_SAMPLES:-128}" \
      --local-epochs 1 --seed "$seed" --data-dir /data --port 8087 \
      --output-dir "$dest"
  else
    echo "REUSE previously measured Flower training for seed $seed"
  fi
  if [[ -e "$dest/paired_flower_policies.csv" ]]; then
    echo "Refusing to overwrite existing Flower policy CSV: $dest/paired_flower_policies.csv" >&2
    exit 2
  fi
  step "flower_policies_${seed}" docker_tools python review/flower_policy_replay.py \
    --flower-dir "$dest" --window-blocks "${EXT_WINDOW_BLOCKS:-11}" \
    --response-blocks 120 --output "$dest/paired_flower_policies.csv"
done
if [[ "$seen_failed" != 1 ]]; then
  echo "Failed seed $failed_seed is not included in EXT_FLOWER_REPS=$F_REPS; refuse partial resumption" >&2
  exit 2
fi

if [[ "${EXT_NETEM:-1}" == 1 ]]; then
  if grep -q $'^netem_apply\tPASS\t' "$STATUS"; then
    echo 'Netem was already measured in a previous attempt; manual audit needed.' >&2; exit 2
  fi
  mkdir -p "$OUT/netem"
  step netem_preflight make netem-preflight VALIDATORS=4
  NETEM_ACTIVE=1
  step netem_apply bash tools/netem.sh apply 4 "${EXT_NETEM_RTT_MS:-100}" 0
  step netem_probe bash tools/netem.sh probe 4 "${EXT_NETEM_RTT_MS:-100}" "$OUT/netem/network_probe.csv"
  step netem_causal_100 docker_tools python review/causal_chain.py \
    --validators 4 --clients 100 --rounds "${EXT_NETEM_REPS:-4}" --warmup 1 \
    --challenge-blocks "${EXT_WINDOW_BLOCKS:-11}" --response-blocks 120 --retry-budget 3 \
    --update-dim 4096 --tag "${OUT##*/}_resumed_netem_${EXT_NETEM_RTT_MS:-100}" \
    --output-dir "$OUT/netem/causal_chain"
  step netem_analyze python3 review/analyze_causal_chain.py \
    --input "$OUT/netem/causal_chain/causal_chain_raw.csv" --output-dir "$OUT/netem/analysis"
  step netem_clear bash tools/netem.sh clear 4
  NETEM_ACTIVE=0
fi

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
# Record that multiple chain instances contribute independent runs.
python3 - "$OUT" "$failed_seed" <<'PY'
import json,sys
from pathlib import Path
out,seed=Path(sys.argv[1]),sys.argv[2]
(out/'RESUME_PROVENANCE.json').write_text(json.dumps({
  'reason':'Python IndexError when printing an empty error string after measured EVM execution',
  'retry_stage':'flower_policies_'+seed,
  'prior_attempts_preserved':'STAGE_STATUS.tsv and logs/*.previous_N.log',
  'reused_data':'all earlier successful causal scaling/root depth/timeouts and Flower training data',
  'new_network':'new four-validator Besu/QBFT instance for Flower policies and Netem experiments',
  'comparison_scope':'separate per-experiment blockchain instances; do not compare absolute block heights',
}, indent=2)+'\n')
PY
printf 'finalize_manifest\tPASS\t%s\n' "$(date -u +%s)" >> "$STATUS"
if ! python3 review/package_results.py --root "$ROOT" --result-dir "$OUT" --profile extended >"$OUT/logs/finalize_manifest.log" 2>&1; then
  sed -i '$d' "$STATUS"
  printf 'finalize_manifest\tFAIL\t%s\n' "$(date -u +%s)" >> "$STATUS"
  cat "$OUT/logs/finalize_manifest.log" >&2
  exit 1
fi
cat "$OUT/logs/finalize_manifest.log"
printf '\nDONE: %s\nARCHIVE: %s.zip\n' "$OUT" "$OUT"
