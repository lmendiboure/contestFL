#!/usr/bin/env python3
"""Replays one *measured* Flower round's canonical artifacts on paired EVM policies.

The Flower training stage is measured once for each seed, not repeated for each
policy; the same exact artifact bytes and training duration are attributed to
both policies. This is an end-to-end *sequential one-round composition* and not
an observed multi-round steady-state streaming throughput or WAN transfer test.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.run_scenarios import RoundData, load_contracts, private_key, sha256
from review.paired_policies import compare_policy
from ml.canonical_artifact import parse_artifact


def prepare_data(folder: Path) -> tuple[RoundData, dict]:
    manifest = json.loads((folder / "FLOWER_ARTIFACT_REPORT.json").read_text())
    n = int(manifest["clients"])
    payloads = [(folder / f"client_{i}.cflupd").read_bytes() for i in range(n)]
    digests = [hashlib.sha256(p).digest() for p in payloads]
    assert [x.hex() for x in digests] == manifest["artifact_sha256"], "artifact hashes changed"
    parsed = [parse_artifact(p) for p in payloads]
    schemas = [v[1] for v in parsed]
    if any(s != schemas[0] for s in schemas[1:]):
        raise ValueError("different Flower tensor schemas")
    data = RoundData(
        client_ids=[sha256(b"ContestFL:flower-client" + i.to_bytes(8, "big")) for i in range(n)],
        updates=[v[0] for v in parsed], update_hashes=digests, smt_depth=32,
    )
    if data.checkpoint([3] * n).hex() != manifest["checkpoint"]:
        raise ValueError("Flower checkpoint and EVM replay input disagree")
    if not manifest["replay_upheld"]:
        raise ValueError("Flower replay not verified")
    return data, manifest


def first_error_line(value: str | None) -> str:
    """Safe diagnostic preview for an empty or multiline error string."""
    return next(iter((value or "").splitlines()), "")


def evaluate(w3, contracts, keys, data, meta, folder: Path, window: int, response: int,
             repetition: int, seed: int, workload: str) -> list[dict]:
    args = SimpleNamespace(validators=4, batch_size=50, challenge_blocks=window,
                           response_blocks=response, retry_budget=2,
                           update_dim=len(data.updates[0]), tag="flower_paired_v4_extended")
    rows = []
    for i, policy in enumerate(("contestfl", "eager_full")):
        round_id = (int(time.time_ns() // 1000) * 100) + repetition * 100 + i * 10
        row = compare_policy(w3, contracts, keys, policy, data, len(data.updates),
                             repetition, round_id, workload, seed, args)
        common_ms = float(meta["flower_train_ms"]) + float(meta["artifact_processing_ms"])
        elapsed = common_ms + float(row["wall_ms"])
        row.update({
            "flower_seed": seed,
            "flower_train_ms_shared": float(meta["flower_train_ms"]),
            "artifact_processing_ms_shared": float(meta["artifact_processing_ms"]),
            "end_to_end_sequential_ms": elapsed,
            "completed_rounds_per_hour_sequential": 3600000 / elapsed if row["correct_checkpoint_finalized"] and not row["error"] else 0.0,
            "artifact_bytes_measured": int(meta["artifact_bytes_total"]),
            "artifact_digest_set_sha256": hashlib.sha256("".join(meta["artifact_sha256"]).encode()).hexdigest(),
            "training_reused_identically": True,
            "measurement_type": "one_round_sequential_shared_flower_training_plus_measured_EVM",
        })
        rows.append(row)
        print(json.dumps({"folder": str(folder), "policy": policy, "workload": workload,
                          "correct": row["correct_checkpoint_finalized"], "e2e_ms": elapsed,
                          "error": first_error_line(row.get("error"))}), flush=True)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--flower-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--workloads", default="clean,bad_aggregate")
    p.add_argument("--window-blocks", type=int, default=11)
    p.add_argument("--response-blocks", type=int, default=120)
    p.add_argument("--rpc", default=os.getenv("RPC_URL", "http://node1:8545"))
    args = p.parse_args()
    if args.window_blocks <= 0 or args.response_blocks <= 0:
        p.error("positive window/response blocks required")
    workloads = [s.strip() for s in args.workloads.split(",")]
    if not workloads or set(workloads) - {"clean", "bad_aggregate"} or len(set(workloads)) != len(workloads):
        p.error("expected unique clean,bad_aggregate workloads")
    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 90}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        raise RuntimeError("no Besu connection")
    contracts = load_contracts(w3)[:3]
    addresses = json.loads((ROOT / "network/secrets/addresses.json").read_text())
    keys = {name: private_key(name) for name in addresses}
    data, meta = prepare_data(args.flower_dir)
    rows: list[dict] = []
    for work in workloads:
        rows.extend(evaluate(w3, contracts, keys, data, meta, args.flower_dir,
                             args.window_blocks, args.response_blocks, 0, int(meta["seed"]), work))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    if not all(row["correct_checkpoint_finalized"] and not row["error"] for row in rows):
        raise SystemExit("Flower/EVM paired result not fully correct: inspect CSV")


if __name__ == "__main__":
    main()
