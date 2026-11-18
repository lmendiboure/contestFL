#!/usr/bin/env python3
"""Empirically expose (do not conceal) the trusted-resolver semantic boundary.

An AUTHORIZED resolver can supply an arbitrary nonzero certificateHash and then
publish a semantically incorrect checkpoint through a terminal fallback.
This test is expected to demonstrate acceptance under the current contract.
If the contract is hardened, acceptance can instead become false; either way
the output is evidence of the tested behavior, not a proof for arbitrary inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from web3 import Web3
# Direct invocation (`python review/trust_boundary_probe.py`) must resolve the repository packages.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.run_scenarios import Context, RoundData, load_contracts, private_key, sha256


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--rpc", default=os.getenv("RPC_URL", "http://node1:8545"))
    p.add_argument("--validators", type=int, default=4)
    args = p.parse_args()
    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        raise RuntimeError("Besu RPC is not available")
    contract, audit, verifier, deployment = load_contracts(w3)
    addresses = json.loads((ROOT / "network/secrets/addresses.json").read_text())
    keys = {name: private_key(name) for name in addresses}
    data = RoundData.generate(2, 1024, 20261106, 32)
    round_id = (time.time_ns() // 1000) * 100
    ctx = Context(
        w3=w3, contract=contract, logging_contract=audit,
        evidence_contract=verifier, validators=args.validators, clients=2,
        repetition=0, scenario="malicious_authorized_resolver", round_id=round_id,
        data=data, batch_size=2, challenge_blocks=10, response_blocks=40,
        retry_budget=1, flood_count=0, flood_parallelism=1,
        flood_challenge_blocks=10, affected_decisions=1, faulty_replacements=0,
        campaign_tag="review_trust_boundary", network_rtt_ms=0, keys=keys,
    )
    wrong_states = [1, 3]
    right_states = [3, 3]
    correct_checkpoint = data.checkpoint(right_states)
    arbitrary_checkpoint = sha256(b"malicious-opaque-incorrect-checkpoint")
    ctx.open_contract_round(wrong_states)
    challenge = ctx.open_challenge("ADMIT", data.client_ids[0], 3, "trust_boundary")
    forged_certificate = sha256(b"NO_EVIDENCE_OR_CERTIFICATE_BLOB_EXISTS")
    # Resolver has the authorized key: this is a trust-boundary test, not an
    # attempt to forge its signature or bypass onlyResolver.
    ctx.resolve(challenge, "REVISED", 3, certificate_hash=forged_certificate)
    wrong_roots = tuple(sha256(b"arbitrary:root:" + bytes([i])) for i in range(3))
    ctx.sender.send_one(
        contract.functions.publishResolverFallback(round_id, *wrong_roots, arbitrary_checkpoint),
        keys["resolver"], "malicious_fallback_roots",
    )
    ctx.finalize()
    status = contract.functions.getRoundStatus(round_id).call()
    accepted_wrong_checkpoint = int(status[0]) == 5 and bytes(status[9]) == arbitrary_checkpoint
    records = {
        "chain_id": int(w3.eth.chain_id), "client_version": str(w3.client_version),
        "round_id": int(round_id),
        "authorized_resolver_used": True,
        "certificate_hash_nonzero_but_unverified": forged_certificate.hex(),
        "arbitrary_roots_accepted": accepted_wrong_checkpoint,
        "incorrect_checkpoint_finalized": accepted_wrong_checkpoint,
        "published_checkpoint": bytes(status[9]).hex(),
        "correct_checkpoint": correct_checkpoint.hex(),
        "txs": [{"phase": tx.phase, "hash": tx.tx_hash, "status": tx.status,
                 "gas": tx.gas_used, "block": tx.block_number} for tx in ctx.sender.metrics],
        "interpretation": (
            "The contract authenticates a trusted resolver address, not the semantic correctness "
            "of its certificateHash or state roots. The C1/T3/evidence policy and resolver trust "
            "assumptions are therefore essential. This is NOT a bypass of onlyResolver."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"accepted_wrong_checkpoint": accepted_wrong_checkpoint, "output": str(args.output)}))
    # Detect changed behavior, but no assertion that the vulnerability must remain.


if __name__ == "__main__":
    main()
