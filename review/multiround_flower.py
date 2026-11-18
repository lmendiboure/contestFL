#!/usr/bin/env python3
"""One REAL sequential 20-round FL trajectory under one ledger design.

A fresh Flower training occurs at each round. Its input is the reconstructed
floating-point model from the previous *on-chain finalized* checkpoint. The
runner refuses to proceed after any incorrect/missing ledger finalization.
Each (seed, design) runs on a fresh Besu deployment managed by the shell driver.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.run_scenarios import load_contracts, private_key
from review.flower_policy_replay import prepare_data
from review.paired_policies import compare_policy
from ml.multiround_state import model_digest, read_model, schedule, metrics_summary

FIELDS = (
    "policy", "trajectory_seed", "round", "round_seed", "workload",
    "input_model_digest", "next_model_digest", "finalized_checkpoint",
    "flower_train_ms", "artifact_processing_ms", "ledger_wall_ms",
    "full_round_wall_ms", "gas_total", "tx_count", "correct_checkpoint_finalized",
    "error", "round_id", "artifact_bytes", "flower_clients",
)


def save_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy", choices=("contestfl", "eager_full"), required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--rounds", type=int, default=20)
    p.add_argument("--fault-rounds", default="6,13,19")
    p.add_argument("--clients", type=int, default=2)
    p.add_argument("--samples-per-client", type=int, default=128)
    p.add_argument("--window-blocks", type=int, default=11)
    p.add_argument("--response-blocks", type=int, default=120)
    p.add_argument("--port", type=int, default=8087)
    p.add_argument("--data-dir", default="/data")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--rpc", default=os.getenv("RPC_URL", "http://node1:8545"))
    args = p.parse_args()
    fault_rounds = [] if not args.fault_rounds.strip() else [int(x) for x in args.fault_rounds.split(",")]
    plan = schedule(args.seed, args.rounds, fault_rounds)
    if args.window_blocks < 1 or args.response_blocks < 1 or args.clients < 2:
        p.error("positive block windows and at least two clients required")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        p.error("output directory exists and is not empty: refusing to overwrite results")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 90}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        raise RuntimeError("Besu RPC unavailable")
    deployment = (ROOT / "network/contracts.json").read_bytes()
    contracts = load_contracts(w3)[:3]
    addresses = json.loads((ROOT / "network/secrets/addresses.json").read_text())
    keys = {name: private_key(name) for name in addresses}
    (args.output_dir / "CONFIG.json").write_text(json.dumps({
        "policy": args.policy, "seed": args.seed, "rounds": args.rounds,
        "fault_rounds": fault_rounds, "clients": args.clients,
        "samples_per_client": args.samples_per_client,
        "window_blocks": args.window_blocks, "response_blocks": args.response_blocks,
        "chain_id": w3.eth.chain_id,
        "deployment_sha256": hashlib.sha256(deployment).hexdigest(),
        "design": "sequential FL model handoff gated by verified on-chain finalization",
        "limits": ["one same-host QBFT network per (seed,policy)",
                   "not pipelined throughput", "same MNIST partition across rounds",
                   "fixed-point round-to-round reconstructed model"],
    }, indent=2) + "\n")
    rows: list[dict] = []
    accepted = None
    previous_hash = None
    start_all = time.monotonic()
    for index, (round_seed, workload) in enumerate(plan, start=1):
        begin = time.monotonic()
        folder = args.output_dir / f"round_{index:02d}"
        folder.mkdir()
        row = {
            "policy": args.policy, "trajectory_seed": args.seed,
            "round": index, "round_seed": round_seed, "workload": workload,
            "input_model_digest": "", "next_model_digest": "",
            "finalized_checkpoint": "", "flower_train_ms": 0,
            "artifact_processing_ms": 0, "ledger_wall_ms": 0,
            "full_round_wall_ms": 0, "gas_total": 0, "tx_count": 0,
            "correct_checkpoint_finalized": False, "error": "",
            "round_id": args.seed * 10000 + index, "artifact_bytes": 0,
            "flower_clients": args.clients,
        }
        try:
            command = [sys.executable, "ml/flower_mnist_e2e.py",
                       "--skip-chain", "--clients", str(args.clients),
                       "--samples-per-client", str(args.samples_per_client),
                       "--local-epochs", "1", "--seed", str(round_seed),
                       "--port", str(args.port), "--data-dir", args.data_dir,
                       "--output-dir", str(folder)]
            if accepted is not None:
                command += ["--initial-params", str(accepted)]
            with (folder / "flower_stdout.log").open("w") as log:
                subprocess.run(command, cwd=ROOT, stdout=log,
                               stderr=subprocess.STDOUT, check=True)
            data, meta = prepare_data(folder)
            if index > 1 and meta["input_model_digest"] != previous_hash:
                raise AssertionError("Flower input != previous on-chain accepted model")
            row["input_model_digest"] = meta["input_model_digest"]
            row["next_model_digest"] = meta["candidate_model_digest"]
            row["flower_train_ms"] = meta["flower_train_ms"]
            row["artifact_processing_ms"] = meta["artifact_processing_ms"]
            row["artifact_bytes"] = meta["artifact_bytes_total"]
            policy_args = SimpleNamespace(validators=4, batch_size=50,
                      challenge_blocks=args.window_blocks,
                      response_blocks=args.response_blocks, retry_budget=2,
                      update_dim=len(data.updates[0]),
                      tag=f"multiround_{args.seed}_{args.policy}")
            result = compare_policy(w3, contracts, keys, args.policy, data,
                    args.clients, index, row["round_id"], workload,
                    round_seed, policy_args)
            row["ledger_wall_ms"] = float(result["wall_ms"])
            row["gas_total"] = int(result["gas_total"])
            row["tx_count"] = int(result["tx_count"])
            row["correct_checkpoint_finalized"] = bool(result["correct_checkpoint_finalized"])
            row["finalized_checkpoint"] = meta["checkpoint"] if row["correct_checkpoint_finalized"] else ""
            row["error"] = result["error"]
            (folder / "ledger_result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
            if row["error"] or not row["correct_checkpoint_finalized"]:
                raise RuntimeError("ledger did not finalize the expected canonical checkpoint: " + str(row["error"]))
            # Only now make the candidate next model eligible for subsequent FL.
            candidate = folder / "CANDIDATE_NEXT_MODEL.npz"
            accepted = folder / "FINALIZED_MODEL.npz"
            shutil.copyfile(candidate, accepted)
            from ml.flower_mnist_e2e import MnistNet, model_ndarrays
            from ml.multiround_state import read_model
            ref = model_ndarrays(MnistNet())
            if model_digest(read_model(accepted, ref)) != meta["candidate_model_digest"]:
                raise AssertionError("candidate model digest mismatched after ledger finalization")
            previous_hash = meta["candidate_model_digest"]
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            (folder / "FAILURE.txt").write_text(row["error"] + "\n" + traceback.format_exc())
        finally:
            row["full_round_wall_ms"] = round((time.monotonic() - begin) * 1000, 3)
            rows.append(row)
            save_rows(args.output_dir / "rounds.csv", rows)
            print(json.dumps({k: row[k] for k in (
                "policy", "round", "workload", "correct_checkpoint_finalized",
                "full_round_wall_ms", "gas_total", "error")}), flush=True)
        if row["error"] or not row["correct_checkpoint_finalized"]:
            break  # No silent skipping of the failed checkpoint.
    summary = metrics_summary(rows)
    summary.update({"policy": args.policy, "seed": args.seed,
                    "target_rounds": args.rounds, "stopped_early": len(rows) < args.rounds,
                    "successful": len(rows) == args.rounds and all(x["correct_checkpoint_finalized"] for x in rows),
                    "trajectory_wall_ms": round((time.monotonic() - start_all) * 1000, 3)})
    (args.output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    if not summary["successful"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
