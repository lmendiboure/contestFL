#!/usr/bin/env python3
"""Measure the complete local watcher verification pipeline.

Unlike replay_scaling.py, this benchmark includes local artifact lookup, file
reads, commitment verification, canonical artifact parsing/deserialization,
aggregation replay, checkpoint hashing, and challenge-package construction.
It deliberately does not claim to measure wide-area transfer or remote object
store latency; those terms are projected separately from configured bandwidths.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import time
import sys
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ml.canonical_artifact import MAGIC, parse_artifact


def percentile(values: Sequence[float], p: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * p
    lo = int(math.floor(position))
    hi = int(math.ceil(position))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def bootstrap_median_ci(
    values: Sequence[float], *, samples: int, confidence: float, seed: int
) -> tuple[float, float]:
    """Deterministic percentile-bootstrap CI for the sample median."""
    if not values:
        return math.nan, math.nan
    if samples <= 0:
        return math.nan, math.nan
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    data = np.asarray([float(v) for v in values], dtype=np.float64)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, data.size, size=(samples, data.size))
    medians = np.median(data[indices], axis=1)
    alpha = (1.0 - confidence) / 2.0
    return float(np.quantile(medians, alpha)), float(np.quantile(medians, 1.0 - alpha))


def parse_ints(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def parse_floats(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def projected_transfer_ms(artifact_bytes: int, bandwidth_mbps: float) -> float:
    """Ideal serialization time at a nominal decimal Mbit/s line rate."""
    if bandwidth_mbps <= 0:
        raise ValueError("bandwidth_mbps must be positive")
    return artifact_bytes * 8.0 / (bandwidth_mbps * 1_000_000.0) * 1000.0


def write_csv(path: Path, rows: Iterable[dict]) -> None:
    records = list(rows)
    if not records:
        raise ValueError(f"no rows for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def artifact_payload(values: np.ndarray) -> bytes:
    header = {
        "format": "ContestFL-fixed-point-update-v1",
        "scale": 1_000_000,
        "integerDtype": "int32-le",
        "tensorOrder": "watcher-benchmark",
        "values": int(values.size),
        "tensors": [{"name": "flat", "shape": [int(values.size)], "offset": 0, "length": int(values.size)}],
    }
    encoded = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return MAGIC + len(encoded).to_bytes(4, "big") + encoded + values.astype("<i4", copy=False).tobytes(order="C")


def prepare_dataset(dataset_dir: Path, clients: int, update_bytes: int, seed: int) -> Path:
    if update_bytes <= 0 or update_bytes % 4:
        raise ValueError("update_bytes must be positive and divisible by four")
    target = dataset_dir / f"n{clients}_b{update_bytes}"
    manifest_path = target / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("clients") == clients and manifest.get("updateBodyBytes") == update_bytes:
            return manifest_path
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    entries = []
    dim = update_bytes // 4
    for client in range(clients):
        rng = np.random.default_rng(seed + clients * 1_000_003 + update_bytes * 17 + client)
        values = rng.integers(-32_768, 32_767, size=dim, dtype=np.int32)
        payload = artifact_payload(values)
        path = target / f"client_{client:05d}.cflupd"
        path.write_bytes(payload)
        entries.append(
            {
                "client": client,
                "file": path.name,
                "artifactBytes": len(payload),
                "bodyBytes": update_bytes,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest = {
        "format": "ContestFL-watcher-dataset-v1",
        "clients": clients,
        "updateBodyBytes": update_bytes,
        "entries": entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def verify_once(manifest_path: Path, claimed_fault: bool, cache_mode: str = "warm") -> dict:
    total_start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()

    start = time.perf_counter_ns()
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    manifest_ms = (time.perf_counter_ns() - start) / 1e6

    entries = manifest["entries"]
    clients = int(manifest["clients"])
    update_body_bytes = int(manifest["updateBodyBytes"])
    dim = update_body_bytes // 4
    accumulator = np.zeros(dim, dtype=np.int64)
    digest_chain = hashlib.sha256(b"ContestFL:watcher:update-digests")

    read_ns = hash_ns = parse_ns = aggregate_ns = 0
    artifact_bytes = 0
    for entry in entries:
        path = manifest_path.parent / str(entry["file"])
        start = time.perf_counter_ns()
        with path.open("rb") as handle:
            if cache_mode == "fadvise" and hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_DONTNEED"):
                os.posix_fadvise(handle.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
            payload = handle.read()
            if cache_mode == "fadvise" and hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_DONTNEED"):
                # Advisory only: this requests eviction for the next repetition
                # but does not claim a device-level cold-cache measurement.
                os.posix_fadvise(handle.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        read_ns += time.perf_counter_ns() - start
        artifact_bytes += len(payload)

        start = time.perf_counter_ns()
        digest = hashlib.sha256(payload).digest()
        expected = bytes.fromhex(str(entry["sha256"]))
        if digest != expected:
            raise ValueError(f"commitment mismatch for {path}")
        digest_chain.update(int(entry["client"]).to_bytes(8, "big"))
        digest_chain.update(digest)
        hash_ns += time.perf_counter_ns() - start

        start = time.perf_counter_ns()
        values, _ = parse_artifact(payload)
        parse_ns += time.perf_counter_ns() - start
        if values.size != dim:
            raise ValueError("inconsistent artifact dimension")

        start = time.perf_counter_ns()
        np.add(accumulator, values, out=accumulator, casting="unsafe")
        aggregate_ns += time.perf_counter_ns() - start

    start = time.perf_counter_ns()
    expected_checkpoint = hashlib.sha256(
        b"ContestFL:canonical-aggregate"
        + clients.to_bytes(8, "big")
        + digest_chain.digest()
        + memoryview(accumulator).cast("B")
    ).digest()
    checkpoint_ms = (time.perf_counter_ns() - start) / 1e6

    claimed_checkpoint = (
        hashlib.sha256(b"ContestFL:injected-fault" + expected_checkpoint).digest()
        if claimed_fault
        else expected_checkpoint
    )
    start = time.perf_counter_ns()
    verdict = "REVISED" if claimed_checkpoint != expected_checkpoint else "UPHELD"
    detection_ms = (time.perf_counter_ns() - start) / 1e6

    challenge_ms = 0.0
    challenge_hash = ""
    if verdict == "REVISED":
        start = time.perf_counter_ns()
        challenge_payload = (
            b"ContestFL:aggregate-challenge-v1"
            + hashlib.sha256(manifest_bytes).digest()
            + claimed_checkpoint
            + expected_checkpoint
            + digest_chain.digest()
            + verdict.encode("ascii")
        )
        challenge_hash = hashlib.sha256(challenge_payload).hexdigest()
        challenge_ms = (time.perf_counter_ns() - start) / 1e6

    total_ns = time.perf_counter_ns() - total_start
    cpu_ns = time.process_time_ns() - cpu_start
    return {
        "clients": clients,
        "cache_mode": cache_mode,
        "update_body_bytes": update_body_bytes,
        "artifact_bytes": artifact_bytes,
        "manifest_ms": manifest_ms,
        "read_ms": read_ns / 1e6,
        "hash_ms": hash_ns / 1e6,
        "parse_ms": parse_ns / 1e6,
        "aggregate_ms": aggregate_ns / 1e6,
        "checkpoint_ms": checkpoint_ms,
        "detection_ms": detection_ms,
        "challenge_package_ms": challenge_ms,
        "verification_ms": (read_ns + hash_ns + parse_ns + aggregate_ns) / 1e6 + checkpoint_ms + manifest_ms + detection_ms,
        "total_ms": total_ns / 1e6,
        "cpu_ms": cpu_ns / 1e6,
        "local_throughput_mib_s": artifact_bytes / (1024 * 1024) / (total_ns / 1e9),
        "verdict": verdict,
        "challenge_hash": challenge_hash,
    }



def host_metadata() -> dict[str, object]:
    cpu_model = None
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    mem_total_kib = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                mem_total_kib = int(line.split()[1])
                break
    except (OSError, ValueError):
        pass
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "logicalCpuCount": os.cpu_count(),
        "cpuModel": cpu_model,
        "memoryTotalBytes": mem_total_kib * 1024 if mem_total_kib is not None else None,
    }

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", default="100")
    parser.add_argument("--update-bytes", default="262144,1048576,10485760")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--large-rounds", type=int, default=5)
    parser.add_argument("--huge-rounds", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--large-threshold-bytes", type=int, default=1_048_576)
    parser.add_argument("--huge-threshold-bytes", type=int, default=10_485_760)
    parser.add_argument("--bandwidth-mbps", default="100,1000,10000", help="Transfer projections only, in nominal decimal Mbit/s")
    parser.add_argument("--bandwidth-mib-s", default="", help=argparse.SUPPRESS)
    parser.add_argument("--cache-modes", default="warm,fadvise", help="warm and/or fadvise; fadvise is an eviction advisory, not guaranteed cold storage")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--dataset-dir", default="")
    parser.add_argument("--seed", type=int, default=20260806)
    parser.add_argument("--retain-datasets", action="store_true")
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--bootstrap-confidence", type=float, default=0.95)
    args = parser.parse_args()

    if args.bootstrap_samples < 0:
        raise SystemExit("--bootstrap-samples must be non-negative")
    if not 0.0 < args.bootstrap_confidence < 1.0:
        raise SystemExit("--bootstrap-confidence must be in (0, 1)")

    run_dir = ROOT / args.run_dir
    dataset_dir = Path(args.dataset_dir) if args.dataset_dir else run_dir / "watcher_datasets"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    clients_values = parse_ints(args.clients)
    update_sizes = parse_ints(args.update_bytes)
    if args.bandwidth_mib_s:
        # Backward-compatible conversion for older launchers. One MiB/s is
        # 8.388608 decimal Mbit/s.
        bandwidths = [value * 8.388608 for value in parse_floats(args.bandwidth_mib_s)]
    else:
        bandwidths = parse_floats(args.bandwidth_mbps)
    cache_modes = [item.strip() for item in args.cache_modes.split(",") if item.strip()]
    unknown_modes = sorted(set(cache_modes) - {"warm", "fadvise"})
    if unknown_modes:
        raise SystemExit(f"unknown cache modes: {unknown_modes}")

    raw: list[dict] = []
    for clients in clients_values:
        for update_bytes in update_sizes:
            manifest = prepare_dataset(dataset_dir, clients, update_bytes, args.seed)
            repetitions = args.huge_rounds if update_bytes >= args.huge_threshold_bytes else (
                args.large_rounds if update_bytes >= args.large_threshold_bytes else args.rounds
            )
            for cache_mode in cache_modes:
                for repetition in range(-args.warmup, repetitions):
                    # Alternate clean and faulty claims. Monitoring work is identical;
                    # challenge-package construction is timed only on faulty claims.
                    row = verify_once(manifest, claimed_fault=(repetition % 2 == 1), cache_mode=cache_mode)
                    if repetition >= 0:
                        row["repetition"] = repetition
                        raw.append(row)
    write_csv(run_dir / "watcher_pipeline_raw.csv", raw)

    summary: list[dict] = []
    keys = sorted({(int(r["clients"]), str(r["cache_mode"]), int(r["update_body_bytes"])) for r in raw})
    metrics = [
        "manifest_ms", "read_ms", "hash_ms", "parse_ms", "aggregate_ms",
        "checkpoint_ms", "detection_ms", "challenge_package_ms", "verification_ms", "total_ms",
        "cpu_ms", "local_throughput_mib_s",
    ]
    for clients, cache_mode, update_bytes in keys:
        group = [r for r in raw if int(r["clients"]) == clients and str(r["cache_mode"]) == cache_mode and int(r["update_body_bytes"]) == update_bytes]
        record: dict[str, float | int | str] = {
            "clients": clients,
            "cache_mode": cache_mode,
            "update_body_bytes": update_bytes,
            "artifact_bytes": int(group[0]["artifact_bytes"]),
            "runs": len(group),
        }
        for metric in metrics:
            metric_group = group
            if metric == "challenge_package_ms":
                metric_group = [r for r in group if r["verdict"] == "REVISED"]
                if not metric_group:
                    raise RuntimeError("challenge-package timing requires at least one faulty retained run")
            values = [float(r[metric]) for r in metric_group]
            record[f"{metric}_median"] = statistics.median(values)
            record[f"{metric}_p95"] = percentile(values, 0.95)
            if metric in {"verification_ms", "total_ms"}:
                lo, hi = bootstrap_median_ci(
                    values,
                    samples=args.bootstrap_samples,
                    confidence=args.bootstrap_confidence,
                    seed=args.seed + clients * 10_000_019 + update_bytes + sum(cache_mode.encode()) + len(metric),
                )
                record[f"{metric}_median_ci_lo"] = lo
                record[f"{metric}_median_ci_hi"] = hi
        summary.append(record)
    write_csv(run_dir / "watcher_pipeline_summary.csv", summary)

    projections: list[dict] = []
    dispute_rates = [0.0, 0.01, 0.05, 0.1]
    watcher_counts = [1, 2, 3]
    for row in summary:
        verify_ms = float(row["verification_ms_median"])
        package_ms = float(row["challenge_package_ms_median"])
        artifact_mib = int(row["artifact_bytes"]) / (1024 * 1024)
        for bandwidth in bandwidths:
            transfer_ms = projected_transfer_ms(int(row["artifact_bytes"]), bandwidth)
            for watchers in watcher_counts:
                for q in dispute_rates:
                    projections.append(
                        {
                            "clients": row["clients"],
                            "cache_mode": row["cache_mode"],
                            "update_body_bytes": row["update_body_bytes"],
                            "artifact_bytes": row["artifact_bytes"],
                            "watchers": watchers,
                            "dispute_rate": q,
                            "bandwidth_mbps": bandwidth,
                            "projected_transfer_ms_per_watcher": transfer_ms,
                            "measured_local_verification_ms_per_watcher": verify_ms,
                            "challenge_package_ms_per_fault": package_ms,
                            "system_watcher_work_ms_per_round": watchers * (transfer_ms + verify_ms) + q * package_ms,
                        }
                    )
    write_csv(run_dir / "watcher_cost_projection.csv", projections)

    host = host_metadata()
    metadata = {
        "platform": host["platform"],
        "python": host["python"],
        "logicalCpuCount": host["logicalCpuCount"],
        "cpuModel": host["cpuModel"],
        "memoryTotalBytes": host["memoryTotalBytes"],
        "numpy": np.__version__,
        "filesystem": os.statvfs(dataset_dir).f_fsid if hasattr(os.statvfs(dataset_dir), "f_fsid") else None,
        "clients": clients_values,
        "updateBodyBytes": update_sizes,
        "bandwidthMbpsForProjection": bandwidths,
        "cacheModes": cache_modes,
        "retainedRepetitions": {
            "default": args.rounds,
            "atOrAboveLargeThreshold": args.large_rounds,
            "atOrAboveHugeThreshold": args.huge_rounds,
            "largeThresholdBytes": args.large_threshold_bytes,
            "hugeThresholdBytes": args.huge_threshold_bytes,
        },
        "scope": (
            "Measured: local manifest lookup, file read, SHA-256 commitment check, canonical parsing/deserialization, "
            "int64 replay, checkpoint comparison, and challenge-package construction on detected faults. Projected only: ideal line-rate network transfer."
        ),
        "cacheCaveat": "warm is page-cache eligible. fadvise requests POSIX_FADV_DONTNEED before and after each file read, but remains an advisory local-store measurement and must not be described as guaranteed device-cold I/O.",
        "coverageInterpretation": (
            "A deterministic C1 watcher pays the full verification pipeline every round. The dispute rate q multiplies only "
            "challenge submission and any duplicated resolver work, not the observation needed to detect faults."
        ),
        "bootstrap": {
            "samples": args.bootstrap_samples,
            "confidence": args.bootstrap_confidence,
            "scope": "Percentile-bootstrap confidence interval for the sample median of verification_ms and total_ms; deterministic seed derived from the benchmark seed and configuration.",
        },
    }
    (run_dir / "watcher_pipeline_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Watcher pipeline report",
        "",
        "This experiment measures the full local verification pipeline used to satisfy challenge coverage. It does not treat `q * replay` as the watcher cost: an always-on watcher inspects every round, while `q` applies only to dispute handling after detection.",
        "",
        "| Clients | Cache mode | Update body/client | Total artifacts | Local verification median | Bootstrap CI | p95 | Local throughput |",
        "|---:|:---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            f"| {int(row['clients'])} | {row['cache_mode']} | {int(row['update_body_bytes']) / 1024:.0f} KiB | "
            f"{int(row['artifact_bytes']) / (1024*1024):.1f} MiB | {float(row['verification_ms_median']):.2f} ms | "
            f"[{float(row['verification_ms_median_ci_lo']):.2f}, {float(row['verification_ms_median_ci_hi']):.2f}] ms | "
            f"{float(row['verification_ms_p95']):.2f} ms | {float(row['local_throughput_mib_s_median']):.1f} MiB/s |"
        )
    lines += [
        "",
        "## Median phase decomposition",
        "",
        "| Artifacts | Cache | Read | SHA-256 binding | Parse | Accumulate | Checkpoint | Challenge package | CPU / wall |",
        "|---:|:---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        wall = float(row["total_ms_median"])
        cpu_ratio = float(row["cpu_ms_median"]) / wall if wall > 0 else float("nan")
        lines.append(
            f"| {int(row['artifact_bytes']) / (1024*1024):.1f} MiB | {row['cache_mode']} | "
            f"{float(row['read_ms_median']):.2f} ms | {float(row['hash_ms_median']):.2f} ms | "
            f"{float(row['parse_ms_median']):.2f} ms | {float(row['aggregate_ms_median']):.2f} ms | "
            f"{float(row['checkpoint_ms_median']):.2f} ms | {float(row['challenge_package_ms_median']):.3f} ms | "
            f"{cpu_ratio:.2f} |"
        )
    lines += [
        "",
        "Interpretation boundary: wide-area/object-store transfer is not measured. `watcher_cost_projection.csv` adds ideal line-rate projections in nominal decimal Mbit/s; it must not be described as a measured network result.",
    ]
    (run_dir / "WATCHER_PIPELINE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not args.retain_datasets:
        shutil.rmtree(dataset_dir, ignore_errors=True)
    print(json.dumps({"rawRows": len(raw), "summaryRows": len(summary), "runDir": str(run_dir)}, indent=2))


if __name__ == "__main__":
    main()
