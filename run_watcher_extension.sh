#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
ensure_env_file "$ROOT"
require_command docker
require_command make
PYTHON_BIN="$(resolve_python)"
docker info >/dev/null 2>&1 || { echo "Docker daemon is not reachable." >&2; exit 1; }

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_watcher_extension}"
RESULT_DIR="${RESULT_DIR:-results/runs/${RUN_ID}}"
DATASET_DIR="${WATCHER_DATASET_DIR:-results/cache/watcher_datasets}"
WATCHER_CLIENTS="${WATCHER_CLIENTS:-100}"
WATCHER_UPDATE_BYTES="${WATCHER_UPDATE_BYTES:-1048576,10485760}"
WATCHER_ROUNDS="${WATCHER_ROUNDS:-30}"
WATCHER_WARMUP="${WATCHER_WARMUP:-2}"
WATCHER_CACHE_MODES="${WATCHER_CACHE_MODES:-warm,fadvise}"
WATCHER_BOOTSTRAP_SAMPLES="${WATCHER_BOOTSTRAP_SAMPLES:-10000}"
WATCHER_RETAIN_DATASETS="${WATCHER_RETAIN_DATASETS:-1}"
WATCHER_RESUME="${WATCHER_RESUME:-0}"

mkdir -p "$RESULT_DIR"
if [[ "$WATCHER_RESUME" != "1" ]]; then
  free_kb="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
  if [[ "${free_kb:-0}" -lt 3145728 ]]; then
    echo "At least 3 GiB free space is required for the 1,000 MiB watcher dataset." >&2
    exit 1
  fi
fi

make tools

DOCKER_ARGS=(
  docker run --rm --env-file .env
  -e MPLCONFIGDIR=/tmp/matplotlib
  -u "$(id -u):$(id -g)"
  -v "$ROOT:/workspace" -w /workspace
  "${TOOLS_IMAGE:-contestfl-eval-tools:local}"
)

retain_arg=()
if [[ "$WATCHER_RETAIN_DATASETS" == "1" ]]; then
  retain_arg=(--retain-datasets)
fi

if [[ "$WATCHER_RESUME" == "1" ]]; then
  for required in watcher_pipeline_raw.csv watcher_pipeline_summary.csv; do
    if [[ ! -s "$RESULT_DIR/$required" ]]; then
      echo "WATCHER_RESUME=1 requested, but $RESULT_DIR/$required is missing or empty." >&2
      exit 1
    fi
  done
  echo "=== Resuming watcher post-processing from: $RESULT_DIR ==="
else
  echo "=== Watcher pipeline: ${WATCHER_ROUNDS} retained repetitions per size and cache mode ==="
  "${DOCKER_ARGS[@]}" python bench/watcher_pipeline.py \
    --clients "$WATCHER_CLIENTS" \
    --update-bytes "$WATCHER_UPDATE_BYTES" \
    --rounds "$WATCHER_ROUNDS" \
    --large-rounds "$WATCHER_ROUNDS" \
    --huge-rounds "$WATCHER_ROUNDS" \
    --warmup "$WATCHER_WARMUP" \
    --cache-modes "$WATCHER_CACHE_MODES" \
    --bootstrap-samples "$WATCHER_BOOTSTRAP_SAMPLES" \
    --dataset-dir "$DATASET_DIR" \
    --run-dir "$RESULT_DIR" \
    "${retain_arg[@]}"
fi

# Recompute the C1 projection when a replay summary is supplied or can be found.
REPLAY_SUMMARY="${REPLAY_SUMMARY:-}"
if [[ -z "$REPLAY_SUMMARY" ]]; then
  REPLAY_SUMMARY="$(find results -type f -name replay_scaling_summary.csv -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1 {$1=""; sub(/^ /,""); print}' || true)"
fi
# The reference artifact stores retained replay summaries inside campaign ZIPs.
# Extract the targeted-extension summary automatically when no fresh unpacked
# replay result is available, so the watcher run remains self-contained.
if [[ -z "$REPLAY_SUMMARY" ]]; then
  reference_archive="results/reference/archives/targeted_extension.zip"
  if [[ -f "$reference_archive" ]]; then
    extracted_replay="$RESULT_DIR/reference_replay_scaling_summary.csv"
    "$PYTHON_BIN" - <<PY2
from pathlib import Path
from zipfile import ZipFile
archive = Path(${reference_archive@Q})
out = Path(${extracted_replay@Q})
with ZipFile(archive) as zf:
    candidates = [n for n in zf.namelist() if n.endswith("replay_scaling_summary.csv")]
    if len(candidates) != 1:
        raise SystemExit(f"expected one replay summary in {archive}, found {candidates}")
    out.write_bytes(zf.read(candidates[0]))
print(out)
PY2
    REPLAY_SUMMARY="$extracted_replay"
  fi
fi
if [[ -n "$REPLAY_SUMMARY" && -f "$REPLAY_SUMMARY" ]]; then
  echo "=== Recomputing C1 deadline projection from: $REPLAY_SUMMARY ==="
  "${DOCKER_ARGS[@]}" python bench/c1_cost_model.py \
    --watcher-summary "$RESULT_DIR/watcher_pipeline_summary.csv" \
    --replay-summary "$REPLAY_SUMMARY" \
    --output-dir "$RESULT_DIR"
else
  echo "No replay_scaling_summary.csv found; watcher statistics were produced without regenerating the C1 projection." >&2
fi

"$PYTHON_BIN" - <<PY
from pathlib import Path
import shutil
root = Path(${RESULT_DIR@Q})
archive = shutil.make_archive(str(root), "zip", root)
print(f"Watcher extension completed.\n  Results: {root}\n  Archive: {archive}")
PY
