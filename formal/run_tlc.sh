#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
export LANG=C

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORMAL="$ROOT/formal"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
PYTHON_BIN="$(resolve_python)"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_tlc}"
RESULT_DIR="$ROOT/results/runs/${RUN_ID}"
TLA2TOOLS_VERSION="${TLA2TOOLS_VERSION:-1.7.4}"
TLA2TOOLS_SHA1="${TLA2TOOLS_SHA1:-bee4a54f3ee3d4afc347c3240ec2d9e93b075104}"
TLA2TOOLS_JAR="${TLA2TOOLS_JAR:-$ROOT/.cache/tla2tools-${TLA2TOOLS_VERSION}.jar}"
TLC_WORKERS="${TLC_WORKERS:-auto}"

mkdir -p "$(dirname "$TLA2TOOLS_JAR")" "$RESULT_DIR"

if [[ ! -s "$TLA2TOOLS_JAR" ]]; then
  url="https://github.com/tlaplus/tlaplus/releases/download/v${TLA2TOOLS_VERSION}/tla2tools.jar"
  echo "Downloading official TLA+ command-line tools v${TLA2TOOLS_VERSION}"
  if command -v curl >/dev/null 2>&1; then
    curl -L --fail --retry 3 "$url" -o "$TLA2TOOLS_JAR"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$TLA2TOOLS_JAR" "$url"
  else
    echo "curl or wget is required to download tla2tools.jar" >&2
    exit 1
  fi
fi

echo "${TLA2TOOLS_SHA1}  ${TLA2TOOLS_JAR}" | sha1sum -c -
java -version >"$RESULT_DIR/java_version.txt" 2>&1
java -jar "$TLA2TOOLS_JAR" -version >"$RESULT_DIR/tlc_version.txt" 2>&1 || true

run_model() {
  local config="$1" output="$2"
  (
    cd "$FORMAL"
    java -XX:+UseParallelGC -jar "$TLA2TOOLS_JAR" \
      -workers "$TLC_WORKERS" -config "$config" ContestFL.tla
  ) 2>&1 | tee "$RESULT_DIR/$output"
}

run_model MC_Coverage.cfg MC_Coverage.out
run_model MC_Structural.cfg MC_Structural.out
"$PYTHON_BIN" "$FORMAL/parse_tlc.py" --output-dir "$RESULT_DIR" \
  "$RESULT_DIR/MC_Coverage.out" "$RESULT_DIR/MC_Structural.out"

cp "$FORMAL/ContestFL.tla" "$FORMAL/MC_Coverage.cfg" "$FORMAL/MC_Structural.cfg" "$RESULT_DIR/"
(
  cd "$ROOT"
  "$PYTHON_BIN" -c "import shutil; shutil.make_archive('$RESULT_DIR', 'zip', '$RESULT_DIR')"
)

echo "TLC verification complete"
echo "  Report: $RESULT_DIR/TLC_RESULTS.md"
echo "  Bundle: $RESULT_DIR.zip"
