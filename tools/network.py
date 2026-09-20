#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import ipaddress
import secrets
import shutil
import stat
from pathlib import Path

from eth_account import Account

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "network" / "work"
RUNTIME = ROOT / "network" / "runtime"
SECRETS = ROOT / "network" / "secrets"
COMPOSE = ROOT / "network" / "docker-compose.generated.yml"

P2P_NETWORK_NAME = os.getenv("P2P_NETWORK_NAME", "contestfl-p2p-net")
CONTROL_NETWORK_NAME = os.getenv("CONTROL_NETWORK_NAME", "contestfl-control-net")
P2P_SUBNET = os.getenv("P2P_SUBNET", "172.31.0.0/24")
CONTROL_SUBNET = os.getenv("CONTROL_SUBNET", "172.32.0.0/24")


def subnet_host(subnet: str, offset: int) -> str:
    network = ipaddress.ip_network(subnet, strict=True)
    address = network.network_address + offset
    if address not in network or address == network.broadcast_address:
        raise ValueError(f"offset {offset} is outside subnet {subnet}")
    return str(address)


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def parse_quantity(raw: str, *, name: str) -> int:
    """Parse a positive decimal or 0x-prefixed integer quantity."""
    try:
        value = int(raw.strip(), 0)
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{name} must be a decimal or 0x-prefixed integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def account(name: str) -> str:
    path = SECRETS / f"{name}.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        private_key = path.read_text(encoding="utf-8").strip().removeprefix("0x")
    else:
        private_key = Account.create(secrets.token_bytes(32)).key.hex().removeprefix("0x")
        path.write_text(private_key + "\n", encoding="utf-8")
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return Account.from_key(private_key).address


def prepare(validators: int) -> None:
    if validators not in (4, 7):
        raise ValueError("the supplied campaign supports 4 or 7 QBFT validators")
    chain_id = int(os.getenv("CHAIN_ID", "20260803")) + validators
    block_period = int(os.getenv("BLOCK_PERIOD_SECONDS", "1"))
    request_timeout = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "2"))
    challenger_count = int(os.getenv("CHALLENGER_ACCOUNTS", "16"))
    block_gas_limit = parse_quantity(
        os.getenv("BLOCK_GAS_LIMIT", "0x1fffffffffffff"), name="BLOCK_GAS_LIMIT"
    )
    target_gas_limit_raw = os.getenv("TARGET_GAS_LIMIT", "").strip()
    target_gas_limit = (
        parse_quantity(target_gas_limit_raw, name="TARGET_GAS_LIMIT")
        if target_gas_limit_raw
        else None
    )

    names = ["admin", "coordinator", "resolver", "submitter"] + [
        f"challenger{i}" for i in range(challenger_count)
    ]
    addresses = {name: account(name) for name in names}
    write_json(SECRETS / "addresses.json", addresses)
    alloc = {
        address.removeprefix("0x").lower(): {"balance": hex(100_000 * 10**18)}
        for address in addresses.values()
    }
    config = {
        "genesis": {
            "config": {
                "chainId": chain_id,
                "berlinBlock": 0,
                "londonBlock": 0,
                "zeroBaseFee": True,
                "contractSizeLimit": 2_147_483_647,
                "qbft": {
                    "blockperiodseconds": block_period,
                    "epochlength": 30_000,
                    "requesttimeoutseconds": request_timeout,
                },
            },
            "nonce": "0x0",
            "timestamp": "0x0",
            "gasLimit": hex(block_gas_limit),
            "difficulty": "0x1",
            "mixHash": "0x63746963616c2062797a616e74696e65206661756c7420746f6c6572616e6365",
            "coinbase": "0x0000000000000000000000000000000000000000",
            "baseFeePerGas": "0x0",
            "alloc": alloc,
        },
        "blockchain": {"nodes": {"generate": True, "count": validators}},
    }
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    write_json(WORK / "qbftConfigFile.json", config)
    print(json.dumps({
        "validators": validators,
        "chainId": chain_id,
        "blockGasLimit": block_gas_limit,
        "blockGasLimitHex": hex(block_gas_limit),
        "targetGasLimit": target_gas_limit,
        "accounts": addresses,
    }, indent=2))


def finalize(validators: int) -> None:
    key_dirs = sorted((WORK / "output" / "keys").iterdir())
    if len(key_dirs) != validators:
        raise RuntimeError(f"expected {validators} validator directories, got {len(key_dirs)}")
    shutil.rmtree(RUNTIME, ignore_errors=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    shutil.copy2(WORK / "output" / "genesis.json", RUNTIME / "genesis.json")

    p2p_hosts = [subnet_host(P2P_SUBNET, 11 + i) for i in range(validators)]
    public_keys = [
        (key_dir / "key.pub").read_text(encoding="utf-8").strip().removeprefix("0x")
        for key_dir in key_dirs
    ]
    enodes = [
        f"enode://{public_keys[i]}@{p2p_hosts[i]}:30303" for i in range(validators)
    ]
    for i, key_dir in enumerate(key_dirs):
        destination = RUNTIME / f"node{i + 1}"
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(key_dir / "key", destination / "key")
        shutil.copy2(key_dir / "key.pub", destination / "key.pub")
        (destination / "static-nodes.json").write_text(
            json.dumps([entry for j, entry in enumerate(enodes) if j != i], indent=2) + "\n",
            encoding="utf-8",
        )
    generate_compose(validators)
    print(f"network prepared in {RUNTIME}; compose file: {COMPOSE}")


def generate_compose(validators: int) -> None:
    target_gas_limit_raw = os.getenv("TARGET_GAS_LIMIT", "").strip()
    target_gas_limit = (
        parse_quantity(target_gas_limit_raw, name="TARGET_GAS_LIMIT")
        if target_gas_limit_raw
        else None
    )
    lines = [
        "name: contestfl-eval",
        "x-besu: &besu",
        "  image: ${BESU_IMAGE:-hyperledger/besu:26.7.0}",
        '  user: "${LOCAL_UID:-1000}:${LOCAL_GID:-1000}"',
        "  restart: unless-stopped",
        "  command:",
        "    - --data-path=/var/lib/besu",
        "    - --genesis-file=/config/genesis.json",
        "    - --static-nodes-file=/var/lib/besu/static-nodes.json",
        "    - --discovery-enabled=false",
        "    - --profile=ENTERPRISE",
        "    - --min-gas-price=0",
        "    - --rpc-http-host=0.0.0.0",
        "    - --rpc-http-port=8545",
        "    - --rpc-http-api=ETH,NET,WEB3,QBFT,ADMIN",
        "    - --host-allowlist=*",
        "    - --rpc-http-cors-origins=*",
        "    - --p2p-port=30303",
        "    - --logging=INFO",
    ]
    if target_gas_limit is not None:
        # Besu exposes a target gas limit independently of the genesis value.
        # Set both for the bounded-capacity experiment so later blocks cannot
        # drift toward a client default.
        lines.append(f"    - --target-gas-limit={target_gas_limit}")
    lines += [
        "    - --rpc-http-enabled=true",
        "services:",
    ]
    for i in range(validators):
        node = i + 1
        rpc_port = 8545 + i * 10
        p2p_port = 30303 + i
        p2p_ip = subnet_host(P2P_SUBNET, 11 + i)
        control_ip = subnet_host(CONTROL_SUBNET, 11 + i)
        lines += [
            f"  node{node}:",
            "    <<: *besu",
            f"    hostname: node{node}",
            "    volumes:",
            "      - ./runtime/genesis.json:/config/genesis.json:ro",
            f"      - ./runtime/node{node}:/var/lib/besu",
            "    ports:",
            f'      - "{rpc_port}:8545"',
            f'      - "{p2p_port}:30303/tcp"',
            f'      - "{p2p_port}:30303/udp"',
            "    networks:",
            "      control:",
            f"        ipv4_address: {control_ip}",
            "      p2p:",
            f"        ipv4_address: {p2p_ip}",
        ]
    lines += [
        "  tools:",
        "    image: ${TOOLS_IMAGE:-contestfl-eval-tools:local}",
        "    working_dir: /workspace",
        '    user: "${LOCAL_UID:-1000}:${LOCAL_GID:-1000}"',
        "    volumes:",
        "      - ..:/workspace",
        "    environment:",
        "      RPC_URL: http://node1:8545",
        "      SOLC_VERSION: ${SOLC_VERSION:-0.8.24}",
        "    networks: [control]",
        "    profiles: [tools]",
        "networks:",
        "  control:",
        f"    name: {CONTROL_NETWORK_NAME}",
        "    driver: bridge",
        "    ipam:",
        "      config:",
        f"        - subnet: {CONTROL_SUBNET}",
        "  p2p:",
        f"    name: {P2P_NETWORK_NAME}",
        "    driver: bridge",
        "    ipam:",
        "      config:",
        f"        - subnet: {P2P_SUBNET}",
    ]
    COMPOSE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "finalize"])
    parser.add_argument("--validators", type=int, required=True)
    args = parser.parse_args()
    globals()[args.action](args.validators)


if __name__ == "__main__":
    main()
