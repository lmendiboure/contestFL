#!/usr/bin/env bash

# Shared shell helpers for the repository launchers.

ensure_env_file() {
  local root="$1"
  if [[ ! -e "$root/.env" ]]; then
    cp "$root/.env.example" "$root/.env"
  fi
}

resolve_python() {
  local candidate=""
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    candidate="$PYTHON_BIN"
  elif command -v python3 >/dev/null 2>&1; then
    candidate="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    candidate="$(command -v python)"
  else
    echo "Python 3 is required on the host (install python3 or set PYTHON_BIN)." >&2
    return 1
  fi

  command -v "$candidate" >/dev/null 2>&1 || {
    echo "Python interpreter not found: $candidate" >&2
    return 1
  }
  "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
    echo "ContestFL requires Python 3.10 or newer; found: $($candidate --version 2>&1)" >&2
    return 1
  }
  command -v "$candidate"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "$1 is required." >&2
    return 1
  }
}
