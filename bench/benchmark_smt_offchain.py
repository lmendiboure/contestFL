#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

try:
    from .smt import SparseMerkleMap
except ImportError:
    from smt import SparseMerkleMap

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Sample:
    clients: int
    depth: int
    repetition: int
    operation: str
    wall_ms: float
    cpu_ms: float
    proof_bytes: int
    verified: bool


def digest(label: bytes, index: int) -> bytes:
    return hashlib.sha256(label + index.to_bytes(8, "big")).digest()


def timed(operation: Callable[[], tuple[int, bool]]) -> tuple[float, float, int, bool]:
    wall_start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    proof_bytes, verified = operation()
    cpu_ms = (time.process_time_ns() - cpu_start) / 1e6
    wall_ms = (time.perf_counter_ns() - wall_start) / 1e6
    return wall_ms, cpu_ms, proof_bytes, verified


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = pos - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def write_csv(path: Path, rows: Iterable[dict]) -> None:
    records = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def benchmark_size(clients: int, depth: int, repetitions: int, warmup: int) -> list[Sample]:
    entries = [(digest(b"ContestFL:offchain:key", i), digest(b"ContestFL:offchain:value", i)) for i in range(clients)]
    target_key = entries[0][0]
    replacement_value = digest(b"ContestFL:offchain:replacement", clients)
    samples: list[Sample] = []

    for repetition in range(-warmup, repetitions):
        def build() -> tuple[int, bool]:
            tree = SparseMerkleMap(depth)
            tree.update(entries)
            root = tree.root
            return 0, bool(root)

        wall, cpu, proof_bytes, ok = timed(build)
        if repetition >= 0:
            samples.append(Sample(clients, depth, repetition, "build_and_root", wall, cpu, proof_bytes, ok))

        tree = SparseMerkleMap(depth)
        tree.update(entries)
        _ = tree.root

        def update_and_root() -> tuple[int, bool]:
            tree.set(target_key, replacement_value)
            root = tree.root
            return 0, bool(root)

        wall, cpu, proof_bytes, ok = timed(update_and_root)
        if repetition >= 0:
            samples.append(Sample(clients, depth, repetition, "single_update_and_root", wall, cpu, proof_bytes, ok))

        # Restore a stable tree for proof generation and verification.
        proof_tree = SparseMerkleMap(depth)
        proof_tree.update(entries)
        expected_root = proof_tree.root

        proof_holder: dict[str, object] = {}

        def generate_proof() -> tuple[int, bool]:
            proof = proof_tree.prove(target_key)
            proof_holder["proof"] = proof
            return len(proof.siblings) * 32 + len(proof.value) + 1, proof.exists

        wall, cpu, proof_bytes, ok = timed(generate_proof)
        if repetition >= 0:
            samples.append(Sample(clients, depth, repetition, "proof_generation", wall, cpu, proof_bytes, ok))

        proof = proof_holder["proof"]

        def verify_proof() -> tuple[int, bool]:
            valid = proof_tree.verify(target_key, proof, expected_root)  # type: ignore[arg-type]
            return len(proof.siblings) * 32 + len(proof.value) + 1, valid  # type: ignore[attr-defined]

        wall, cpu, proof_bytes, ok = timed(verify_proof)
        if repetition >= 0:
            samples.append(Sample(clients, depth, repetition, "proof_verification", wall, cpu, proof_bytes, ok))

    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description="Reference off-chain sparse-Merkle microbenchmark")
    parser.add_argument("--clients", default="10,100,500")
    parser.add_argument("--depth", type=int, default=32)
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    client_sizes = [int(item) for item in args.clients.split(",") if item]
    if any(size <= 0 for size in client_sizes):
        raise ValueError("client counts must be positive")
    if args.repetitions <= 0 or args.warmup < 0:
        raise ValueError("invalid repetition count")

    samples: list[Sample] = []
    for clients in client_sizes:
        samples.extend(benchmark_size(clients, args.depth, args.repetitions, args.warmup))

    if not all(sample.verified for sample in samples):
        raise RuntimeError("an off-chain SMT operation failed its correctness check")

    out = ROOT / args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    raw_records = [asdict(sample) for sample in samples]
    write_csv(out / "smt_offchain_raw.csv", raw_records)

    summary: list[dict[str, object]] = []
    for clients in client_sizes:
        for operation in sorted({sample.operation for sample in samples}):
            subset = [sample for sample in samples if sample.clients == clients and sample.operation == operation]
            wall = [sample.wall_ms for sample in subset]
            cpu = [sample.cpu_ms for sample in subset]
            summary.append({
                "clients": clients,
                "depth": args.depth,
                "operation": operation,
                "runs": len(subset),
                "wall_ms_median": statistics.median(wall),
                "wall_ms_p95": percentile(wall, 0.95),
                "cpu_ms_median": statistics.median(cpu),
                "cpu_ms_p95": percentile(cpu, 0.95),
                "proof_bytes": max(sample.proof_bytes for sample in subset),
                "success_rate": sum(sample.verified for sample in subset) / len(subset),
            })
    write_csv(out / "smt_offchain_summary.csv", summary)

    at_500 = [row for row in summary if row["clients"] == 500]
    report = {
        "implementation": "bench.smt.SparseMerkleMap reference implementation",
        "interpretation": (
            "This implementation recomputes all populated levels when root or proof is requested; "
            "the measurements are conservative implementation costs, not an optimized incremental-tree claim."
        ),
        "depth": args.depth,
        "clients": client_sizes,
        "repetitions": args.repetitions,
        "warmup": args.warmup,
        "summary": summary,
    }
    (out / "SMT_OFFCHAIN_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Off-chain sparse-Merkle microbenchmark",
        "",
        f"- Depth: **{args.depth}**",
        f"- Retained repetitions per point: **{args.repetitions}**",
        f"- Client populations: **{', '.join(map(str, client_sizes))}**",
        "- Correctness failures: **0**",
        "",
        "## 500-client result",
        "",
        "| Operation | Median wall time (ms) | p95 wall time (ms) | Proof bytes |",
        "|---|---:|---:|---:|",
    ]
    for row in at_500:
        lines.append(
            f"| {row['operation']} | {row['wall_ms_median']:.3f} | {row['wall_ms_p95']:.3f} | {row['proof_bytes']} |"
        )
    lines.extend([
        "",
        "These measurements cover tree construction, one leaf update followed by root recomputation, proof generation, and proof verification in the dependency-free Python reference implementation. They exclude artifact hashing, disk I/O, network transfer, and EVM verification. The implementation recomputes populated levels rather than maintaining an optimized incremental cache, so the result is a conservative engineering measurement rather than a lower bound.",
    ])
    (out / "SMT_OFFCHAIN_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "samples": len(samples)}, indent=2))


if __name__ == "__main__":
    main()
