#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"

PYTHON_BIN="$(resolve_python)"
require_command docker
require_command make
require_command bash

docker compose version >/dev/null 2>&1 || {
  echo "The Docker Compose plugin is required." >&2
  exit 1
}
docker info >/dev/null 2>&1 || {
  echo "The Docker daemon is not reachable by the current user." >&2
  exit 1
}

free_kb="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
if [[ "${free_kb:-0}" -lt 8388608 ]]; then
  echo "Warning: less than 8 GiB is free on the repository filesystem." >&2
fi

printf 'Python:  %s\n' "$($PYTHON_BIN --version 2>&1)"
printf 'Docker:  %s\n' "$(docker --version)"
printf 'Compose: %s\n' "$(docker compose version --short)"
printf 'Make:    %s\n' "$(make --version | head -n1)"
if command -v java >/dev/null 2>&1; then
  printf 'Java:    %s\n' "$(java -version 2>&1 | head -n1)"
else
  echo "Java:    not found (required only for TLC)"
fi
