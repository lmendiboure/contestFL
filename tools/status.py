#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import time

from web3 import Web3


def peer_ipv4(remote_address: str) -> str | None:
    match = re.search(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])", remote_address)
    return match.group(0) if match else None


def admin_peers(w3: Web3) -> list[dict]:
    response = w3.provider.make_request("admin_peers", [])
    if "error" in response:
        raise RuntimeError(f"admin_peers failed: {response['error']}")
    result = response.get("result")
    if not isinstance(result, list):
        raise RuntimeError(f"unexpected admin_peers response: {response}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validators", type=int, required=True)
    parser.add_argument("--wait-seconds", type=int, default=60)
    parser.add_argument("--require-p2p-subnet", default="")
    args = parser.parse_args()

    required_network = (
        ipaddress.ip_network(args.require_p2p_subnet, strict=True)
        if args.require_p2p_subnet
        else None
    )
    deadline = time.time() + args.wait_seconds
    status: list[dict] = []
    last_error = ""
    while True:
        status = []
        try:
            for i in range(args.validators):
                url = f"http://node{i + 1}:8545"
                w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 10}))
                if not w3.is_connected():
                    raise RuntimeError(f"RPC unavailable: {url}")
                peers = admin_peers(w3)
                remote_addresses = [
                    str(peer.get("network", {}).get("remoteAddress", "")) for peer in peers
                ]
                peer_ips = [ip for value in remote_addresses if (ip := peer_ipv4(value))]
                p2p_path_ok = True
                if required_network is not None:
                    p2p_path_ok = len(peer_ips) == len(peers) and all(
                        ipaddress.ip_address(value) in required_network for value in peer_ips
                    )
                status.append(
                    {
                        "node": i + 1,
                        "url": url,
                        "clientVersion": w3.client_version,
                        "peerCount": w3.net.peer_count,
                        "adminPeerCount": len(peers),
                        "peerRemoteAddresses": remote_addresses,
                        "p2pPathOk": p2p_path_ok,
                        "blockNumber": w3.eth.block_number,
                        "chainId": w3.eth.chain_id,
                    }
                )
            ready = all(
                item["peerCount"] >= args.validators - 1
                and item["adminPeerCount"] >= args.validators - 1
                and item["p2pPathOk"]
                for item in status
            )
            if ready:
                break
            last_error = "peer count or P2P path is not ready"
        except Exception as exc:
            status = []
            last_error = f"{type(exc).__name__}: {exc}"

        if time.time() >= deadline:
            raise RuntimeError(
                f"QBFT network did not become ready within {args.wait_seconds}s: "
                f"error={last_error}; status={status}"
            )
        time.sleep(2)

    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
