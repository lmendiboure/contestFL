#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/common.sh"
PYTHON_BIN="$(resolve_python)"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_auxiliary_formal}"
RESULT_DIR="${RESULT_DIR:-$ROOT/results/runs/$RUN_ID}"
mkdir -p "$RESULT_DIR"
"$PYTHON_BIN" "$ROOT/formal/feature_ablation_check.py" --output-dir "$RESULT_DIR/feature_ablation"
"$PYTHON_BIN" "$ROOT/formal/validate_retained_dag.py" | tee "$RESULT_DIR/dependency_dag_validation.json"
(cd "$ROOT" && "$PYTHON_BIN" -c "import shutil; shutil.make_archive('$RESULT_DIR','zip','$RESULT_DIR')")
echo "Auxiliary formal checks complete: $RESULT_DIR"
