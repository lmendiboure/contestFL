#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
import time
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: Sequence[float], p: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    low = int(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def replay_once(clients: int, update_bytes: int, seed: int) -> tuple[float, float, str]:
    if update_bytes % 4:
        raise ValueError("update_bytes must be divisible by four for int32 updates")
    dim = update_bytes // 4
    rng = np.random.default_rng(seed)
    accumulator = np.zeros(dim, dtype=np.int64)
    hash_started = time.perf_counter_ns()
    update_hashes = []
    generated = []
    for _ in range(clients):
        update = rng.integers(-32_768, 32_767, size=dim, dtype=np.int32)
        payload = update.tobytes(order="C")
        update_hashes.append(hashlib.sha256(payload).digest())
        generated.append(update)
    hash_ms = (time.perf_counter_ns() - hash_started) / 1e6

    replay_started = time.perf_counter_ns()
    for update in generated:
        accumulator += update.astype(np.int64, copy=False)
    checkpoint = hashlib.sha256(
        b"ContestFL:canonical-aggregate"
        + clients.to_bytes(8, "big")
        + accumulator.tobytes(order="C")
    ).hexdigest()
    replay_ms = (time.perf_counter_ns() - replay_started) / 1e6
    return hash_ms, replay_ms, checkpoint


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure eager versus optimistic deterministic replay cost")
    parser.add_argument("--clients", default="10,25,50")
    parser.add_argument("--update-bytes", default="4096,262144,1048576,10485760")
    parser.add_argument("--challenge-rates", default="0,0.01,0.05,0.1,0.2,0.5,1")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--large-rounds", type=int, default=3)
    parser.add_argument("--large-threshold-bytes", type=int, default=1_048_576)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--seed", type=int, default=20260803)
    args = parser.parse_args()

    run_dir = ROOT / args.run_dir
    raw_dir = run_dir / "raw"
    clients_list = [int(value) for value in args.clients.split(",") if value]
    update_sizes = [int(value) for value in args.update_bytes.split(",") if value]
    challenge_rates = [float(value) for value in args.challenge_rates.split(",") if value]

    raw_rows: list[dict] = []
    for clients in clients_list:
        for update_bytes in update_sizes:
            repetitions = args.large_rounds if update_bytes >= args.large_threshold_bytes else args.rounds
            for repetition in range(repetitions):
                hash_ms, replay_ms, checkpoint = replay_once(
                    clients, update_bytes, args.seed + clients * 100_000 + update_bytes + repetition
                )
                raw_rows.append(
                    {
                        "clients": clients,
                        "update_bytes": update_bytes,
                        "repetition": repetition,
                        "hash_ms": hash_ms,
                        "replay_ms": replay_ms,
                        "total_verification_ms": hash_ms + replay_ms,
                        "artifacts_bytes": clients * update_bytes,
                        "checkpoint": checkpoint,
                    }
                )
    write_csv(raw_dir / "optimistic_replay_raw.csv", raw_rows)

    frame = pd.DataFrame(raw_rows)
    summary_rows: list[dict] = []
    for (clients, update_bytes), group in frame.groupby(["clients", "update_bytes"]):
        values = group["total_verification_ms"].tolist()
        replay_values = group["replay_ms"].tolist()
        hash_values = group["hash_ms"].tolist()
        summary_rows.append(
            {
                "clients": int(clients),
                "update_bytes": int(update_bytes),
                "runs": len(group),
                "artifacts_bytes": int(clients * update_bytes),
                "hash_ms_median": statistics.median(hash_values),
                "replay_ms_median": statistics.median(replay_values),
                "verification_ms_median": statistics.median(values),
                "verification_ms_p95": percentile(values, 0.95),
            }
        )
    write_csv(raw_dir / "optimistic_replay_summary.csv", summary_rows)

    expected_rows: list[dict] = []
    for row in summary_rows:
        eager = float(row["verification_ms_median"])
        for rate in challenge_rates:
            expected_rows.append(
                {
                    **row,
                    "challenge_rate": rate,
                    "eager_verification_cpu_ms_per_round": eager,
                    "optimistic_verification_cpu_ms_per_round": rate * eager,
                    "cpu_saving_percent": 100.0 * (1.0 - rate),
                }
            )
    write_csv(run_dir / "optimistic_regime.csv", expected_rows)

    metadata = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "clients": clients_list,
        "updateBytes": update_sizes,
        "challengeRates": challenge_rates,
        "rounds": args.rounds,
        "largeRounds": args.large_rounds,
        "interpretation": (
            "These measurements isolate deterministic hashing and aggregate replay CPU cost. "
            "They do not include the mandatory challenge-window latency or blockchain correction transactions."
        ),
    }
    (raw_dir / "optimistic_replay_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"raw": len(raw_rows), "expected": len(expected_rows)}, indent=2))


if __name__ == "__main__":
    main()
