#!/usr/bin/env python3
"""Paired on-chain ContestFL policy comparison (NOT published-system reproductions).

Each design receives identical RoundData and the same injected fault scenario.
All local-policy variants use the *same* ContestFLExperiment contract.  The eager
verification design uses EagerVerification and is measured in its natural
pre-finalization workflow.  A full challenge window is waited for where the
policy mandates it; eager has no optimistic challenge window.  Repetitions are
paired by seed, NOT by block height or experiment order.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import random
import time
import traceback
from pathlib import Path
from typing import Any

from web3 import Web3


# Direct invocation (`python review/paired_policies.py`) must resolve the repository packages.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.run_competitor_baselines import load_contracts as load_baselines, run_eager
from bench.run_scenarios import (
    Context, RoundData, load_contracts,
    private_key, sha256,
)

DESIGNS = ("contestfl", "abort_restart", "level_cascade", "eager_full")


def parse_ints(raw: str) -> list[int]:
    values = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if not values or min(values) <= 0:
        raise ValueError("clients must be positive")
    return values


def context(w3: Web3, contracts: tuple, keys: dict[str, str], *, design: str,
            round_id: int, data: RoundData, clients: int, repeat: int,
            args: argparse.Namespace) -> Context:
    return Context(
        w3=w3, contract=contracts[0], logging_contract=contracts[1],
        evidence_contract=contracts[2], validators=args.validators, clients=clients,
        repetition=repeat, scenario="revision_" + design, round_id=round_id,
        data=data, batch_size=args.batch_size, challenge_blocks=args.challenge_blocks,
        response_blocks=args.response_blocks, retry_budget=args.retry_budget,
        flood_count=0, flood_parallelism=1, flood_challenge_blocks=args.challenge_blocks,
        affected_decisions=1, faulty_replacements=0, campaign_tag=args.tag,
        network_rtt_ms=0, keys=keys,
    )


def compare_policy(w3: Web3, contracts: tuple, keys: dict[str, str], design: str,
                   data: RoundData, clients: int, rep: int, base_id: int,
                   workload: str, seed: int, args: argparse.Namespace) -> dict[str, Any]:
    initial = [3] * clients
    if workload == "bad_admission":
        initial[0] = 1
    elif workload == "bad_omission":
        initial[0] = 2
    correct = [3] * clients
    correct_checkpoint = data.checkpoint(correct)
    published_checkpoint = (sha256(correct_checkpoint + b"bad_aggregate")
                            if workload == "bad_aggregate" else data.checkpoint(initial))
    c = context(w3, contracts, keys, design=design, round_id=base_id,
                data=data, clients=clients, repeat=rep, args=args)
    all_contexts = [c]
    started = time.perf_counter_ns()
    verification_cpu_ms = 0.0
    verification_wall_ms = 0.0
    error = ""
    terminal = "UNKNOWN"
    try:
        if design == "eager_full":
            baseline = load_baselines(w3)
            result, _, tx_metrics = run_eager(
                w3=w3, contract=baseline["EagerVerification"],
                keyset={"coordinator": keys["coordinator"], "resolver": keys["resolver"],
                        "submitter": keys["submitter"], "challenger": keys["challenger0"]},
                tag=args.tag, validators=args.validators, clients=clients, repetition=rep,
                round_id=base_id, data=data, workload=workload,
                update_dim=args.update_dim, batch_size=args.batch_size,
                challenge_blocks=args.challenge_blocks, response_blocks=args.response_blocks,
            )
            total_ms = (time.perf_counter_ns() - started) / 1e6
            terminal = result.terminal_state
            # Do not rely on the baseline runner's declared semantic flag
            # alone: independently read the finalized on-chain checkpoint.
            eager_status = baseline["EagerVerification"].functions.getRoundStatus(base_id).call()
            correct_final = (bool(result.correct_checkpoint_finalized)
                             and int(eager_status[0]) == 4  # Eager Phase.FINALIZED
                             and bool(eager_status[2])     # verified
                             and bytes(eager_status[4]) == correct_checkpoint)
            verification_cpu_ms = result.offchain_verify_cpu_ms
            verification_wall_ms = result.offchain_verify_ms
            metrics = tx_metrics
            if not result.semantic_ok:
                error = f"eager failed semantic check: {result.semantic_outcome}"
            last_epoch = 0
        elif workload == "clean":
            # All three on-demand policies follow the same clean protocol path.
            # In the absence of a fault, abort/restart never restarts and the
            # downstream re-audit policy has nothing to recheck.
            c.open_contract_round(correct)
            c.wait_challenge_window()
            c.finalize()
            terminal = "FINALIZED"
            status = c.contract.functions.getRoundStatus(c.round_id).call()
            correct_final = int(status[0]) == 5 and bytes(status[9]) == correct_checkpoint
            last_epoch = int(status[1])
            metrics = c.sender.metrics
            total_ms = (time.perf_counter_ns() - started) / 1e6
            if not correct_final:
                error = "incorrect terminal state/checkpoint"
        else:
            c.open_contract_round(initial, published_checkpoint)
            if workload == "bad_admission":
                evidence = c.admission_evidence(0, observed_state=1, policy_state=3)
                kind, client_id, corrected_state = "ADMIT", data.client_ids[0], 3
            elif workload == "bad_omission":
                evidence = c.inclusion_evidence(0, observed_state=2)
                kind, client_id, corrected_state = "INCLUDE", data.client_ids[0], 3
            elif workload == "bad_aggregate":
                evidence = c.aggregate_evidence(initial, published_checkpoint)
                kind, client_id, corrected_state = "AGGREGATE", bytes(32), 0
            else:
                raise ValueError(f"unsupported workload {workload}")
            if evidence.verdict != "REVISED" or evidence.corrected_state != corrected_state:
                raise AssertionError(f"unexpected {workload} adapter result: {evidence.verdict} / {evidence.corrected_state}")
            verification_cpu_ms += evidence.evidence_generation_cpu_ms + evidence.verification_cpu_ms
            verification_wall_ms += evidence.evidence_generation_ms + evidence.verification_ms
            challenge = c.open_challenge(
                kind, client_id, corrected_state, "paired_" + workload,
                evidence_hash=evidence.evidence_hash,
            )
            c.record_adapter(challenge, evidence)
            if design == "abort_restart":
                # Restart is a clean *new round*: all submissions are resent and
                # the incomplete attempt is included in the reported total cost.
                c.abort("policy_abort_and_restart")
                restarted = context(w3, contracts, keys, design=design + "_restart",
                                    round_id=base_id + 1, data=data,
                                    clients=clients, repeat=rep, args=args)
                all_contexts.append(restarted)
                restarted.open_contract_round(correct)
                restarted.wait_challenge_window()
                restarted.finalize()
                terminal = "FINALIZED_AFTER_RESTART"
                status = restarted.contract.functions.getRoundStatus(restarted.round_id).call()
                correct_final = int(status[0]) == 5 and bytes(status[9]) == correct_checkpoint
                last_epoch = int(status[1])
            else:
                c.resolve(challenge, "REVISED", corrected_state, certificate_hash=evidence.certificate_hash)
                c.publish_replacement(correct, correct_checkpoint)
                if design == "level_cascade" and workload != "bad_aggregate":
                    # Policy design point: a downstream re-audit is warranted
                    # for admission or inclusion corrections; an aggregate
                    # correction has no downstream decision in this schema.
                    downstream = c.aggregate_evidence(correct, correct_checkpoint)
                    if downstream.verdict != "UPHELD":
                        raise AssertionError("correct downstream checkpoint not upheld")
                    verification_cpu_ms += downstream.evidence_generation_cpu_ms + downstream.verification_cpu_ms
                    verification_wall_ms += downstream.evidence_generation_ms + downstream.verification_ms
                    second = c.open_challenge(
                        "AGGREGATE", reason="cascade_downstream_reaudit",
                        evidence_hash=downstream.evidence_hash,
                    )
                    c.record_adapter(second, downstream)
                    c.resolve(second, "UPHELD", certificate_hash=downstream.certificate_hash)
                c.wait_challenge_window()
                c.finalize()
                terminal = "FINALIZED"
                status = c.contract.functions.getRoundStatus(c.round_id).call()
                correct_final = int(status[0]) == 5 and bytes(status[9]) == correct_checkpoint
                last_epoch = int(status[1])
            metrics = [tx for run in all_contexts for tx in run.sender.metrics]
            total_ms = (time.perf_counter_ns() - started) / 1e6
            if not correct_final:
                error = "incorrect terminal state/checkpoint"
    except Exception as exc:
        total_ms = (time.perf_counter_ns() - started) / 1e6
        correct_final = False
        metrics = [tx for run in all_contexts for tx in run.sender.metrics]
        last_epoch = -1
        error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"

    blocks = [metric.block_number for metric in metrics]
    waits = sum(run.challenge_wait_ms for run in all_contexts)
    # This metric is protocol wall clock, NOT real end-to-end FL training time.
    return {
        "tag": args.tag, "workload": workload, "design": design,
        "client_count": clients, "repetition": rep, "seed": seed,
        "round_id": base_id, "terminal": terminal,
        "correct_checkpoint_finalized": bool(correct_final),
        "wall_ms": round(total_ms, 3),
        "protocol_completions_per_hour_proxy": round(3600000 / total_ms, 6) if total_ms > 0 and correct_final else 0.0,
        "challenge_wait_wall_ms": round(waits, 3),
        "gas_total": sum(tx.gas_used for tx in metrics),
        "tx_count": len(metrics),
        "first_block": min(blocks) if blocks else -1,
        "last_block": max(blocks) if blocks else -1,
        "block_span": max(blocks) - min(blocks) + 1 if blocks else 0,
        "calldata_bytes": sum(tx.calldata_bytes for tx in metrics),
        "verification_wall_ms": round(verification_wall_ms, 3),
        "verification_cpu_ms": round(verification_cpu_ms, 3),
        "challenge_blocks": args.challenge_blocks,
        "response_blocks": args.response_blocks,
        "update_dim": args.update_dim,
        "artifact_payload_bytes": clients * args.update_dim * 4,
        "error": error,
    }


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--validators", type=int, default=4)
    p.add_argument("--clients", default="10,50")
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--warmup", type=int, default=1)
    p.add_argument("--designs", default=",".join(DESIGNS))
    p.add_argument("--workloads", default="clean,bad_admission,bad_aggregate")
    p.add_argument("--update-dim", type=int, default=1024)
    p.add_argument("--batch-size", type=int, default=50)
    p.add_argument("--challenge-blocks", type=int, default=10)
    p.add_argument("--response-blocks", type=int, default=20)
    p.add_argument("--retry-budget", type=int, default=2)
    p.add_argument("--smt-depth", type=int, default=32)
    p.add_argument("--tag", default="review_policies")
    p.add_argument("--window-label", default="sized", choices=("sized", "short", "custom"))
    p.add_argument("--allow-failures", action="store_true", help="Retain and report invalid/failed outcomes in short-window sensitivity without aborting the suite")
    p.add_argument("--seed", type=int, default=20261106)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--rpc", default=os.environ.get("RPC_URL", "http://node1:8545"))
    args = p.parse_args()
    if args.rounds < 1 or args.warmup < 0 or args.challenge_blocks <= 0 or args.response_blocks <= 0:
        p.error("rounds > 0, warmup >= 0 and positive deadlines required")
    designs = [x.strip() for x in args.designs.split(",") if x.strip()]
    if not designs or set(designs) - set(DESIGNS) or len(set(designs)) != len(designs):
        p.error(f"designs must be unique and drawn from {DESIGNS}")
    clients_list = parse_ints(args.clients)
    workloads = [x.strip() for x in args.workloads.split(",") if x.strip()]
    allowed_workloads = {"clean", "bad_admission", "bad_omission", "bad_aggregate"}
    if not workloads or len(set(workloads)) != len(workloads) or set(workloads) - allowed_workloads:
        p.error(f"workloads must be distinct and selected from {sorted(allowed_workloads)}")
    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 90}))
    if not w3.is_connected():
        raise RuntimeError(f"Besu RPC unavailable: {args.rpc}")
    contracts = load_contracts(w3)[:3]
    addresses = json.loads((ROOT / "network/secrets/addresses.json").read_text())
    keys = {name: private_key(name) for name in addresses}
    results: list[dict[str, Any]] = []
    serial = int(time.time_ns() // 1000) * 100
    for clients in clients_list:
        for workload_index, workload in enumerate(workloads):
            for rep in range(-args.warmup, args.rounds):
                seed = args.seed + rep * 1000003 + clients * 101 + workload_index * 10000019
                data = RoundData.generate(clients, args.update_dim, seed, args.smt_depth)
                order = list(designs)
                random.Random(args.seed + rep * 19 + clients + workload_index * 7).shuffle(order)
                for design in order:
                    serial += 10
                    row = compare_policy(w3, contracts, keys, design, data, clients,
                                         rep, serial, workload, seed, args)
                    print(json.dumps({k: row[k] for k in (
                        "workload", "design", "client_count", "repetition",
                        "correct_checkpoint_finalized", "wall_ms", "error")}), flush=True)
                    if rep >= 0:
                        row["window_label"] = args.window_label
                        results.append(row)
                        # Crash recovery: retain measured rows after each comparison.
                        write_csv(args.output_dir / "paired_policies_raw.csv", results)
    if not results:
        raise RuntimeError("no measured runs")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "paired_policies_raw.csv", results)
    (args.output_dir / "paired_policies_metadata.json").write_text(json.dumps({
        "description": __doc__, "chain_id": w3.eth.chain_id,
        "client_version": w3.client_version,
        "contracts_json_sha256": hashlib.sha256((ROOT / "network/contracts.json").read_bytes()).hexdigest(),
        "designs": designs, "workloads": workloads,
        "window_label": args.window_label,
        "clients": clients_list, "rounds": args.rounds,
        "warmup": args.warmup, "seed": args.seed, "challenge_blocks": args.challenge_blocks,
        "response_blocks": args.response_blocks, "update_dim": args.update_dim,
        "retry_budget": args.retry_budget, "smt_depth": args.smt_depth,
        "limitations": [
            "same-host sequential QBFT evaluation; policies are self-defined design points",
            "not a reproduction of previously published competitor implementations",
            "no network transfer; artifact bytes denote generated model update payloads",
            "wall duration includes challenge waiting when policy requires it; eager checks prior to finalization",
            "no training computation in this on-chain protocol microbenchmark; throughput is equivalent protocol rounds/hour, NOT trained FL rounds/hour",
            "authorized resolver certificate hash is not semantically verified by Solidity",
        ],
    }, indent=2) + "\n")
    failures = [r for r in results if not r["correct_checkpoint_finalized"] or r["error"]]
    print(json.dumps({"rows": len(results), "failures": len(failures),
                      "output": str(args.output_dir)}))
    if failures and not args.allow_failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
