#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from eth_account import Account
from solcx import compile_standard, get_installed_solc_versions, install_solc
from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]


def private_key(name: str) -> str:
    return (ROOT / "network" / "secrets" / f"{name}.key").read_text(encoding="utf-8").strip()


def send(w3: Web3, key: str, call: Any) -> tuple[str, Any]:
    account = Account.from_key(key)
    transaction = {
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address, "pending"),
        "chainId": w3.eth.chain_id,
        "gasPrice": 0,
    }
    transaction["gas"] = int(call.estimate_gas(transaction) * 1.25) + 50_000
    built = call.build_transaction(transaction)
    signed = Account.sign_transaction(built, key)
    transaction_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(transaction_hash, timeout=180)
    if receipt.status != 1:
        raise RuntimeError(f"transaction failed: {transaction_hash.hex()}")
    return transaction_hash.hex(), receipt


def main() -> None:
    w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL", "http://node1:8545"), request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        raise RuntimeError("Besu RPC is unavailable")
    version = os.getenv("SOLC_VERSION", "0.8.24")
    if version not in {str(item) for item in get_installed_solc_versions()}:
        install_solc(version)

    sources = {
        path.name: {"content": path.read_text(encoding="utf-8")}
        for path in (ROOT / "contracts").glob("*.sol")
    }
    output = compile_standard(
        {
            "language": "Solidity",
            "sources": sources,
            "settings": {
                "optimizer": {"enabled": True, "runs": 200},
                "viaIR": True,
                "evmVersion": "london",
                "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
            },
        },
        solc_version=version,
    )

    admin_key = private_key("admin")
    coordinator = Account.from_key(private_key("coordinator")).address
    resolver = Account.from_key(private_key("resolver")).address
    deployments = {}
    constructors = {
        "ContestFLExperiment": [coordinator, resolver],
        "LoggingOnly": [coordinator],
        "EagerVerification": [coordinator, resolver],
        "SingleShotOptimistic": [coordinator, resolver],
        "EvidenceVerifier": [],
        "RootOnlyContestFL": [coordinator, resolver],
    }
    for contract_name, constructor_args in constructors.items():
        source_name = f"{contract_name}.sol"
        interface = output["contracts"][source_name][contract_name]
        factory = w3.eth.contract(
            abi=interface["abi"],
            bytecode=interface["evm"]["bytecode"]["object"],
        )
        tx_hash, receipt = send(w3, admin_key, factory.constructor(*constructor_args))
        deployments[contract_name] = {
            "address": receipt.contractAddress,
            "abi": interface["abi"],
            "bytecode": interface["evm"]["bytecode"]["object"],
            "deploymentTx": tx_hash,
            "deploymentGas": int(receipt.gasUsed),
        }

    artifact = {
        "chainId": w3.eth.chain_id,
        "clientVersion": w3.client_version,
        "solc": version,
        "viaIR": True,
        "optimizerRuns": 200,
        "contracts": deployments,
    }
    path = ROOT / "network" / "contracts.json"
    path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(artifact, indent=2))


if __name__ == "__main__":
    main()
