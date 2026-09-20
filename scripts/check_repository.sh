#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
PYTHON_BIN="$(resolve_python)"
cd "$ROOT"

find . -type f -name '*.sh' -print0 | sort -z | xargs -0 -n1 bash -n
"$PYTHON_BIN" -m compileall -q bench ml tools formal tests
"$PYTHON_BIN" -m unittest discover -s tests -v
if "$PYTHON_BIN" -c 'import matplotlib, numpy, pandas' >/dev/null 2>&1; then
  "$PYTHON_BIN" tools/plot_reference_results.py
else
  echo "Skipping figure regeneration: matplotlib/numpy/pandas are not installed on the host."
fi
"$PYTHON_BIN" tools/verify_reference_results.py
"$PYTHON_BIN" formal/validate_retained_dag.py >/dev/null
_tmpdir="$(mktemp -d)"
trap 'rm -rf "$_tmpdir"' EXIT
"$PYTHON_BIN" formal/feature_ablation_check.py --output-dir "$_tmpdir/feature" >/dev/null
for archive in results/reference/archives/*.zip; do
  unzip -tq "$archive" >/dev/null
done

echo "Repository source and retained-result checks passed. Docker-dependent tests run in make selftest."
