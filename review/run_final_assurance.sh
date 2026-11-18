#!/usr/bin/env bash
# One final Besu campaign: new Solidity liveness conformance/gas audit plus
# independent off-chain level cascade on the *same corrected* on-chain substrate.
# Does NOT rerun earlier v3/v4 or Flower multi-round campaigns.
set -Eeuo pipefail
export LC_ALL=C LANG=C
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-check}"
case "$MODE" in check|smoke|run) ;; *) echo 'usage: run_final_assurance.sh check|smoke|run' >&2; exit 2;; esac
step_check() {
 python3 -m unittest discover -s tests -p 'test_independent_level_cascade.py' -v
 python3 -m unittest discover -s tests -p 'test_termination_liveness_extension.py' -v
 python3 -m unittest discover -s tests -p 'test_termination_conformance.py' -v
 python3 -m unittest discover -s tests -p 'test_final_assurance.py' -v
 python3 -m py_compile review/independent_level_cascade.py review/cascade_runtime.py \
  review/compare_cascade_onchain.py review/analyze_final_assurance.py review/termination_liveness_probe.py
 bash -n review/run_final_assurance.sh
}
step_check
if [[ "$MODE" == check ]]; then echo 'CHECK PASS: no blockchain test run'; exit 0; fi
BASE_RUN_ID="${BASE_RUN_ID:-final_$(date -u +%Y%m%dT%H%M%S)}"
case "$BASE_RUN_ID" in ''|*[!a-zA-Z0-9_-]*) echo 'invalid BASE_RUN_ID' >&2; exit 2;; esac
OUT="review_outputs/${BASE_RUN_ID}_final_assurance_${MODE}"
if [[ -e "$OUT" || -e "${OUT}.zip" ]]; then echo "Refusing overwrite: $OUT" >&2; exit 2; fi
for executable in docker make python3; do command -v "$executable" >/dev/null || { echo "missing $executable" >&2; exit 2; }; done
docker info >/dev/null || { echo 'Docker unavailable' >&2; exit 2; }
if docker ps --format '{{.Names}}' | grep -Eq '^contestfl-eval-node[0-9]+-1$'; then
 echo 'Existing ContestFL network detected. Stop/finish it first.' >&2; exit 2;
fi
mkdir -p "$OUT/logs"
STATUS="$OUT/STAGE_STATUS.tsv"
printf 'stage\tstatus\tutc\n' > "$STATUS"
step() {
 local stage="$1" rc=0;shift
 echo "### $stage | $(date -u +%FT%TZ)"
 "$@" >"$OUT/logs/$stage.log" 2>&1 || rc=$?
 tail -n 24 "$OUT/logs/$stage.log" || true
 printf '%s\t%s\t%s\n' "$stage" "$([[ $rc == 0 ]] && echo PASS || echo FAIL_$rc)" "$(date -u +%FT%TZ)" >> "$STATUS"
 if (( rc != 0 )); then echo "FAILED $stage ($rc); original and completed outputs retained in $OUT" >&2; exit "$rc"; fi
}
source scripts/common.sh
ensure_env_file "$ROOT"
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)" CHALLENGER_ACCOUNTS="${CHALLENGER_ACCOUNTS:-16}"
export BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000
if [[ "${FINAL_REBUILD_TOOLS:-0}" == 1 ]] || ! docker image inspect "${TOOLS_IMAGE:-contestfl-eval-tools:local}" >/dev/null 2>&1; then
 step build_tools make tools
fi
cleanup() { make down >/dev/null 2>&1 || true; }
trap cleanup EXIT
start_chain() {
 make down >/dev/null 2>&1 || true
 make network-clean
 make -o tools bootstrap VALIDATORS=4 BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000 CHALLENGER_ACCOUNTS="$CHALLENGER_ACCOUNTS"
 make up
 sleep "${STARTUP_WAIT_SECONDS:-5}"
 make status VALIDATORS=4
 make deploy
}
step start_clean_besu start_chain
docker_tools() { docker compose --profile tools -f network/docker-compose.generated.yml run --rm tools "$@"; }
# Validation of old-vs-new bytecode and both missing timeout transitions.
step liveness_probe docker_tools python review/termination_liveness_probe.py --output "$OUT/liveness/liveness_probe.json"
if [[ "$MODE" == smoke ]]; then
 SPECS=("n10_r1_chain" "n10_r1_clean")
else
 SPECS=("n25_r5_chain" "n100_r10_chain" "n500_r5_chain" "n100_r5_clean")
fi
for spec in "${SPECS[@]}"; do
 IFS=_ read -r n r workload <<<"$spec"
 clients="${n#n}";reps="${r#r}"
 step "compare_${spec}" docker_tools python review/compare_cascade_onchain.py \
   --clients "$clients" --rounds "$reps" --warmup 0 --workload "$workload" \
   --update-dim "${FINAL_UPDATE_DIM:-4096}" --seed 20261112 \
   --challenge-blocks 11 --response-blocks 120 --retry-budget 3 \
   --output-dir "$OUT/cascade/$spec" --tag "${BASE_RUN_ID}_${spec}"
done
step analyze python3 review/analyze_final_assurance.py --result-dir "$OUT"
step stop_network make down
trap - EXIT
# Final status recorded before checksums to keep manifest stable after creation.
printf 'finalize\tPASS\t%s\n' "$(date -u +%FT%TZ)" >> "$STATUS"
python3 - "$OUT" <<'PY'
from pathlib import Path
import hashlib,json,sys,zipfile
root=Path(sys.argv[1]); source=Path.cwd()
source_files=[source/'contracts/ContestFLExperiment.sol',source/'review/independent_level_cascade.py',
              source/'review/cascade_runtime.py',source/'review/compare_cascade_onchain.py',
              source/'review/termination_liveness_probe.py']
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
files={str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and p.name!='MANIFEST.json'}
manifest={'profile':'final-assurance-v1','complete':True,'files_sha256':files,
          'source_sha256':{str(p.relative_to(source)):sha(p) for p in source_files},
          'source_git_commit':None}
(root/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
with zipfile.ZipFile(root.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(root.rglob('*')):
  if p.is_file():z.write(p,arcname=str(p.relative_to(root.parent)))
print('DONE',root,'ARCHIVE',root.with_suffix('.zip'))
PY
