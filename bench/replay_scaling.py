#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import multiprocessing as mp
import platform
import resource
import statistics
import time
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: Sequence[float], p: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * p
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def parse_ints(raw: str) -> list[int]:
    return [int(value) for value in raw.split(",") if value.strip()]


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"no rows to write to {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def replay_once(clients: int, update_bytes: int, seed: int) -> dict:
    """Measure a memory-bounded deterministic aggregation replay.

    Only one client update is resident at a time. Update generation is measured
    separately and excluded from verification_ms. The verification path hashes
    each committed update, accumulates it into an int64 canonical sum, and hashes
    the resulting checkpoint.
    """
    if clients <= 0:
        raise ValueError("clients must be positive")
    if update_bytes <= 0 or update_bytes % 4:
        raise ValueError("update_bytes must be positive and divisible by four")

    dim = update_bytes // 4
    rng = np.random.default_rng(seed)
    accumulator = np.zeros(dim, dtype=np.int64)
    generation_ns = 0
    hashing_ns = 0
    aggregation_ns = 0
    digest_chain = hashlib.sha256(b"ContestFL:update-digests")

    wall_started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()

    for client_index in range(clients):
        started = time.perf_counter_ns()
        update = rng.integers(-32_768, 32_767, size=dim, dtype=np.int32)
        generation_ns += time.perf_counter_ns() - started

        started = time.perf_counter_ns()
        update_digest = hashlib.sha256(memoryview(update).cast("B")).digest()
        digest_chain.update(client_index.to_bytes(8, "big"))
        digest_chain.update(update_digest)
        hashing_ns += time.perf_counter_ns() - started

        started = time.perf_counter_ns()
        np.add(accumulator, update, out=accumulator, casting="unsafe")
        aggregation_ns += time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    checkpoint = hashlib.sha256(
        b"ContestFL:canonical-aggregate"
        + clients.to_bytes(8, "big")
        + digest_chain.digest()
        + memoryview(accumulator).cast("B")
    ).hexdigest()
    checkpoint_ns = time.perf_counter_ns() - started

    wall_ns = time.perf_counter_ns() - wall_started
    cpu_ns = time.process_time_ns() - cpu_started
    verification_ns = hashing_ns + aggregation_ns + checkpoint_ns
    artifact_bytes = clients * update_bytes
    peak_rss_kib = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

    return {
        "clients": clients,
        "update_bytes": update_bytes,
        "artifact_bytes": artifact_bytes,
        "generation_ms": generation_ns / 1e6,
        "hash_ms": hashing_ns / 1e6,
        "aggregate_ms": aggregation_ns / 1e6,
        "checkpoint_ms": checkpoint_ns / 1e6,
        "verification_ms": verification_ns / 1e6,
        "wall_ms": wall_ns / 1e6,
        "cpu_ms": cpu_ns / 1e6,
        "verification_throughput_mib_s": (
            artifact_bytes / (1024 * 1024) / (verification_ns / 1e9)
            if verification_ns > 0
            else math.inf
        ),
        "peak_rss_kib": peak_rss_kib,
        "checkpoint": checkpoint,
    }


def repetitions_for(
    update_bytes: int,
    rounds: int,
    large_rounds: int,
    huge_rounds: int,
    large_threshold: int,
    huge_threshold: int,
) -> int:
    if update_bytes >= huge_threshold:
        return huge_rounds
    if update_bytes >= large_threshold:
        return large_rounds
    return rounds


def _run_replay_config(payload: tuple[int, int, int, int, int]) -> list[dict]:
    clients, update_bytes, measured_rounds, warmup, seed = payload
    rows: list[dict] = []
    for repetition in range(-warmup, measured_rounds):
        row = replay_once(
            clients=clients,
            update_bytes=update_bytes,
            seed=seed + clients * 1_000_003 + update_bytes * 17 + repetition,
        )
        row["repetition"] = repetition
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Memory-bounded deterministic aggregate replay scaling benchmark"
    )
    parser.add_argument("--clients", default="10,50,100")
    parser.add_argument("--update-bytes", default="4096,262144,1048576,10485760")
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--large-rounds", type=int, default=15)
    parser.add_argument("--huge-rounds", type=int, default=5)
    parser.add_argument("--large-threshold-bytes", type=int, default=1_048_576)
    parser.add_argument("--huge-threshold-bytes", type=int, default=10_485_760)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260805)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--isolate-configs", action="store_true",
        help="Run every (clients, update size) configuration in a fresh child process.",
    )
    args = parser.parse_args()

    if min(args.rounds, args.large_rounds, args.huge_rounds) <= 0:
        raise ValueError("all repetition counts must be positive")

    clients_values = parse_ints(args.clients)
    update_sizes = parse_ints(args.update_bytes)
    run_dir = ROOT / args.run_dir
    raw_dir = run_dir / "raw"
    raw_rows: list[dict] = []

    for clients in clients_values:
        for update_bytes in update_sizes:
            measured_rounds = repetitions_for(
                update_bytes,
                args.rounds,
                args.large_rounds,
                args.huge_rounds,
                args.large_threshold_bytes,
                args.huge_threshold_bytes,
            )
            warmup = 0 if update_bytes >= args.huge_threshold_bytes else args.warmup
            payload = (clients, update_bytes, measured_rounds, warmup, args.seed)
            if args.isolate_configs:
                context = mp.get_context("spawn")
                with context.Pool(processes=1, maxtasksperchild=1) as pool:
                    config_rows = pool.apply(_run_replay_config, (payload,))
            else:
                config_rows = _run_replay_config(payload)

            for row in config_rows:
                repetition = int(row["repetition"])
                if repetition >= 0:
                    raw_rows.append(row)
                print(
                    json.dumps(
                        {
                            "clients": clients,
                            "update_bytes": update_bytes,
                            "repetition": repetition,
                            "verification_ms": round(row["verification_ms"], 3),
                            "throughput_mib_s": round(row["verification_throughput_mib_s"], 2),
                        }
                    ),
                    flush=True,
                )

    write_csv(raw_dir / "replay_scaling_raw.csv", raw_rows)

    summary_rows: list[dict] = []
    for clients in clients_values:
        for update_bytes in update_sizes:
            group = [
                row
                for row in raw_rows
                if row["clients"] == clients and row["update_bytes"] == update_bytes
            ]
            verification = [float(row["verification_ms"]) for row in group]
            hashing = [float(row["hash_ms"]) for row in group]
            aggregation = [float(row["aggregate_ms"]) for row in group]
            throughput = [float(row["verification_throughput_mib_s"]) for row in group]
            summary_rows.append(
                {
                    "clients": clients,
                    "update_bytes": update_bytes,
                    "artifact_bytes": clients * update_bytes,
                    "runs": len(group),
                    "hash_ms_median": statistics.median(hashing),
                    "aggregate_ms_median": statistics.median(aggregation),
                    "verification_ms_median": statistics.median(verification),
                    "verification_ms_q1": percentile(verification, 0.25),
                    "verification_ms_q3": percentile(verification, 0.75),
                    "verification_ms_p95": percentile(verification, 0.95),
                    "throughput_mib_s_median": statistics.median(throughput),
                    "peak_rss_kib_max": max(int(row["peak_rss_kib"]) for row in group),
                }
            )
    write_csv(run_dir / "replay_scaling_summary.csv", summary_rows)

    metadata = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "clients": clients_values,
        "updateBytes": update_sizes,
        "rounds": args.rounds,
        "largeRounds": args.large_rounds,
        "hugeRounds": args.huge_rounds,
        "warmup": args.warmup,
        "isolatedConfigs": args.isolate_configs,
        "method": (
            "One update is generated at a time. Generation is reported separately. "
            "Verification hashes every update, accumulates a canonical int64 sum, and hashes the checkpoint."
        ),
        "limitation": (
            "The benchmark measures an in-memory replay kernel. It excludes artifact-store retrieval, "
            "decryption, deserialization, and wide-area transfer."
        ),
    }
    (run_dir / "replay_scaling_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"rawRows": len(raw_rows), "summaryRows": len(summary_rows)}, indent=2))


if __name__ == "__main__":
    main()
