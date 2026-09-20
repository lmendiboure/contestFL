#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
export LANG=C

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[[ -f .env ]] && { set -a; source .env; set +a; }

COMPOSE_FILE="network/docker-compose.generated.yml"
TOOLS_IMAGE="${TOOLS_IMAGE:-contestfl-eval-tools:local}"
P2P_NETWORK_NAME="${P2P_NETWORK_NAME:-contestfl-p2p-net}"
PROBE_PACKETS="${NETWORK_PROBE_PACKETS:-5}"
PROBE_TIMEOUT="${NETWORK_PROBE_TIMEOUT_SECONDS:-3}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_runtime() {
  command -v docker >/dev/null 2>&1 || fail "Docker is required"
  docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable"
  [[ -f "$COMPOSE_FILE" ]] || fail "$COMPOSE_FILE is missing; run make bootstrap first"
  docker image inspect "$TOOLS_IMAGE" >/dev/null 2>&1 || fail "tools image $TOOLS_IMAGE is missing; run make tools"
}

compose() {
  LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)" docker compose -f "$COMPOSE_FILE" "$@"
}

container_id() {
  local node="$1"
  local cid
  cid="$(compose ps -q "node${node}")"
  [[ -n "$cid" ]] || fail "validator node${node} is not running"
  printf '%s\n' "$cid"
}

p2p_ip() {
  local cid="$1"
  local ip
  ip="$(docker inspect -f "{{with index .NetworkSettings.Networks \"${P2P_NETWORK_NAME}\"}}{{.IPAddress}}{{end}}" "$cid")"
  [[ -n "$ip" ]] || fail "container $cid is not attached to $P2P_NETWORK_NAME"
  printf '%s\n' "$ip"
}

run_namespace_helper() {
  local cid="$1"; shift
  docker run --rm \
    --network "container:${cid}" \
    --cap-add NET_ADMIN \
    -v "$ROOT:/workspace:ro" \
    -w /workspace \
    "$TOOLS_IMAGE" \
    python tools/netem_namespace.py "$@"
}

clear_all() {
  local validators="$1"
  require_runtime
  local node cid ip
  for node in $(seq 1 "$validators"); do
    cid="$(container_id "$node")"
    ip="$(p2p_ip "$cid")"
    run_namespace_helper "$cid" clear --p2p-ip "$ip" >/dev/null
  done
  echo "netem cleared on $validators validator P2P interfaces"
}

apply_all() {
  local validators="$1" requested_rtt_ms="$2" jitter_ms="${3:-0}"
  require_runtime
  awk -v rtt="$requested_rtt_ms" -v jitter="$jitter_ms" 'BEGIN { if (rtt < 0 || jitter < 0) exit 1 }' \
    || fail "RTT and jitter must be non-negative"
  clear_all "$validators" >/dev/null
  if awk -v rtt="$requested_rtt_ms" 'BEGIN { exit !(rtt == 0) }'; then
    echo "netem disabled (requested RTT=0 ms)"
    return 0
  fi

  [[ "$requested_rtt_ms" =~ ^[0-9]+$ ]] || fail "requested RTT must be an integer number of milliseconds"
  [[ "$jitter_ms" =~ ^[0-9]+$ ]] || fail "jitter must be an integer number of milliseconds"
  local one_way_us jitter_us
  one_way_us=$((requested_rtt_ms * 1000 / 2))
  jitter_us=$((jitter_ms * 1000))
  local node cid ip
  for node in $(seq 1 "$validators"); do
    cid="$(container_id "$node")"
    ip="$(p2p_ip "$cid")"
    run_namespace_helper "$cid" apply \
      --p2p-ip "$ip" --delay-us "$one_way_us" --jitter-us "$jitter_us" >/dev/null
  done
  echo "netem active on P2P only: validators=$validators requested_RTT=${requested_rtt_ms}ms egress_delay=${one_way_us}us jitter=${jitter_us}us"
}

show_all() {
  local validators="$1"
  require_runtime
  local node cid ip
  for node in $(seq 1 "$validators"); do
    cid="$(container_id "$node")"
    ip="$(p2p_ip "$cid")"
    printf 'node%s ' "$node"
    run_namespace_helper "$cid" show --p2p-ip "$ip"
  done
}

probe_once() {
  local validators="$1" requested_rtt_ms="$2" output_csv="${3:-}"
  [[ "$validators" -ge 2 ]] || fail "at least two validators are required for a probe"
  require_runtime
  local cid1 cid2 ip1 ip2 payload observed
  cid1="$(container_id 1)"
  cid2="$(container_id 2)"
  ip1="$(p2p_ip "$cid1")"
  ip2="$(p2p_ip "$cid2")"
  payload="$(run_namespace_helper "$cid1" probe \
    --p2p-ip "$ip1" --peer-ip "$ip2" \
    --packets "$PROBE_PACKETS" --timeout-seconds "$PROBE_TIMEOUT")"
  observed="$(sed -nE 's/.*"averageRttMs": ([0-9.]+).*/\1/p' <<<"$payload")"
  [[ -n "$observed" ]] || fail "unable to parse probe result: $payload"
  echo "P2P probe: validators=$validators requested_RTT=${requested_rtt_ms}ms observed_RTT=${observed}ms packets=$PROBE_PACKETS"

  if [[ -n "$output_csv" ]]; then
    mkdir -p "$(dirname "$output_csv")"
    if [[ ! -s "$output_csv" ]]; then
      printf 'timestamp_utc,validators,requested_rtt_ms,observed_rtt_ms,packets,node1_p2p_ip,node2_p2p_ip\n' > "$output_csv"
    fi
    printf '%s,%s,%s,%s,%s,%s,%s\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$validators" "$requested_rtt_ms" \
      "$observed" "$PROBE_PACKETS" "$ip1" "$ip2" >> "$output_csv"
  fi
  printf '%s\n' "$observed"
}

preflight() {
  local validators="$1" test_rtt_ms="${2:-20}"
  require_runtime
  echo "=== tc/netem capability preflight ($validators validators) ==="
  clear_all "$validators" >/dev/null
  local baseline impaired recovered
  baseline="$(probe_once "$validators" 0 | tail -n1)"
  apply_all "$validators" "$test_rtt_ms" >/dev/null
  impaired="$(probe_once "$validators" "$test_rtt_ms" | tail -n1)"
  clear_all "$validators" >/dev/null
  recovered="$(probe_once "$validators" 0 | tail -n1)"

  awk -v baseline="$baseline" -v impaired="$impaired" -v recovered="$recovered" -v target="$test_rtt_ms" 'BEGIN {
    minimum = target * 0.50; if (minimum < 2.0) minimum = 2.0;
    if (impaired < baseline + minimum) {
      printf "netem preflight failed: baseline=%.3f ms, impaired=%.3f ms, expected increase >= %.3f ms\n", baseline, impaired, minimum > "/dev/stderr";
      exit 1;
    }
    if (recovered > impaired - minimum / 2.0) {
      printf "netem cleanup check failed: recovered=%.3f ms, impaired=%.3f ms\n", recovered, impaired > "/dev/stderr";
      exit 1;
    }
    printf "{\n  \"baselineRttMs\": %.3f,\n  \"impairedRttMs\": %.3f,\n  \"recoveredRttMs\": %.3f,\n  \"requestedRttMs\": %.3f\n}\n", baseline, impaired, recovered, target;
  }'
  echo "tc/netem preflight passed"
}

usage() {
  cat >&2 <<'EOF_USAGE'
Usage:
  tools/netem.sh apply <validators> <requested-rtt-ms> [jitter-ms]
  tools/netem.sh clear <validators>
  tools/netem.sh show <validators>
  tools/netem.sh probe <validators> <requested-rtt-ms> [output.csv]
  tools/netem.sh preflight <validators> [test-rtt-ms]
EOF_USAGE
  exit 2
}

ACTION="${1:-}"
case "$ACTION" in
  apply) [[ $# -ge 3 ]] || usage; apply_all "$2" "$3" "${4:-0}" ;;
  clear) [[ $# -eq 2 ]] || usage; clear_all "$2" ;;
  show) [[ $# -eq 2 ]] || usage; show_all "$2" ;;
  probe) [[ $# -ge 3 ]] || usage; probe_once "$2" "$3" "${4:-}" ;;
  preflight) [[ $# -ge 2 ]] || usage; preflight "$2" "${3:-20}" ;;
  *) usage ;;
esac
