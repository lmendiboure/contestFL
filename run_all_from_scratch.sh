#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
export LANG=C

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
ensure_env_file "$ROOT"
PYTHON_BIN="$(resolve_python)"

SUITE="${SUITE:-paper}"
BASE_RUN_ID="${BASE_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
RELEASE_DIR="${RELEASE_DIR:-$ROOT/artifacts/${BASE_RUN_ID}_${SUITE}}"
RESUME="${RESUME:-1}"

case "$SUITE" in
  smoke|paper|exhaustive) ;;
  *) echo "SUITE must be smoke, paper, or exhaustive" >&2; exit 2 ;;
esac

mkdir -p "$RELEASE_DIR/logs"

run_step() {
  local name="$1"; shift
  local log="$RELEASE_DIR/logs/${name}.log"
  echo "=== ${name} ===" | tee "$log"
  printf 'Command:' | tee -a "$log"
  printf ' %q' "$@" | tee -a "$log"
  printf '\n' | tee -a "$log"
  "$@" 2>&1 | tee -a "$log"
}

run_env_step() {
  local name="$1"; shift
  local log="$RELEASE_DIR/logs/${name}.log"
  echo "=== ${name} ===" | tee "$log"
  printf 'Command: env' | tee -a "$log"
  printf ' %q' "$@" | tee -a "$log"
  printf '\n' | tee -a "$log"
  env "$@" 2>&1 | tee -a "$log"
}

# Source-level checks fail before any expensive campaign.
run_step host_preflight ./scripts/preflight.sh
run_step environment_before "$PYTHON_BIN" tools/capture_environment.py \
  --output "$RELEASE_DIR/environment-before.json" \
  --base-run-id "$BASE_RUN_ID" --suite "$SUITE"
run_step source_selftest make selftest
run_step shell_syntax bash -n \
  run_all_from_scratch.sh run_campaign.sh run_competitor_extension.sh \
  run_targeted_extension.sh run_realism_extensions.sh run_root_only_ablation.sh \
  run_flower_mnist_e2e.sh run_network_smoke.sh run_root_depth_sensitivity.sh \
  run_smt_offchain.sh run_watcher_extension.sh run_bounded_gas_contention.sh \
  formal/run_tlc.sh formal/run_auxiliary_checks.sh scripts/preflight.sh scripts/common.sh scripts/check_repository.sh

if [[ "$SUITE" == "smoke" ]]; then
  run_env_step root_only \
    RUN_ID="${BASE_RUN_ID}_root_only" RESUME="$RESUME" \
    ROOT_ONLY_CLIENTS=10 ROOT_ONLY_ROUNDS=1 ROOT_ONLY_WARMUP=0 \
    ./run_root_only_ablation.sh
  run_env_step flower_mnist \
    RUN_ID="${BASE_RUN_ID}_flower_mnist" RESUME="$RESUME" \
    FLOWER_SAMPLES_PER_CLIENT=128 ./run_flower_mnist_e2e.sh
  run_env_step smt_offchain \
    RUN_ID="${BASE_RUN_ID}_smt_offchain" SMT_OFFCHAIN_REPETITIONS=3 \
    SMT_OFFCHAIN_WARMUP=1 ./run_smt_offchain.sh
  if [[ "${SKIP_TLC:-0}" != "1" ]]; then
    run_env_step tlc RUN_ID="${BASE_RUN_ID}_tlc" ./formal/run_tlc.sh
  fi
else
  # Broad functional/scaling campaign retained for the original evaluation.
  run_env_step stable_core \
    RUN_ID="${BASE_RUN_ID}_stable" RESUME="$RESUME" ./run_campaign.sh stable

  # Design-point comparison and fault-outcome matrix.
  run_env_step competitors \
    RUN_ID="${BASE_RUN_ID}_competitors" RESUME="$RESUME" ./run_competitor_extension.sh

  # Final targeted scaling, robustness, replay, and phase decomposition.
  run_env_step targeted \
    RUN_ID="${BASE_RUN_ID}_targeted" RESUME="$RESUME" ./run_targeted_extension.sh

  # Authenticated-state ablation, Flower REVISED path, and controlled RTT smoke.
  run_env_step realism \
    BASE_RUN_ID="$BASE_RUN_ID" RESUME="$RESUME" ./run_realism_extensions.sh

  # Off-chain authenticated-tree cost and finite-state model checking.
  if [[ "${SKIP_DEPTH_SENSITIVITY:-0}" != "1" ]]; then
    run_env_step root_depth_sensitivity \
      RUN_ID="${BASE_RUN_ID}_root_depth" ./run_root_depth_sensitivity.sh
  fi
  run_env_step smt_offchain \
    RUN_ID="${BASE_RUN_ID}_smt_offchain" ./run_smt_offchain.sh

  # Final-paper watcher and bounded-capacity contention campaigns.
  if [[ "${SKIP_ADDITIONAL_CAMPAIGNS:-0}" != "1" ]]; then
    run_env_step watcher_extension \
      RUN_ID="${BASE_RUN_ID}_watcher" ./run_watcher_extension.sh
    run_env_step bounded_gas_contention \
      RUN_ID="${BASE_RUN_ID}_bounded_contention" \
      BLOCK_GAS_LIMITS="5000000 10000000 30000000" ./run_bounded_gas_contention.sh
  fi

  run_env_step auxiliary_formal \
    RUN_ID="${BASE_RUN_ID}_auxiliary_formal" ./formal/run_auxiliary_checks.sh
  if [[ "${SKIP_TLC:-0}" != "1" ]]; then
    run_env_step tlc RUN_ID="${BASE_RUN_ID}_tlc" ./formal/run_tlc.sh
  fi

  if [[ "$SUITE" == "exhaustive" ]]; then
    # Additional repetitions, committee-size sensitivity, replay, and full RTT sweep.
    run_env_step final_extension \
      RUN_ID="${BASE_RUN_ID}_final_extension" RESUME="$RESUME" ./run_final_extension.sh
  fi
fi

"$PYTHON_BIN" tools/capture_environment.py \
  --output "$RELEASE_DIR/environment-after.json" \
  --base-run-id "$BASE_RUN_ID" --suite "$SUITE"

run_step build_artifact_bundle "$PYTHON_BIN" tools/build_artifact_bundle.py \
  --root "$ROOT" --base-run-id "$BASE_RUN_ID" --suite "$SUITE" \
  --release-dir "$RELEASE_DIR"

echo "ContestFL reproducibility suite completed."
echo "  Release directory: $RELEASE_DIR"
echo "  Release archive:   ${RELEASE_DIR}.zip"
