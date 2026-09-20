#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from web3 import Web3

try:
    from .run_scenarios import RoundData, TxMetric, TxSender, private_key, sha256
    from .smt import SparseMerkleMap
except ImportError:
    from run_scenarios import RoundData, TxMetric, TxSender, private_key, sha256
    from smt import SparseMerkleMap

ROOT = Path(__file__).resolve().parents[1]
PHASE_FINALIZED = 3
OUTCOME_REVISED = 1


@dataclass
class RootOnlyRound:
    campaign_tag: str
    design: str
    workload: str
    validators: int
    clients: int
    repetition: int
    round_id: int
    semantic_ok: bool
    correct_checkpoint_finalized: bool
    total_ms: float
    tx_count: int
    gas_total: int
    calldata_bytes: int
    first_block: int
    last_block: int
    block_span: int
    proof_bytes: int
    epoch: int
    retries_used: int
    challenge_count: int
    smt_depth: int
    error: str = ""


def write_csv(path: Path, rows: Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    records = [asdict(row) if not isinstance(row, dict) else row for row in rows]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def load_contract(w3: Web3) -> tuple[Any, dict[str, Any]]:
    artifact = json.loads((ROOT / "network" / "contracts.json").read_text(encoding="utf-8"))
    entry = artifact["contracts"]["RootOnlyContestFL"]
    return w3.eth.contract(address=entry["address"], abi=entry["abi"]), artifact


def decision_tree(client_ids: Sequence[bytes], states: Sequence[int], depth: int) -> SparseMerkleMap:
    tree = SparseMerkleMap(depth)
    for client_id, state in zip(client_ids, states):
        tree.set(client_id, bytes([state]))
    return tree


def wait_until_block(w3: Web3, target_exclusive: int, timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    while int(w3.eth.block_number) <= target_exclusive:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"block {target_exclusive + 1} not reached; current={w3.eth.block_number}"
            )
        time.sleep(0.2)


def summarize(sender: TxSender) -> tuple[int, int, int, int, int, int]:
    if not sender.metrics:
        return 0, 0, 0, -1, -1, 0
    blocks = [metric.block_number for metric in sender.metrics]
    return (
        len(sender.metrics),
        sum(metric.gas_used for metric in sender.metrics),
        sum(metric.calldata_bytes for metric in sender.metrics),
        min(blocks),
        max(blocks),
        max(blocks) - min(blocks) + 1,
    )


def run_one(
    *, w3: Web3, contract: Any, validators: int, clients: int, repetition: int,
    workload: str, round_id: int, tag: str, update_dim: int, smt_depth: int,
    challenge_blocks: int, response_blocks: int, retry_budget: int, seed: int,
) -> tuple[RootOnlyRound, list[TxMetric]]:
    data = RoundData.generate(clients, update_dim, seed, smt_depth)
    keys = {
        "coordinator": private_key("coordinator"),
        "resolver": private_key("resolver"),
        "challenger": private_key("challenger0"),
    }
    sender = TxSender(w3, validators, clients, repetition, workload, round_id, tag)
    proof_bytes = 0
    challenge_count = 0
    error = ""
    started = time.perf_counter_ns()

    clean_states = [3] * clients
    initial_states = clean_states.copy()
    if workload == "bad_admission":
        initial_states[0] = 1
    elif workload not in {"clean", "bad_aggregate"}:
        raise ValueError(f"unsupported workload {workload}")

    submission, _, included_initial = data.trees(initial_states)
    initial_decisions = decision_tree(data.client_ids, initial_states, smt_depth)
    expected_checkpoint = data.checkpoint(clean_states)
    initial_checkpoint = (
        sha256(expected_checkpoint + b":root-only:bad-aggregate")
        if workload == "bad_aggregate"
        else data.checkpoint(initial_states)
    )

    try:
        sender.send_one(
            contract.functions.openRound(
                round_id, clients, challenge_blocks, response_blocks, retry_budget
            ),
            keys["coordinator"],
            "open_round",
        )
        sender.send_one(
            contract.functions.publishInitialState(
                round_id,
                submission.root,
                initial_decisions.root,
                included_initial.root,
                initial_checkpoint,
            ),
            keys["coordinator"],
            "publish_roots",
        )

        if workload == "bad_admission":
            proof = initial_decisions.prove(data.client_ids[0])
            proof_bytes = len(proof.siblings) * 32 + len(proof.value) + 1
            evidence_hash = sha256(
                b"ContestFL:root-only:bad-admission"
                + round_id.to_bytes(32, "big")
                + data.client_ids[0]
                + initial_decisions.root
            )
            next_id = int(contract.functions.nextChallengeId().call())
            sender.send_one(
                contract.functions.openDecisionChallenge(
                    round_id,
                    data.client_ids[0],
                    1,
                    list(proof.siblings),
                    sha256(b"wrong-admission"),
                    evidence_hash,
                ),
                keys["challenger"],
                "challenge_with_proof",
            )
            challenge_count = 1

            corrected_decisions = decision_tree(data.client_ids, clean_states, smt_depth)
            _, _, included_corrected = data.trees(clean_states)
            certificate = sha256(
                b"ContestFL:root-only:resolver-certificate"
                + next_id.to_bytes(32, "big")
                + corrected_decisions.root
                + expected_checkpoint
            )
            sender.send_one(
                contract.functions.resolveDecisionChallenge(
                    next_id,
                    OUTCOME_REVISED,
                    corrected_decisions.root,
                    included_corrected.root,
                    expected_checkpoint,
                    certificate,
                ),
                keys["resolver"],
                "resolve_and_replace_roots",
            )
        elif workload == "bad_aggregate":
            evidence_hash = sha256(
                b"ContestFL:root-only:bad-aggregate"
                + round_id.to_bytes(32, "big")
                + included_initial.root
                + initial_checkpoint
                + expected_checkpoint
            )
            next_id = int(contract.functions.nextChallengeId().call())
            sender.send_one(
                contract.functions.openAggregateChallenge(
                    round_id,
                    sha256(b"checkpoint-mismatch"),
                    evidence_hash,
                ),
                keys["challenger"],
                "aggregate_challenge",
            )
            challenge_count = 1
            certificate = sha256(
                b"ContestFL:root-only:aggregate-certificate"
                + next_id.to_bytes(32, "big")
                + included_initial.root
                + expected_checkpoint
            )
            sender.send_one(
                contract.functions.resolveDecisionChallenge(
                    next_id,
                    OUTCOME_REVISED,
                    initial_decisions.root,
                    included_initial.root,
                    expected_checkpoint,
                    certificate,
                ),
                keys["resolver"],
                "resolve_aggregate_and_replace_checkpoint",
            )

        round_state = contract.functions.rounds(round_id).call()
        challenge_end_block = int(round_state[7])
        wait_until_block(w3, challenge_end_block)
        sender.send_one(
            contract.functions.finalize(round_id),
            keys["coordinator"],
            "finalize",
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"

    total_ms = (time.perf_counter_ns() - started) / 1e6
    state = contract.functions.rounds(round_id).call()
    # Solidity getter field order follows the Round struct declaration.
    epoch = int(state[3])
    retries_used = int(state[6])
    phase = int(state[8])
    checkpoint = bytes(state[12])
    semantic_ok = not error and phase == PHASE_FINALIZED and checkpoint == expected_checkpoint
    tx_count, gas_total, calldata, first_block, last_block, block_span = summarize(sender)
    metric = RootOnlyRound(
        campaign_tag=tag,
        design="root_only",
        workload=workload,
        validators=validators,
        clients=clients,
        repetition=repetition,
        round_id=round_id,
        semantic_ok=semantic_ok,
        correct_checkpoint_finalized=checkpoint == expected_checkpoint and phase == PHASE_FINALIZED,
        total_ms=total_ms,
        tx_count=tx_count,
        gas_total=gas_total,
        calldata_bytes=calldata,
        first_block=first_block,
        last_block=last_block,
        block_span=block_span,
        proof_bytes=proof_bytes,
        epoch=epoch,
        retries_used=retries_used,
        challenge_count=challenge_count,
        smt_depth=smt_depth,
        error=error,
    )
    return metric, sender.metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Root-only versus materialized ContestFL ablation")
    parser.add_argument("--validators", type=int, default=4)
    parser.add_argument("--clients", default="10,100,500")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--workloads", default="clean,bad_admission,bad_aggregate")
    parser.add_argument("--update-dim", type=int, default=1024)
    parser.add_argument("--smt-depth", type=int, default=32)
    parser.add_argument("--challenge-blocks", type=int, default=1)
    parser.add_argument("--response-blocks", type=int, default=4)
    parser.add_argument("--retry-budget", type=int, default=1)
    parser.add_argument("--tag", default="root_only_ablation")
    parser.add_argument("--rpc", default=os.getenv("RPC_URL", "http://node1:8545"))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=20260806)
    args = parser.parse_args()

    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        raise RuntimeError(f"RPC unavailable: {args.rpc}")
    contract, deployment = load_contract(w3)
    clients_list = [int(item) for item in args.clients.split(",") if item]
    workloads = [item for item in args.workloads.split(",") if item]
    rows: list[RootOnlyRound] = []
    transactions: list[TxMetric] = []
    round_id = int(time.time_ns() // 1_000_000) * 1_000_000

    for clients in clients_list:
        for repetition in range(-args.warmup, args.rounds):
            order = workloads.copy()
            random.Random(args.seed + clients * 100 + repetition).shuffle(order)
            for workload in order:
                round_id += 1
                metric, txs = run_one(
                    w3=w3,
                    contract=contract,
                    validators=args.validators,
                    clients=clients,
                    repetition=repetition,
                    workload=workload,
                    round_id=round_id,
                    tag=args.tag,
                    update_dim=args.update_dim,
                    smt_depth=args.smt_depth,
                    challenge_blocks=args.challenge_blocks,
                    response_blocks=args.response_blocks,
                    retry_budget=args.retry_budget,
                    seed=args.seed + round_id,
                )
                if repetition >= 0:
                    rows.append(metric)
                    transactions.extend(txs)
                print(json.dumps({
                    "tag": args.tag,
                    "design": "root_only",
                    "workload": workload,
                    "clients": clients,
                    "repetition": repetition,
                    "gas": metric.gas_total,
                    "blocks": metric.block_span,
                    "proofBytes": metric.proof_bytes,
                    "error": bool(metric.error),
                }), flush=True)

    out = ROOT / args.output_dir
    safe_tag = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in args.tag)
    write_csv(out / f"root_only_rounds_{safe_tag}_v{args.validators}.csv", rows)
    write_csv(out / f"root_only_transactions_{safe_tag}_v{args.validators}.csv", transactions)
    metadata = {
        "tag": args.tag,
        "validators": args.validators,
        "clients": clients_list,
        "workloads": workloads,
        "rounds": args.rounds,
        "warmup": args.warmup,
        "smtDepth": args.smt_depth,
        "updateDim": args.update_dim,
        "deployment": deployment,
    }
    (out / f"root_only_metadata_{safe_tag}_v{args.validators}.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    failures = [row for row in rows if not row.semantic_ok]
    print(json.dumps({"output": str(out), "rounds": len(rows), "failures": len(failures)}, indent=2))
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
