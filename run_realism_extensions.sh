#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
BASE_RUN_ID="${BASE_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

if [[ "${SKIP_ROOT_ONLY:-0}" != "1" ]]; then
  RUN_ID="${BASE_RUN_ID}_root_only" ./run_root_only_ablation.sh
fi
if [[ "${SKIP_FLOWER:-0}" != "1" ]]; then
  RUN_ID="${BASE_RUN_ID}_flower_mnist" ./run_flower_mnist_e2e.sh
fi
if [[ "${SKIP_NETWORK:-0}" != "1" ]]; then
  RUN_ID="${BASE_RUN_ID}_network_smoke" ./run_network_smoke.sh
fi

echo "Requested realism extensions completed."
[[ "${SKIP_ROOT_ONLY:-0}" == "1" ]] || echo "  Root-only: results/runs/${BASE_RUN_ID}_root_only"
[[ "${SKIP_FLOWER:-0}" == "1" ]] || echo "  Flower:    results/runs/${BASE_RUN_ID}_flower_mnist"
[[ "${SKIP_NETWORK:-0}" == "1" ]] || echo "  Network:   results/runs/${BASE_RUN_ID}_network_smoke"
