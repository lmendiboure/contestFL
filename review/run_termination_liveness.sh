#!/usr/bin/env bash
# Standalone liveness/conformance probe. NEVER run alongside another ContestFL
# benchmark: it prepares its own QBFT chain and must keep old measurements intact.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-check}"
case "$MODE" in check|smoke) ;; *) echo 'Usage: ./review/run_termination_liveness.sh check|smoke' >&2; exit 2;; esac
python3 -m unittest discover -s tests -p 'test_termination_liveness_extension.py' -v
python3 -m py_compile review/termination_liveness_probe.py
bash -n review/run_termination_liveness.sh
if [[ "$MODE" == check ]]; then echo 'LOCAL CHECK PASS (no EVM execution)'; exit 0; fi
for bin in docker make python3; do command -v "$bin" >/dev/null || { echo "missing: $bin" >&2; exit 2; }; done
docker info >/dev/null || { echo 'Docker unavailable' >&2; exit 2; }
if docker ps --format '{{.Names}}' | grep -Eq '^contestfl-eval-node[0-9]+-1$'; then
  echo 'Refusing to stop an existing ContestFL network. Finish multi-round first.' >&2
  exit 2
fi
BASE_RUN_ID="${BASE_RUN_ID:-term_$(date -u +%Y%m%dT%H%M%S)}"
case "$BASE_RUN_ID" in ''|*[!a-zA-Z0-9_-]*) echo 'invalid BASE_RUN_ID' >&2; exit 2;; esac
OUT="review_outputs/${BASE_RUN_ID}_termination_liveness"
if [[ -e "$OUT" ]]; then echo "Refusing overwrite: $OUT" >&2; exit 2; fi
mkdir -p "$OUT/logs"
STATUS="$OUT/STAGE_STATUS.tsv"
printf 'stage\tstatus\n' > "$STATUS"
step() {
  local name="$1" rc=0; shift
  echo "### $name | $(date -u +%FT%TZ)"
  "$@" > "$OUT/logs/$name.log" 2>&1 || rc=$?
  tail -n 25 "$OUT/logs/$name.log" || true
  printf '%s\t%s\n' "$name" "$( ((rc == 0)) && echo PASS || echo FAIL_$rc )" >> "$STATUS"
  if ((rc != 0)); then echo "FAILED $name, code=$rc; see $OUT/logs/$name.log" >&2; exit "$rc"; fi
}
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)"
if [[ ! -f .env ]]; then cp .env.example .env; fi
if ! docker image inspect "${TOOLS_IMAGE:-contestfl-eval-tools:local}" >/dev/null 2>&1; then
  step build_tools make tools
fi
cleanup() { make down >/dev/null 2>&1 || true; }
trap cleanup EXIT
step bootstrap make -o tools bootstrap VALIDATORS=4
step up make up
step status make status VALIDATORS=4
step deploy make deploy
step probe docker compose --profile tools -f network/docker-compose.generated.yml run --rm tools \
  python review/termination_liveness_probe.py --output "$OUT/liveness_probe.json"
step down make down
trap - EXIT
printf 'finalize\tPASS\n' >> "$STATUS"
python3 - "$OUT" <<'PY'
from pathlib import Path
import hashlib,sys,json
p=Path(sys.argv[1]); files={}
for f in sorted(p.rglob('*')):
    if f.is_file() and f.name!='MANIFEST.json':
        files[str(f.relative_to(p))]=hashlib.sha256(f.read_bytes()).hexdigest()
(p/'MANIFEST.json').write_text(json.dumps({'profile':'termination-liveness','status':'PASS',
    'source_sha256':hashlib.sha256(Path('contracts/ContestFLExperiment.sol').read_bytes()).hexdigest(),
    'files':files},indent=2)+'\n')
PY
python3 - "$OUT" <<'PY'
from pathlib import Path
import sys,zipfile
out=Path(sys.argv[1]); dst=out.with_suffix('.zip')
with zipfile.ZipFile(dst,'w',compression=zipfile.ZIP_DEFLATED) as z:
  for p in sorted(out.rglob('*')):
    if p.is_file(): z.write(p,arcname=str(p.relative_to(out.parent)))
print('DONE:',out,'\nARCHIVE:',dst)
PY
