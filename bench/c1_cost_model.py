#!/usr/bin/env python3
"""Combine measured watcher/replay costs with transparent C1 projections.

The script deliberately separates:
  * measured local monitoring work, paid on every covered round;
  * ideal artifact serialization, deployment-specific and not measured here;
  * challenge-package construction, paid only on detected faults;
  * optional independent resolver replay, also paid only on faults.

Acquisition and local verification can overlap when the watcher streams an
artifact.  Consequently, adding transfer and local time is not a universal
lower bound.  We report two implementation-grounded projections instead:

  overlap projection = max(ideal transfer, measured local monitoring)
  serial projection  = ideal transfer + measured local monitoring

They bracket ideal full overlap and no overlap for the retained implementation.
Neither includes publication delay, object-store latency, queueing, challenge
transaction propagation/inclusion, or an operational safety margin.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Iterable


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict]) -> None:
    records = list(rows)
    if not records:
        raise ValueError(f"no rows for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def parse_floats(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def parse_ints(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def find_replay_ms(replay_rows: list[dict[str, str]], clients: int, update_bytes: int) -> float:
    matches = [
        row for row in replay_rows
        if int(float(row["clients"])) == clients and int(float(row["update_bytes"])) == update_bytes
    ]
    if not matches:
        return math.nan
    return float(matches[0]["verification_ms_median"])


def transfer_ms(artifact_bytes: int, bandwidth_mbps: float) -> float:
    """Ideal serialization time at a nominal decimal Mbit/s line rate."""
    if bandwidth_mbps <= 0:
        raise ValueError("bandwidth must be positive")
    return artifact_bytes * 8.0 / (bandwidth_mbps * 1_000_000.0) * 1000.0


def projected_detection_ms(transfer: float, local: float) -> tuple[float, float]:
    """Return ideal full-overlap and serial projections for fixed work."""
    if transfer < 0 or local < 0:
        raise ValueError("times must be non-negative")
    return max(transfer, local), transfer + local


def minimum_blocks(duration_ms: float, block_period_ms: float) -> int:
    if block_period_ms <= 0:
        raise ValueError("block period must be positive")
    return max(1, math.ceil(duration_ms / block_period_ms))


def artifact_label(artifact_bytes: int) -> str:
    mib = artifact_bytes / (1024 * 1024)
    if mib >= 999.5:
        return r"1{,}000~MiB"
    return f"{mib:.0f}~MiB"


def latex_table(rows: list[dict], cache_mode: str) -> str:
    selected = [r for r in rows if r["cache_mode"] == cache_mode and r["watchers"] == 1 and r["dispute_rate"] == 0.0]
    by_size: dict[int, dict[float, dict]] = {}
    for row in selected:
        by_size.setdefault(int(row["artifact_bytes"]), {})[float(row["bandwidth_mbps"])] = row
    lines = [
        r"\begin{tabular}{@{}rrrrr@{}}",
        r"\toprule",
        r"Artifacts & Local monitor & \multicolumn{2}{c}{Overlap--serial projection} & Window blocks \\",
        r"\cmidrule(lr){3-4}\cmidrule(l){5-5}",
        r" & (ms) & 1~Gb/s & 10~Gb/s & 1 / 10~Gb/s \\",
        r"\midrule",
    ]
    for artifact_bytes, bandwidth_rows in sorted(by_size.items()):
        if 1000.0 not in bandwidth_rows or 10000.0 not in bandwidth_rows:
            continue
        one = bandwidth_rows[1000.0]
        ten = bandwidth_rows[10000.0]
        local = float(one["local_monitor_ms"])
        one_overlap = float(one["overlap_projection_ms"])
        one_serial = float(one["serial_projection_ms"])
        ten_overlap = float(ten["overlap_projection_ms"])
        ten_serial = float(ten["serial_projection_ms"])
        one_blocks = f"{int(one['overlap_window_blocks'])}--{int(one['serial_window_blocks'])}"
        ten_blocks = f"{int(ten['overlap_window_blocks'])}--{int(ten['serial_window_blocks'])}"
        lines.append(
            f"{artifact_label(artifact_bytes)} & {local:.0f} & "
            f"{one_overlap/1000:.2f}--{one_serial/1000:.2f}~s & "
            f"{ten_overlap/1000:.2f}--{ten_serial/1000:.2f}~s & "
            f"{one_blocks} / {ten_blocks} \\\\" 
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watcher-summary", type=Path, required=True)
    parser.add_argument("--replay-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-mode", default="fadvise")
    parser.add_argument("--bandwidth-mbps", default="100,1000,10000")
    parser.add_argument("--watchers", default="1,2,3")
    parser.add_argument("--dispute-rates", default="0,0.01,0.05,0.1")
    parser.add_argument("--block-period-ms", type=float, default=1000.0)
    args = parser.parse_args()

    if args.block_period_ms <= 0:
        raise SystemExit("--block-period-ms must be positive")
    watcher_rows = read_csv(args.watcher_summary)
    replay_rows = read_csv(args.replay_summary)
    bandwidths = parse_floats(args.bandwidth_mbps)
    watcher_counts = parse_ints(args.watchers)
    dispute_rates = parse_floats(args.dispute_rates)

    selected = [row for row in watcher_rows if row["cache_mode"] == args.cache_mode]
    if not selected:
        raise SystemExit(f"cache mode {args.cache_mode!r} absent from watcher summary")

    rows: list[dict] = []
    for source in sorted(selected, key=lambda r: (int(r["clients"]), int(r["update_body_bytes"]))):
        clients = int(source["clients"])
        update_bytes = int(source["update_body_bytes"])
        artifact_bytes = int(source["artifact_bytes"])
        local_ms = float(source["verification_ms_median"])
        local_p95_ms = float(source["verification_ms_p95"])
        package_ms = float(source["challenge_package_ms_median"])
        resolver_ms = find_replay_ms(replay_rows, clients, update_bytes)
        resolver_component = 0.0 if math.isnan(resolver_ms) else resolver_ms
        for bandwidth in bandwidths:
            wire_ms = transfer_ms(artifact_bytes, bandwidth)
            overlap_ms, serial_ms = projected_detection_ms(wire_ms, local_ms)
            overlap_p95_ms, serial_p95_ms = projected_detection_ms(wire_ms, local_p95_ms)
            for watchers in watcher_counts:
                for q in dispute_rates:
                    rows.append({
                        "clients": clients,
                        "cache_mode": args.cache_mode,
                        "update_body_bytes": update_bytes,
                        "artifact_bytes": artifact_bytes,
                        "artifact_mib": artifact_bytes / (1024 * 1024),
                        "bandwidth_mbps": bandwidth,
                        "watchers": watchers,
                        "dispute_rate": q,
                        "local_monitor_ms": local_ms,
                        "local_monitor_p95_ms": local_p95_ms,
                        "projected_transfer_ms": wire_ms,
                        "overlap_projection_ms": overlap_ms,
                        "serial_projection_ms": serial_ms,
                        "overlap_p95_projection_ms": overlap_p95_ms,
                        "serial_p95_projection_ms": serial_p95_ms,
                        "overlap_window_blocks": minimum_blocks(overlap_ms, args.block_period_ms),
                        "serial_window_blocks": minimum_blocks(serial_ms, args.block_period_ms),
                        "overlap_p95_window_blocks": minimum_blocks(overlap_p95_ms, args.block_period_ms),
                        "serial_p95_window_blocks": minimum_blocks(serial_p95_ms, args.block_period_ms),
                        "challenge_package_ms_per_fault": package_ms,
                        "independent_resolver_replay_ms_per_fault": resolver_ms,
                        "one_watcher_expected_work_ms_per_round": local_ms + q * package_ms,
                        "resolver_expected_work_ms_per_round": q * resolver_component,
                        "federation_expected_local_work_ms_per_round": watchers * local_ms + q * (package_ms + resolver_component),
                        "federation_serial_acquisition_plus_local_ms_per_round": watchers * serial_ms + q * (package_ms + resolver_component),
                    })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "c1_cost_projection.csv", rows)
    (args.output_dir / "c1_deadline_table.tex").write_text(
        latex_table(rows, args.cache_mode), encoding="utf-8"
    )

    compact = [row for row in rows if row["watchers"] == 1 and row["dispute_rate"] == 0.0]
    report = [
        "# C1 monitoring cost and challenge-window projections",
        "",
        "Measured local monitoring is combined with ideal line-rate serialization. Because streaming can overlap acquisition and verification, transfer plus local time is not a universal lower bound. The overlap projection is `max(transfer, local)` and the serial projection is `transfer + local`; they bracket ideal full overlap and no overlap for the retained implementation. Both exclude artifact publication delay, storage/object-store latency, queueing, challenge-transaction propagation/inclusion, and an engineering safety margin.",
        "",
        "| Artifacts | Bandwidth | Local monitor | Transfer | Overlap projection | Serial projection | Blocks (overlap--serial) | p95 blocks |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in compact:
        report.append(
            f"| {row['artifact_mib']:.1f} MiB | {row['bandwidth_mbps']:.0f} Mb/s | "
            f"{row['local_monitor_ms']:.1f} ms | {row['projected_transfer_ms']:.1f} ms | "
            f"{row['overlap_projection_ms']:.1f} ms | {row['serial_projection_ms']:.1f} ms | "
            f"{row['overlap_window_blocks']}--{row['serial_window_blocks']} | "
            f"{row['overlap_p95_window_blocks']}--{row['serial_p95_window_blocks']} |"
        )
    report += [
        "",
        "## Cost interpretation",
        "",
        "For deterministic challenge coverage, every full watcher pays the local monitoring term on every round. The fault rate multiplies only challenge-package construction and, when a separate resolver independently repeats the replay, that resolver term. The projection assumes duplicate challenges are merged so one package and one resolver invocation are charged per disputed round. Multiple watchers multiply monitoring and acquisition work unless they share infrastructure.",
        "",
        "The one-block challenge windows used by the protocol microbenchmarks are therefore not deployment recommendations. At 1 Gb/s, the measured 100 MiB configuration projects to 1--2 one-second blocks and the 1,000 MiB configuration to 9--10 blocks before queueing or transaction inclusion. At 10 Gb/s, the 1,000 MiB configuration still projects to 2--3 blocks (3--4 using the retained p95 local time).",
    ]
    (args.output_dir / "C1_COST_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    metadata = {
        "cacheMode": args.cache_mode,
        "blockPeriodMs": args.block_period_ms,
        "bandwidthMbps": bandwidths,
        "watcherCounts": watcher_counts,
        "disputeRates": dispute_rates,
        "projectionScope": "Ideal serialization combined with the retained local implementation under full-overlap and serial assumptions; excludes publication, store latency, queueing, transaction inclusion, and safety margin.",
        "resolverScope": "Independent resolver term uses the isolated deterministic replay-kernel median; it is not a complete resolver service measurement.",
        "deduplicationScope": "Expected federation work assumes duplicate challenge packages and resolver jobs are merged per disputed round.",
    }
    (args.output_dir / "c1_cost_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "outputDir": str(args.output_dir)}, indent=2))


if __name__ == "__main__":
    main()
