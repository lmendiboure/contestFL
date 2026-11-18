#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
PYTHON_BIN="$(resolve_python)"
cd "$ROOT"

find . -type f -name '*.sh' -print0 | sort -z | xargs -0 -n1 bash -n
"$PYTHON_BIN" -m compileall -q bench ml tools formal review tests
"$PYTHON_BIN" -m unittest discover -s tests -v
# Reference PDFs are retained release artifacts. Matplotlib PDF metadata may
# change with each export even when values are identical. Keep a source-only
# integrity check non-mutating; regenerate figures only on explicit request.
if [[ "${REGENERATE_REFERENCE_FIGURES:-0}" == "1" ]]; then
  if "$PYTHON_BIN" -c 'import matplotlib, numpy, pandas' >/dev/null 2>&1; then
    "$PYTHON_BIN" tools/plot_reference_results.py
  else
    echo "Cannot regenerate reference figures: matplotlib/numpy/pandas absent." >&2
    exit 1
  fi
else
  echo "Reference figures preserved; set REGENERATE_REFERENCE_FIGURES=1 for explicit regeneration."
fi
"$PYTHON_BIN" tools/verify_reference_results.py
"$PYTHON_BIN" formal/validate_retained_dag.py >/dev/null
_tmpdir="$(mktemp -d)"
trap 'rm -rf "$_tmpdir"' EXIT
"$PYTHON_BIN" formal/feature_ablation_check.py --output-dir "$_tmpdir/feature" >/dev/null
"$PYTHON_BIN" formal/dynamic_dependency_check.py --output-dir "$_tmpdir/dynamic" >/dev/null
for archive in results/reference/archives/*.zip; do
  unzip -tq "$archive" >/dev/null
done

echo "Repository source and retained-result checks passed. Docker-dependent tests run in make selftest."
