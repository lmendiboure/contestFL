#!/usr/bin/env python3
"""Failure-accounted, seeded-pair analysis of the targeted causal-chain campaign.

No figure is created: the resulting compact table is intended to REPLACE an
existing table/paragraph, not expand the paper. Failed cases remain in counts.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics as st
from collections import defaultdict
from pathlib import Path

BASE = "contestfl"
POLICIES = {BASE, "abort_restart", "aggregate_reaudit"}
METRICS = ("gas_total", "wall_ms", "verification_cpu_ms", "tx_count")


def read_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        rdr = csv.DictReader(handle)
        fields = {"design", "workload", "client_count", "repetition", "seed", "error",
                  "correct_checkpoint_finalized", *METRICS}
        missing = fields - set(rdr.fieldnames or ())
        if missing:
            raise ValueError(f"missing columns: {sorted(missing)}")
        rows = []
        for original in rdr:
            r = dict(original)
            r["client_count"] = int(r["client_count"])
            r["seed"] = int(r["seed"])
            r["repetition"] = int(r["repetition"])
            for measure in METRICS:
                r[measure] = float(r[measure])
            r["ok"] = r["correct_checkpoint_finalized"].lower() == "true" and not r["error"].strip()
            if r["design"] not in POLICIES or r["repetition"] < 0:
                raise ValueError("invalid design or warm-up leaked into measured dataset")
            rows.append(r)
    if not rows:
        raise ValueError("empty measured data")
    return rows


def bootstrap_median_ci(values: list[float], seed: int, draws: int = 3000):
    if not values:
        return math.nan, math.nan
    rng = random.Random(seed)
    n = len(values)
    out = sorted(st.median(values[rng.randrange(n)] for _ in range(n)) for _ in range(draws))
    return out[int(.025*(draws-1))], out[int(.975*(draws-1))]


def summarize(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    cases = defaultdict(dict)
    for row in rows:
        case = (row["workload"], row["client_count"])
        key = (row["seed"], row["repetition"])
        slots = cases[(case, row["design"])]
        if key in slots:
            raise ValueError(f"duplicate pair key: {case}, {row['design']}, {key}")
        slots[key] = row
    groups = []
    pairs = []
    for (case, policy), records in sorted(cases.items()):
        valid = [r for r in records.values() if r["ok"]]
        result = {"workload": case[0], "clients": case[1], "policy": policy,
                  "attempts": len(records), "successes": len(valid),
                  "failure_count": len(records) - len(valid)}
        for m in METRICS:
            result[m + "_median_success_only"] = st.median(r[m] for r in valid) if valid else math.nan
        groups.append(result)
    for (case, policy), challenger in sorted(cases.items()):
        if policy == BASE:
            continue
        reference = cases.get((case, BASE))
        if reference is None:
            raise ValueError("missing ContestFL baseline")
        shared = sorted(set(reference) & set(challenger))
        good = [k for k in shared if reference[k]["ok"] and challenger[k]["ok"]]
        result = {"workload": case[0], "clients": case[1],
                  "contrast": policy + " - " + BASE,
                  "pairs_total": len(shared), "pairs_both_successful": len(good),
                  "missing_pairs": len(set(reference) ^ set(challenger)),
                  "failed_pairs": len(shared) - len(good)}
        for m in METRICS:
            differences = [challenger[k][m] - reference[k][m] for k in good]
            result[m + "_paired_median_delta"] = st.median(differences) if differences else math.nan
            lo, hi = bootstrap_median_ci(differences, 20261111 + len(policy) * 37 + len(m))
            result[m + "_paired_ci95_low"] = lo
            result[m + "_paired_ci95_high"] = hi
        pairs.append(result)
    return groups, pairs


def write_csv(path: Path, data: list[dict]):
    with path.open("w", newline="", encoding="utf-8") as stream:
        if not data:
            raise ValueError("empty output")
        writer = csv.DictWriter(stream, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)


def fmt(x, scale=1, decimals=2):
    return f"{x / scale:.{decimals}f}" if math.isfinite(x) else "NA"


def report(groups: list[dict], pairs: list[dict]) -> str:
    lines = [
        "# ContestFL v4: causal-chain paired comparison", "",
        "**Scope:** Three intentionally staged faults, in order reject→admit/excluded",
        "(state 1→2), newly active INCLUDE 2→3, and a bad aggregate root.",
        "All policies use identical generated updates and seeded instances.",
        "Results are *not* a measurement of general random fault rates.", "",
        "## Protocol finalization and ledger cost", "",
        "| Policy | Correct / attempts | Median wall (s) | Median gas (M) | Median off-chain verify CPU (ms) |",
        "|---|---:|---:|---:|---:|",
    ]
    for g in groups:
        lines.append(f"| {g['policy']} | {g['successes']}/{g['attempts']} | "
                     f"{fmt(g['wall_ms_median_success_only'], 1000)} | "
                     f"{fmt(g['gas_total_median_success_only'], 1e6, 3)} | "
                     f"{fmt(g['verification_cpu_ms_median_success_only'])} |")
    lines += ["", "## Paired effects (positive = alternative more expensive/slower)", "",
              "Confidence intervals are descriptive 95% percentile bootstrap of per-seed",
              "paired *median differences*, conditional on both checkpoints being correct.",
              "Failures remain in the success denominator and are listed separately.", "",
              "| Comparison | Valid pairs | Wall Δ (s) [95% CI] | Gas Δ (M) [95% CI] |",
              "|---|---:|---:|---:|"]
    for r in pairs:
        lines.append(f"| {r['contrast']} | {r['pairs_both_successful']}/{r['pairs_total']} | "
                     f"{fmt(r['wall_ms_paired_median_delta'],1000)} "
                     f"[{fmt(r['wall_ms_paired_ci95_low'],1000)}, {fmt(r['wall_ms_paired_ci95_high'],1000)}] | "
                     f"{fmt(r['gas_total_paired_median_delta'],1e6,3)} "
                     f"[{fmt(r['gas_total_paired_ci95_low'],1e6,3)}, {fmt(r['gas_total_paired_ci95_high'],1e6,3)}] |")
    lines += ["", "## Scientific limitations", "",
              "- The Solidity prototype compresses ADMIT and INCLUDE into a per-client state;",
              "  this does **not** prove arbitrary DAG node activation on-chain.",
              "- `aggregate_reaudit` re-audits an aggregate dependency off-chain after each",
              "  *published* replacement, but shares ContestFL's on-chain transition path.",
              "  This ablation **cannot** establish strict superiority over a general level-cascade engine.",
              "- `abort_restart` resubmits client artifacts after every successive fault.",
              "  It measures repeated-error cost, not the distribution of faults in practice.",
              "- Eager's published v3 comparison remains separate because an early audit",
              "  changes which later faulty replacements would be exposed at all.",
              "- No Flower training throughput, geographic WAN, certificate validation,",
              "  complete Merkle recovery, or multi-key termination theorem is established.",
              "- Do not combine CPU verification time and gas into a common financial cost.", ""]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    groups, pairs = summarize(read_rows(args.input))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "causal_policy_summary.csv", groups)
    write_csv(args.output_dir / "causal_paired_effects.csv", pairs)
    (args.output_dir / "CAUSAL_CHAIN_REPORT.md").write_text(report(groups, pairs), encoding="utf-8")
    print(json.dumps({"groups": len(groups), "paired_contrasts": len(pairs),
                      "report": str(args.output_dir / 'CAUSAL_CHAIN_REPORT.md')}, indent=2))


if __name__ == "__main__":
    main()
