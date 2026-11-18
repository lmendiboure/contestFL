#!/usr/bin/env bash
# Resume ONLY a v4 extended campaign stopped at netem_preflight after Flower.
# A fresh Besu network is used; all previously completed measurements are retained.
set -Eeuo pipefail
export LC_ALL=C LANG=C
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ $# -ne 1 ]]; then
  echo "Usage: ./review/resume_v4_extended_netem.sh review_outputs/<original>_v4_extended_run" >&2
  exit 2
fi
OUT="${1%/}"
case "$OUT" in review_outputs/*_v4_extended_run) ;; *) echo 'Unexpected result directory' >&2; exit 2 ;; esac
STATUS="$OUT/STAGE_STATUS.tsv"
python3 -m review.netem_resume_state "$OUT" --flower-reps "${EXT_FLOWER_REPS:-3}"

source scripts/common.sh
ensure_env_file "$ROOT"
for command in docker make python3; do require_command "$command"; done
if ! docker info >/dev/null 2>&1; then echo 'Docker daemon unavailable' >&2; exit 2; fi
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)"
export CHALLENGER_ACCOUNTS="${CHALLENGER_ACCOUNTS:-16}"
export BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000
mkdir -p "$OUT/logs" "$OUT/netem"
LOCK="$OUT/.netem_resume_lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo 'Netem resume lock exists: another resume may be running.' >&2; exit 2
fi
NETEM_ACTIVE=0
cleanup() {
  if (( NETEM_ACTIVE )); then bash tools/netem.sh clear 4 >/dev/null 2>&1 || true; fi
  make down >/dev/null 2>&1 || true
  rmdir "$LOCK" 2>/dev/null || true
}
trap cleanup EXIT
step() {
  local stage="$1" rc=0 prior n=1
  shift
  echo "### $stage | $(date -u +%FT%TZ)"
  prior="$OUT/logs/$stage.log"
  if [[ -e "$prior" ]]; then
    while [[ -e "$OUT/logs/${stage}.previous_${n}.log" ]]; do n=$((n+1)); done
    mv "$prior" "$OUT/logs/${stage}.previous_${n}.log"
  fi
  "$@" >"$prior" 2>&1 || rc=$?
  tail -n 18 "$prior" || true
  printf '%s\t%s\t%s\n' "$stage" "$( ((rc==0)) && echo PASS || echo FAIL_$rc )" "$(date -u +%s)" >> "$STATUS"
  if (( rc != 0 )); then
    echo "FAILED $stage ($rc): $prior; previously measured CSVs remain untouched." >&2
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
if ! docker image inspect "${TOOLS_IMAGE:-contestfl-eval-tools:local}" >/dev/null 2>&1; then
  step resume_netem_build_tools make tools
fi
step resume_netem_network_and_contracts start_chain
step netem_preflight make netem-preflight VALIDATORS=4
NETEM_ACTIVE=1
step netem_apply bash tools/netem.sh apply 4 "${EXT_NETEM_RTT_MS:-100}" 0
step netem_probe bash tools/netem.sh probe 4 "${EXT_NETEM_RTT_MS:-100}" "$OUT/netem/network_probe.csv"
step netem_causal_100 docker_tools python review/causal_chain.py \
  --validators 4 --clients 100 --rounds "${EXT_NETEM_REPS:-4}" --warmup 1 \
  --challenge-blocks "${EXT_WINDOW_BLOCKS:-11}" --response-blocks 120 --retry-budget 3 \
  --update-dim 4096 --tag "${OUT##*/}_netem_resumed_${EXT_NETEM_RTT_MS:-100}" \
  --output-dir "$OUT/netem/causal_chain"
step netem_analyze python3 review/analyze_causal_chain.py \
  --input "$OUT/netem/causal_chain/causal_chain_raw.csv" --output-dir "$OUT/netem/analysis"
step netem_clear bash tools/netem.sh clear 4
NETEM_ACTIVE=0

V3_SOURCE="${EXT_V3_RESULTS_DIR:-}"
if [[ -z "$V3_SOURCE" ]]; then
  V3_SOURCE="$(python3 - <<'PYFIND'
from pathlib import Path
import json
for d in sorted(Path('review_outputs').glob('*_v3_focused'), key=lambda p:p.stat().st_mtime, reverse=True):
    source=d/'paired_policies/sized/paired_policies_raw.csv'
    manifest=d/'REVIEW_RUN_MANIFEST.json'
    if source.is_file() and manifest.is_file():
        try:
            if json.loads(manifest.read_text()).get('completed_all_stages'):
                print(d);break
        except (ValueError,OSError): pass
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
python3 - "$OUT" <<'PY'
import json,sys
from pathlib import Path
out=Path(sys.argv[1])
(out/'RESUME_PROVENANCE.json').write_text(json.dumps({
    'previous_failures': ['flower_policies_20261111: print of empty error string',
                          'netem_preflight: tools/netem.sh lacked execute permission'],
    'reused_data':'all successful causal/scale, Merkle, timeout, Flower training and Flower policy observations',
    'netem_chain':'fresh Besu/QBFT four-validator instance; not the same chain as earlier experiments',
    'valid_comparisons':'per-run gas/latency, not cross-chain absolute block heights',
    'attempts':'original and resumed attempt rows retained in STAGE_STATUS.tsv'},indent=2)+'\n')
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
