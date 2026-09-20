#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import sqlite3
import statistics
import time
from pathlib import Path
from typing import Sequence

import numpy as np

from smt import SparseMerkleMap

ROOT = Path(__file__).resolve().parents[1]


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def percentile(values: Sequence[float], p: float) -> float:
    ordered = sorted(values)
    q = (len(ordered) - 1) * p
    low = int(q)
    high = math.ceil(q)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (q - low)


def central_log_round(client_ids: list[bytes], update_hashes: list[bytes], roots: tuple[bytes, bytes, bytes], checkpoint: bytes) -> float:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA journal_mode=MEMORY")
    connection.execute("CREATE TABLE submissions (client BLOB PRIMARY KEY, update_hash BLOB NOT NULL)")
    connection.execute("CREATE TABLE state (submission_root BLOB, admitted_root BLOB, aggregate_root BLOB, checkpoint BLOB)")
    started = time.perf_counter_ns()
    with connection:
        connection.executemany("INSERT INTO submissions VALUES (?, ?)", zip(client_ids, update_hashes))
        connection.execute("INSERT INTO state VALUES (?, ?, ?, ?)", (*roots, checkpoint))
    connection.commit()
    elapsed = (time.perf_counter_ns() - started) / 1e6
    connection.close()
    return elapsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", default="10,50,100")
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--update-dim", type=int, default=1024)
    parser.add_argument("--smt-depth", type=int, default=32)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=20260803)
    args = parser.parse_args()

    raw = []
    for clients in [int(item) for item in args.clients.split(",") if item]:
        for repetition in range(-args.warmup, args.rounds):
            rng = np.random.default_rng(args.seed + clients * 10_000 + repetition)
            client_ids = [sha256(b"client" + i.to_bytes(8, "big")) for i in range(clients)]
            updates = [rng.integers(-32_768, 32_767, args.update_dim, dtype=np.int32) for _ in range(clients)]
            update_hashes = [sha256(update.tobytes()) for update in updates]

            started = time.perf_counter_ns()
            submission = SparseMerkleMap(args.smt_depth)
            admitted = SparseMerkleMap(args.smt_depth)
            included = SparseMerkleMap(args.smt_depth)
            for client_id, update_hash in zip(client_ids, update_hashes):
                submission.set(client_id, update_hash)
                admitted.set(client_id, b"\x01")
                included.set(client_id, b"\x01")
            roots = (submission.root, admitted.root, included.root)
            smt_ms = (time.perf_counter_ns() - started) / 1e6

            started = time.perf_counter_ns()
            aggregate = np.sum(np.stack(updates), axis=0, dtype=np.int64)
            checkpoint = sha256(len(updates).to_bytes(8, "big") + aggregate.tobytes())
            replay_ms = (time.perf_counter_ns() - started) / 1e6

            log_ms = central_log_round(client_ids, update_hashes, roots, checkpoint)
            if repetition >= 0:
                raw.append(
                    {
                        "clients": clients,
                        "repetition": repetition,
                        "update_dim": args.update_dim,
                        "smt_ms": smt_ms,
                        "eager_replay_ms": replay_ms,
                        "central_log_ms": log_ms,
                    }
                )

    output = ROOT / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    raw_path = output / "local_baselines_raw.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw[0]))
        writer.writeheader()
        writer.writerows(raw)

    summary = []
    for clients in sorted({row["clients"] for row in raw}):
        rows = [row for row in raw if row["clients"] == clients]
        record = {"clients": clients, "rounds": len(rows), "update_dim": args.update_dim}
        for metric in ("smt_ms", "eager_replay_ms", "central_log_ms"):
            values = [float(row[metric]) for row in rows]
            record[f"{metric}_mean"] = statistics.fmean(values)
            record[f"{metric}_median"] = statistics.median(values)
            record[f"{metric}_p95"] = percentile(values, 0.95)
            record[f"{metric}_std"] = statistics.stdev(values) if len(values) > 1 else 0.0
        summary.append(record)
    summary_path = output / "local_baselines_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)

    metadata = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "clients": sorted({row["clients"] for row in raw}),
        "rounds": args.rounds,
        "updateDim": args.update_dim,
        "smtDepth": args.smt_depth,
    }
    (output / "local_baselines_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"raw": str(raw_path), "summary": str(summary_path)}, indent=2))


if __name__ == "__main__":
    main()
