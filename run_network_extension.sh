#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Run only the controlled RTT extension and regenerate the combined analysis.
# Use a new RUN_ID unless the same directory already contains the 4/7-validator
# and replay outputs that should be combined with these network measurements.
SKIP_CONFIRMATION=1 \
SKIP_7_VALIDATORS=1 \
SKIP_REPLAY_SCALING=1 \
exec ./run_final_extension.sh
