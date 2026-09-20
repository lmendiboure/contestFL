#!/usr/bin/env python3
"""Apply or inspect netem inside a validator's shared network namespace.

This helper is executed in a short-lived tools container with
``--network container:<validator-id>`` and ``--cap-add NET_ADMIN``.  It finds
only the interface carrying the validator's P2P address, so JSON-RPC traffic on
the separate control network is not delayed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from typing import Any


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    return subprocess.run(command, text=True, capture_output=True, check=check, env=env)


def interfaces() -> list[dict[str, Any]]:
    result = run(["ip", "-j", "-4", "addr", "show"])
    return json.loads(result.stdout)


def find_interface(ip_address: str) -> str:
    for interface in interfaces():
        for address in interface.get("addr_info", []):
            if address.get("local") == ip_address:
                return str(interface["ifname"])
    raise RuntimeError(f"no interface carries P2P address {ip_address}")


def parse_ping_average(text: str) -> float:
    # iputils output: rtt min/avg/max/mdev = 0.123/0.456/0.789/0.012 ms
    match = re.search(
        r"(?:rtt|round-trip) min/avg/max/(?:mdev|stddev) = "
        r"[0-9.]+/([0-9.]+)/[0-9.]+/[0-9.]+ ms",
        text,
    )
    if not match:
        raise RuntimeError(f"unable to parse ping statistics:\n{text}")
    return float(match.group(1))


def apply_delay(interface: str, delay_us: int, jitter_us: int) -> None:
    if delay_us < 0 or jitter_us < 0:
        raise ValueError("delay and jitter must be non-negative")
    command = [
        "tc",
        "qdisc",
        "replace",
        "dev",
        interface,
        "root",
        "netem",
        "delay",
        f"{delay_us}us",
    ]
    if jitter_us > 0:
        command.extend([f"{jitter_us}us", "distribution", "normal"])
    run(command)


def clear_delay(interface: str) -> None:
    """Remove an active netem root qdisc, if one is installed.

    Docker veth interfaces commonly expose the implicit ``noqueue`` root qdisc.
    Asking ``tc qdisc del ... root`` to delete that implicit qdisc fails with
    messages such as ``cannot delete qdisc with handle of zero``.  That state
    already means that no emulation is active, so inspect the interface first
    and issue the delete only when a real netem qdisc is present.
    """
    current = run(["tc", "qdisc", "show", "dev", interface], check=False)
    if current.returncode != 0:
        message = (current.stderr or current.stdout).strip()
        raise RuntimeError(message or "failed to inspect qdisc")

    if not re.search(r"\bnetem\b", current.stdout):
        return

    result = run(["tc", "qdisc", "del", "dev", interface, "root"], check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip().lower()
        benign_fragments = (
            "no such file",
            "no such qdisc",
            "cannot find qdisc",
            "invalid argument",
            "cannot delete qdisc with handle of zero",
        )
        if not any(fragment in message for fragment in benign_fragments):
            raise RuntimeError(message or "failed to remove qdisc")


def show_delay(interface: str) -> str:
    result = run(["tc", "qdisc", "show", "dev", interface])
    return result.stdout.strip()


def probe(peer_ip: str, packets: int, timeout_seconds: int) -> dict[str, Any]:
    if packets < 1:
        raise ValueError("packets must be positive")
    result = run(
        [
            "ping",
            "-n",
            "-q",
            "-c",
            str(packets),
            "-W",
            str(timeout_seconds),
            peer_ip,
        ]
    )
    return {
        "peerIp": peer_ip,
        "packets": packets,
        "averageRttMs": parse_ping_average(result.stdout),
        "raw": result.stdout.strip(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["apply", "clear", "show", "probe"])
    parser.add_argument("--p2p-ip", required=True)
    parser.add_argument("--delay-us", type=int, default=0)
    parser.add_argument("--jitter-us", type=int, default=0)
    parser.add_argument("--peer-ip")
    parser.add_argument("--packets", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=3)
    args = parser.parse_args()

    interface = find_interface(args.p2p_ip)
    payload: dict[str, Any] = {"interface": interface, "p2pIp": args.p2p_ip}

    if args.action == "apply":
        apply_delay(interface, args.delay_us, args.jitter_us)
        payload.update(
            {
                "action": "apply",
                "delayUs": args.delay_us,
                "jitterUs": args.jitter_us,
                "qdisc": show_delay(interface),
            }
        )
    elif args.action == "clear":
        clear_delay(interface)
        payload.update({"action": "clear", "qdisc": show_delay(interface)})
    elif args.action == "show":
        payload.update({"action": "show", "qdisc": show_delay(interface)})
    else:
        if not args.peer_ip:
            parser.error("--peer-ip is required for probe")
        payload.update({"action": "probe", **probe(args.peer_ip, args.packets, args.timeout_seconds)})

    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
