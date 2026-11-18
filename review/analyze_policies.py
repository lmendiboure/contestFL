#!/usr/bin/env python3
"""Summarize matched protocol-policy observations without hiding failures.

Only exact seed+clients+repetition pairs contribute to paired differences.
CIs are percentile bootstrap intervals over physical repetitions (not txs).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

METRICS = ("wall_ms", "gas_total", "tx_count", "verification_cpu_ms")
BASE = "contestfl"


def quantile(values: list[float], q: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    i = int(position)
    if i == len(ordered) - 1:
        return ordered[i]
    return ordered[i] + (position - i) * (ordered[i + 1] - ordered[i])


def bootstrap_ci(diffs: list[float], seed: int = 20261106, samples: int = 4000) -> tuple[float, float]:
    if not diffs:
        return math.nan, math.nan
    rng = random.Random(seed)
    size = len(diffs)
    medians = [statistics.median(diffs[rng.randrange(size)] for _ in range(size))
               for _ in range(samples)]
    return quantile(medians, .025), quantile(medians, .975)


def read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        result: list[dict[str, Any]] = []
        for row in csv.DictReader(f):
            normalized: dict[str, Any] = dict(row)
            for key in METRICS:
                normalized[key] = float(row[key])
            normalized["client_count"] = int(row["client_count"])
            normalized["repetition"] = int(row["repetition"])
            normalized["seed"] = int(row["seed"])
            normalized["ok"] = row["correct_checkpoint_finalized"].lower() == "true" and not row["error"]
            result.append(normalized)
    if not result:
        raise ValueError("empty input")
    return result


def summarize(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_group: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_group[(r["workload"], r["client_count"], r["design"])].append(r)
    summary = []
    for (workload, n, design), group in sorted(by_group.items()):
        if len({(r["repetition"], r["seed"]) for r in group}) != len(group):
            raise ValueError(f"duplicate repetition/seed for {(workload, n, design)}")
        successful = [r for r in group if r["ok"]]
        row = {
            "workload": workload, "clients": n, "design": design, "attempts": len(group),
            "successes": len(successful), "success_rate": len(successful) / len(group),
        }
        for metric in METRICS:
            values = [r[metric] for r in successful]
            row[f"{metric}_median_successes_only"] = statistics.median(values) if values else math.nan
            row[f"{metric}_p95_successes_only"] = quantile(values, .95)
        summary.append(row)
    pair_rows = []
    groups_by_case: dict[tuple[str, int], dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    for (workload, n, design), group in by_group.items():
        groups_by_case[(workload, n)][design] = group
    for (workload, clients), designs in sorted(groups_by_case.items()):
        if BASE not in designs:
            continue
        baselines = {(r["repetition"], r["seed"]): r for r in designs[BASE]}
        for design, group in sorted(designs.items()):
            if design == BASE:
                continue
            test = {(r["repetition"], r["seed"]): r for r in group}
            keys = sorted(set(baselines) & set(test))
            valid_keys = [key for key in keys if baselines[key]["ok"] and test[key]["ok"]]
            line: dict[str, Any] = {
                "workload": workload, "clients": clients, "comparison": f"{design} - {BASE}",
                "matched_total": len(keys), "matched_successful": len(valid_keys),
                "missing_pair_count": len(set(baselines) ^ set(test)),
                "excluded_failure_pairs": len(keys) - len(valid_keys),
            }
            for metric in METRICS:
                deltas = [test[key][metric] - baselines[key][metric] for key in valid_keys]
                line[f"{metric}_paired_median_delta"] = statistics.median(deltas) if deltas else math.nan
                low, high = bootstrap_ci(deltas, seed=20261106 + clients + len(workload) + len(design) + len(metric))
                line[f"{metric}_paired_ci95_low"] = low
                line[f"{metric}_paired_ci95_high"] = high
            pair_rows.append(line)
    return summary, pair_rows


def output_table(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    rows = read_rows(args.input)
    summary, comparisons = summarize(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_table(args.output_dir / "paired_policies_summary.csv", summary)
    output_table(args.output_dir / "paired_policies_effects.csv", comparisons)
    lines = [
        "# ContestFL reviewer campaign — paired protocol policy comparison",
        "", "All rows are on-chain observations. **Only successful runs** contribute to",
        "latency/gas medians; failures remain in the success-rate denominator.",
        "Paired differences use identical input update arrays, workload, and seed per repetition.",
        "The 95% intervals are percentile bootstrap intervals for the paired median.",
        "Small samples cannot justify general performance conclusions.", "",
        "## Per-policy performance", "",
        "| Workload | Clients | Policy | Success | Wall median (ms) | Gas median | CPU verification median (ms) |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for r in summary:
        lines.append(f"| {r['workload']} | {r['clients']} | {r['design']} | {r['successes']}/{r['attempts']} | "
                     f"{r['wall_ms_median_successes_only']:.1f} | {r['gas_total_median_successes_only']:.0f} | "
                     f"{r['verification_cpu_ms_median_successes_only']:.2f} |")
    lines += ["", "## Paired effects relative to ContestFL", "",
              "Positive difference = alternative is more expensive/slower than ContestFL.", "",
              "| Workload | Clients | Alternative | Valid pairs | Wall Δ median [95% CI] (ms) | Gas Δ median [95% CI] |",
              "|---|---:|---|---:|---:|---:|",]
    for r in comparisons:
        lines.append(f"| {r['workload']} | {r['clients']} | {r['comparison']} | {r['matched_successful']}/{r['matched_total']} | "
                     f"{r['wall_ms_paired_median_delta']:.1f} [{r['wall_ms_paired_ci95_low']:.1f}, {r['wall_ms_paired_ci95_high']:.1f}] | "
                     f"{r['gas_total_paired_median_delta']:.0f} [{r['gas_total_paired_ci95_low']:.0f}, {r['gas_total_paired_ci95_high']:.0f}] |")
    lines += ["", "## Scope and caveats", "",
              "- ContestFL, abort/restart and level-cascade are **policy design points** on one shared ContestFL smart contract, not independent optimized implementations or reproductions of published work.",
              "- Level-cascade here means *a conservative post-correction downstream aggregate re-audit*; it does not represent arbitrary-level cascading invalidations.",
              "- Eager performs pre-finalization exhaustive admission/inclusion/aggregate checking, so it does not wait for an optimistic challenge window. This is a **difference in protocol** rather than an accidentally omitted delay.",
              "- Measured throughput is protocol completions/hour only. No training is executed in this microbenchmark; it is not full FL training throughput.",
              "- Clients' model updates are deterministic generated payloads. Real artifact transfer and remote storage must be measured separately.",
              "- If correctness is missing for any policy, its faster latency is not a valid performance gain.", ""]
    (args.output_dir / "PAIRED_POLICY_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"groups": len(summary), "comparisons": len(comparisons), "report": str(args.output_dir / "PAIRED_POLICY_REPORT.md")}))


if __name__ == "__main__":
    main()
