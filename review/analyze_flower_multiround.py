#!/usr/bin/env python3
"""Trajectory-level paired throughput analysis; failed runs remain visible."""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def summarize(root: Path) -> dict:
    paths = sorted((root / "trajectories").glob("*/SUMMARY.json"))
    if not paths:
        raise ValueError("no trajectories")
    by_key = {}
    round_data = {}
    for p in paths:
        s = json.loads(p.read_text())
        key = (int(s["seed"]), s["policy"])
        if key in by_key:
            raise ValueError("duplicate trajectory")
        rows = read_csv(p.parent / "rounds.csv")
        if len(rows) != int(s["completed_rounds"]):
            raise ValueError(f"round count mismatch in {p.parent}")
        if any(row["correct_checkpoint_finalized"] != "True" or row["error"] for row in rows):
            if s["successful"]:
                raise ValueError(f"incorrect successful marker in {p.parent}")
        by_key[key] = s
        round_data[key] = rows
    seeds = sorted({seed for seed, _ in by_key})
    paired = []
    for seed in seeds:
        a = by_key.get((seed, "contestfl"))
        b = by_key.get((seed, "eager_full"))
        if a is None or b is None:
            raise ValueError(f"missing policy for seed {seed}")
        if a["target_rounds"] != b["target_rounds"]:
            raise ValueError("round target mismatch")
        # Successful paired trajectories must converge on exactly the same
        # model and EVM checkpoint at each round. Mismatched training cannot
        # be attributed to the settlement policy alone.
        if a["successful"] and b["successful"]:
            ra, rb = round_data[(seed, "contestfl")], round_data[(seed, "eager_full")]
            if len(ra) != len(rb):
                raise ValueError(f"round count differs for seed {seed}")
            for x, y in zip(ra, rb):
                for field in ("round", "round_seed", "workload", "input_model_digest",
                              "next_model_digest", "finalized_checkpoint"):
                    if x[field] != y[field]:
                        raise ValueError(f"non-paired Flower checkpoint: seed {seed}, round {x['round']}, field {field}")
        # Report all trajectories; a pair is eligible for time/gas difference
        # only if both reached the predefined horizon correctly.
        paired.append({"seed": seed,
            "contestfl_success": a["successful"], "eager_success": b["successful"],
            "contestfl_completed": a["completed_rounds"], "eager_completed": b["completed_rounds"],
            "contestfl_rounds_per_hour": a["completed_rounds_per_hour"],
            "eager_rounds_per_hour": b["completed_rounds_per_hour"],
            "delta_rounds_per_hour": (
                a["completed_rounds_per_hour"] - b["completed_rounds_per_hour"])
                if a["successful"] and b["successful"] else None,
            "contestfl_elapsed_ms": a["elapsed_ms"], "eager_elapsed_ms": b["elapsed_ms"],
        })
    valid = [p["delta_rounds_per_hour"] for p in paired if p["delta_rounds_per_hour"] is not None]
    summary = {"seed_count": len(seeds), "complete_pairs": len(valid),
               "failed_pairs": len(seeds) - len(valid),
               "paired_mean_delta_rounds_per_hour": statistics.mean(valid) if valid else None,
               "paired_sd": statistics.stdev(valid) if len(valid) > 1 else None,
               "all_complete": len(valid) == len(seeds),
               "warning": "Paired across independent trajectories, not across the 20 rounds of a single seed; no pipelined FL throughput claim."}
    return {"summary": summary, "paired": paired}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.run_dir)
    (args.run_dir / "MULTIROUND_ANALYSIS.json").write_text(json.dumps(result, indent=2) + "\n")
    with (args.run_dir / "MULTIROUND_PAIRED.csv").open("w", newline="") as f:
        keys = list(result["paired"][0])
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader();writer.writerows(result["paired"])
    print(json.dumps(result["summary"], indent=2))
    if not result["summary"]["all_complete"]:
        raise SystemExit("One or more trajectories failed: raw outputs retained")

if __name__ == "__main__":
    main()
