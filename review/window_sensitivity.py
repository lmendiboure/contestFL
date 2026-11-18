#!/usr/bin/env python3
"""Transparent C1 window-sizing sensitivity from watcher p95 + ideal link model.

This does not empirically measure WAN/object-store RTT. It exposes assumptions
explicitly: serialized bytes/bandwidth plus fixed object-lookup overhead, then
local measured watcher p95. Block conversion uses a configured block period.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def choose_rows(input_path: Path, clients: int, cache: str) -> list[dict]:
    with input_path.open(newline="", encoding="utf-8") as f:
        result = [row for row in csv.DictReader(f)
                  if int(row["clients"]) == clients and row["cache_mode"] == cache]
    if not result:
        raise ValueError(f"no watcher observations at clients={clients}, cache={cache} in {input_path}")
    return result


def compute_window(p95_local_ms: float, artifact_bytes: int, bandwidth_mbps: float,
                   rtt_ms: float, serial_requests: int, block_s: float,
                   reserve_blocks: int = 2) -> int:
    if min(p95_local_ms, artifact_bytes, rtt_ms, serial_requests, reserve_blocks) < 0:
        raise ValueError("negative inputs are invalid")
    if bandwidth_mbps <= 0 or block_s <= 0:
        raise ValueError("positive bandwidth and block period required")
    transfer_ms = artifact_bytes * 8 * 1000 / (bandwidth_mbps * 1e6)
    budget_ms = p95_local_ms + transfer_ms + serial_requests * rtt_ms
    return int(math.ceil(budget_ms / (block_s * 1000))) + reserve_blocks


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--watcher-summary", required=True, type=Path)
    p.add_argument("--clients", type=int, default=100)
    p.add_argument("--cache", default="fadvise")
    p.add_argument("--bandwidths-mbps", default="20,100,1000")
    p.add_argument("--object-rtts-ms", default="0,50,200")
    p.add_argument("--request-models", default="1,100")
    p.add_argument("--block-period-s", type=float, default=1)
    p.add_argument("--reserve-blocks", type=int, default=2)
    p.add_argument("--primary-update-bytes", type=int, default=1048576)
    p.add_argument("--primary-bandwidth-mbps", type=float, default=100)
    p.add_argument("--primary-rtt-ms", type=float, default=50)
    p.add_argument("--primary-requests", type=int, default=1)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    rows = choose_rows(args.watcher_summary, args.clients, args.cache)
    bands = [float(v) for v in args.bandwidths_mbps.split(",")]
    rtts = [float(v) for v in args.object_rtts_ms.split(",")]
    requests = [int(v) for v in args.request_models.split(",")]
    if args.primary_bandwidth_mbps not in bands or args.primary_rtt_ms not in rtts or args.primary_requests not in requests:
        p.error("primary assumptions must occur in the corresponding sensitivity grids")
    out = []
    for raw in rows:
        artifact_bytes = int(raw["artifact_bytes"])
        p95_local_ms = float(raw["total_ms_p95"])
        for bw in bands:
            for rtt in rtts:
                for req in requests:
                    out.append({
                        "clients": args.clients, "cache": args.cache,
                        "update_body_bytes": int(raw["update_body_bytes"]),
                        "artifact_bytes": artifact_bytes,
                        "local_watcher_p95_ms_measured": p95_local_ms,
                        "bandwidth_mbps_assumed": bw, "object_store_rtt_ms_assumed": rtt,
                        "serialized_object_requests_assumed": req,
                        "ideal_link_serialization_ms_derived": round(artifact_bytes * 8 * 1000 / (bw * 1e6), 3),
                        "lookup_latency_ms_derived": round(req * rtt, 3),
                        "minimum_window_blocks_model": compute_window(
                            p95_local_ms, artifact_bytes, bw, rtt, req,
                            args.block_period_s, args.reserve_blocks),
                    })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "window_sensitivity.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    candidate = [r for r in out if
                 r["update_body_bytes"] == args.primary_update_bytes and
                 r["bandwidth_mbps_assumed"] == args.primary_bandwidth_mbps and
                 r["object_store_rtt_ms_assumed"] == args.primary_rtt_ms and
                 r["serialized_object_requests_assumed"] == args.primary_requests]
    if len(candidate) != 1:
        raise ValueError(f"expected one primary scenario, got {len(candidate)}; choose a tested update size")
    selected = candidate[0]
    (args.output_dir / "recommended_window.json").write_text(json.dumps({
        "challenge_blocks": selected["minimum_window_blocks_model"],
        "selection": selected,
        "source": str(args.watcher_summary),
        "model": "measured local p95 + ideal link serialization + modeled object lookup RTT + fixed safety-block reserve",
        "cautions": [
            "This is a sensitivity projection, not WAN measurements nor a guaranteed C1 bound.",
            "No queueing, contention, straggler correlation, object-store jitter or malicious delays modeled.",
            "fadvise cache eviction is advisory; not a certified cold cache.",
            "Replay/verify may overlap with transfers; serial summation is intentionally conservative.",
            "A block deadline does not guarantee transaction inclusion under overload or censorship.",
        ],
    }, indent=2) + "\n")
    print(selected["minimum_window_blocks_model"])


if __name__ == "__main__":
    main()
