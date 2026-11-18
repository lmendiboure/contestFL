#!/usr/bin/env python3
"""Combine real extended-v4 observations into compact manuscript replacement tables.

Never substitute reference data for a failed/missing experiment. Keep each
scaling configuration independent to avoid mixing artifact sizes and client
counts; count invalid runs before success-conditioned medians.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

from review.analyze_causal_chain import bootstrap_median_ci, read_rows, summarize


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fmt(x, d=2):
    try:
        f = float(x)
        return f"{f:.{d}f}" if math.isfinite(f) else "--"
    except (TypeError, ValueError):
        return "--"


def summarize_scale(out: Path):
    all_groups, all_pairs = [], []
    for datafile in sorted((out / "scale").glob("*/causal_chain_raw.csv")):
        cfg = datafile.parent.name
        rows = read_rows(datafile)
        groups, pairs = summarize(rows)
        for group in groups:
            group["configuration"] = cfg
            all_groups.append(group)
        for pair in pairs:
            pair["configuration"] = cfg
            all_pairs.append(pair)
    if not all_groups:
        raise RuntimeError("no measured causal-chain scaling output")
    return all_groups, all_pairs


def summarize_flower(out: Path):
    files = sorted((out / "flower").glob("seed_*/paired_flower_policies.csv"))
    if not files:
        return [], []
    lines, pairs = [], []
    for f in files:
        data = read_csv(f)
        for row in data:
            success = row["correct_checkpoint_finalized"].strip().lower() == "true" and not row["error"].strip()
            lines.append({"seed": row["seed"], "policy": row["design"], "workload": row["workload"],
                          "success": success, "end_to_end_sequential_ms": float(row["end_to_end_sequential_ms"]),
                          "gas_total": float(row["gas_total"]), "artifact_bytes": int(row["artifact_bytes_measured"])})
    groups = defaultdict(list)
    for row in lines:
        groups[(row["workload"], row["policy"])].append(row)
    summary = []
    for (workload, policy), group in sorted(groups.items()):
        valid = [r for r in group if r["success"]]
        summary.append({"workload": workload, "policy": policy, "runs": len(group),
                        "correct": len(valid),
                        "median_sequential_e2e_ms_success_only": st.median(r["end_to_end_sequential_ms"] for r in valid) if valid else math.nan,
                        "median_completed_rounds_per_hour_proxy_success_only": st.median(3600000 / r["end_to_end_sequential_ms"] for r in valid) if valid else math.nan,
                        "median_gas_success_only": st.median(r["gas_total"] for r in valid) if valid else math.nan,
                        "artifact_bytes": group[0]["artifact_bytes"]})
    for workload in sorted({r["workload"] for r in lines}):
        left = {r["seed"]: r for r in lines if r["workload"] == workload and r["policy"] == "contestfl"}
        right = {r["seed"]: r for r in lines if r["workload"] == workload and r["policy"] == "eager_full"}
        common = sorted(set(left) & set(right))
        good = [k for k in common if left[k]["success"] and right[k]["success"]]
        deltas = [right[k]["end_to_end_sequential_ms"] - left[k]["end_to_end_sequential_ms"] for k in good]
        lo, hi = bootstrap_median_ci(deltas, seed=20261111, draws=3000)
        pairs.append({"workload": workload, "paired_attempts": len(common), "both_correct": len(good),
                      "eager_minus_contestfl_e2e_delta_median_ms": st.median(deltas) if deltas else math.nan,
                      "paired_ci95_low_ms": lo, "paired_ci95_high_ms": hi})
    return summary, pairs


def summarize_timeouts(out: Path):
    path = out / "timeouts" / "late_challenge_raw.csv"
    if not path.exists():
        return []
    rows = read_csv(path)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["flood_count"], row["quota_per_identity"])].append(row)
    summary = []
    for (flood, quota), subset in sorted(groups.items(), key=lambda x: (int(x[0][0]),int(x[0][1]))):
        success = sum(r["honest_success"].strip().lower() == "true" for r in subset)
        timeout = sum(r["resolver_timeout_abort"].strip().lower() == "true" for r in subset)
        missed = sum(r["terminal_outcome"] == "coverage_miss_C1" for r in subset)
        errors = sum(bool(r["error"].strip()) for r in subset)
        observed = [float(r["max_observed_block_gas_utilization"]) for r in subset if r.get("measured_blocks") and int(r["measured_blocks"]) > 0]
        summary.append({"flood_count": int(flood), "quota": int(quota), "attempts": len(subset),
                        "honest_included_timely": success, "C1_coverage_misses": missed,
                        "injected_unresolved_resolver_aborts_onchain": timeout,
                        "errors": errors, "max_gas_utilization_observed": max(observed, default=math.nan)})
    return summary


def write_csv(path: Path, rows: list[dict]):
    if not rows: return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def latex_escape(s):
    return str(s).replace("_", "\\_").replace("%", "\\%")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", required=True, type=Path)
    args = p.parse_args()
    out = args.run_dir
    groups, pairs = summarize_scale(out)
    flower, flower_pairs = summarize_flower(out)
    timeouts = summarize_timeouts(out)
    a = out / "analysis"; a.mkdir(parents=True, exist_ok=True)
    for name, records in [("extended_causal_groups.csv", groups),("extended_causal_paired.csv", pairs),
                          ("extended_flower_groups.csv", flower),("extended_flower_paired.csv", flower_pairs),
                          ("extended_timeout_outcomes.csv", timeouts)]:
        write_csv(a / name, records)
    lines = ["# ContestFL v4 extended — measured results", "",
             "Only explicitly executed experiments are included; no figures are added.",
             "## Causal-chain scaling", "",
             "| Configuration | Policy | Correct/attempts | Latency median (s) | Gas median (M) |",
             "|---|---|---:|---:|---:|"]
    latex = [r"% Extended-v4 measured causal scaling; conditional medians only.",
             r"\begin{tabular}{llrrr}",r"\toprule",
             r"Configuration & Policy & Success & Time (s) & Gas (M) \\",r"\midrule"]
    for x in groups:
        s=f"{x['successes']}/{x['attempts']}"
        t=fmt(x["wall_ms_median_success_only"]/1000)
        g=fmt(x["gas_total_median_success_only"]/1e6,3)
        lines.append(f"| {x['configuration']} | {x['policy']} | {s} | {t} | {g} |")
        latex.append(f"{latex_escape(x['configuration'])} & {latex_escape(x['policy'])} & {s} & {t} & {g} " + r"\\")
    latex += [r"\bottomrule",r"\end{tabular}"]
    lines += ["", "## Measured one-round Flower replay, shared training", "",
              "The exact same measured Flower round/artifacts are reused between policies. The resulting throughput is a sequential **one-round equivalent**, not a directly observed steady-state multi-round throughput."]
    if flower:
        lines += ["", "| Fault | Policy | Correct/attempts | Sequential E2E median (s) | Equivalent rounds/hour |",
                  "|---|---|---:|---:|---:|"]
        for x in flower:
            lines.append(f"| {x['workload']} | {x['policy']} | {x['correct']}/{x['runs']} | "
                         f"{fmt(x['median_sequential_e2e_ms_success_only']/1000)} | "
                         f"{fmt(x['median_completed_rounds_per_hour_proxy_success_only'])} |")
    else:
        lines.append("Flower experiment was not run; no Flower throughput claims are supported by this package.")
    lines += ["", "## Sustained-load coverage and forced responder-outage outcome", ""]
    if timeouts:
        lines += ["| Flood | Identity quota | Timely honest / trials | Coverage misses | Actual expireChallenge aborts (resolver outage injected) | RPC errors |",
                  "|---:|---:|---:|---:|---:|---:|"]
        for x in timeouts:
            lines.append(f"| {x['flood_count']} | {x['quota']} | {x['honest_included_timely']}/{x['attempts']} | "
                         f"{x['C1_coverage_misses']} | {x['injected_unresolved_resolver_aborts_onchain']} | {x['errors']} |")
    else:
        lines.append("Timeout outcome test not run.")
    root_depth = out / "root_depth" / "root_depth_sensitivity_summary.csv"
    if root_depth.exists():
        root_rows = read_csv(root_depth)
        lines += ["", "## Merkle depth sensitivity — isolated challenged path", "",
                  "| Depth | Correct/runs | Proof bytes median | Total gas median (M) |",
                  "|---:|---:|---:|---:|"]
        for r in root_rows:
            lines.append(f"| {r['smt_depth']} | {fmt(float(r['success_rate'])*float(r['runs']),0)}/{r['runs']} | "
                         f"{fmt(r['proof_bytes'],0)} | {fmt(float(r['total_gas'])/1e6,3)} |")
    netem = out / "netem" / "causal_chain" / "causal_chain_raw.csv"
    if netem.exists():
        net_rows = read_rows(netem)
        net_groups, _ = summarize(net_rows)
        lines += ["", "## Synthetic RTT sensitivity — single-host validators", "",
                  "| Policy | Correct/attempts | Finalization median (s) | Gas median (M) |",
                  "|---|---:|---:|---:|"]
        for r in net_groups:
            lines.append(f"| {r['policy']} | {r['successes']}/{r['attempts']} | "
                         f"{fmt(r['wall_ms_median_success_only']/1000)} | "
                         f"{fmt(r['gas_total_median_success_only']/1e6,3)} |")
    fault_mix = out / "fault_mix_derived" / "fault_rate_mixture_scope.json"
    if fault_mix.exists():
        mix = json.loads(fault_mix.read_text())
        lines += ["", "## Derived fault-frequency mixture from measured v3", "",
                  f"Source: `{mix['source']}`. This is a **weighted expectation**, not new on-chain observations.",
                  f"Eager minus ContestFL expected wall-time delta range on the tested fault grid (ms): "
                  f"{fmt(mix['eager_minus_contestfl_wall_delta_ms_min_max'][0])} .. "
                  f"{fmt(mix['eager_minus_contestfl_wall_delta_ms_min_max'][1])}."]
    lines += ["", "## Interpretation restrictions", "",
              "- Differences at different client counts isolate the client dimension **only** where update_dim and challenge_blocks match.",
              "- 500-client EVM/causal measurements do not establish 500-client Flower training throughput.",
              "- Identity quotas are address-bounded, not Sybil-proof.",
              "- Forced resolver absence is an injected fault; aborts after expireChallenge are not naturally observed outage probabilities.",
              "- Missed honest challenge inclusion is a C1 coverage failure, not an automatic timeout abort.",
              "- The root-only 256-depth Merkle measurement is an ablation, not complete recovery equivalence.",
              "- Eager verifies before optimistic finalization; differences require explicit assurance and computation scope.",
              "- Tests do not replace formal refinement proofs or validate arbitrary DAG structure or malicious-resolver semantics.", ""]
    (a / "EXTENDED_V4_RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    (a / "extended_table_replacement.tex").write_text("\n".join(latex)+"\n",encoding="utf-8")
    print(json.dumps({"causal_configurations": len({x['configuration'] for x in groups}),
                      "causal_measured_policy_groups": len(groups),
                      "flower_policy_groups":len(flower),"flood_groups":len(timeouts)},indent=2))

if __name__ == "__main__": main()
