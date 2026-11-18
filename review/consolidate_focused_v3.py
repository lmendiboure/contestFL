#!/usr/bin/env python3
"""Create *replacement* tables/figures from measured ContestFL v3 CSVs.

No synthetic data, no historical CSV substitution. Missing, failed or unmatched
runs are counted explicitly. All numeric comparisons are paired by generated
round seed within a single configuration; they are not cross-host causal effects.
The upstream on-chain harness must run to produce the expected input CSVs.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics as stats
from collections import defaultdict
from pathlib import Path
from typing import Any

POLICIES = ("contestfl", "eager_full", "abort_restart", "level_cascade")
MEASURES = ("wall_ms", "gas_total", "verification_cpu_ms", "challenge_wait_wall_ms")


def median(xs):
    return stats.median(xs) if xs else math.nan


def percentile(xs, p):
    if not xs:
        return math.nan
    a = sorted(xs)
    x = (len(a) - 1) * p
    i = int(x)
    return a[i] if i == len(a) - 1 else a[i] + (x - i) * (a[i + 1] - a[i])


def boot_ci(deltas: list[float], seed: int = 31, draws: int = 4000):
    """Percentile bootstrap on *pairs*; report descriptive CI, not significance."""
    if not deltas:
        return math.nan, math.nan
    rng = random.Random(seed)
    n = len(deltas)
    vals = [stats.median(deltas[rng.randrange(n)] for _ in range(n)) for _ in range(draws)]
    return percentile(vals, .025), percentile(vals, .975)


def wilson(successes: int, total: int) -> tuple[float, float]:
    if not total:
        return math.nan, math.nan
    z = 1.959963984540054
    p = successes / total
    center = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return max(0.0, center - half), min(1.0, center + half)


def read_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open(encoding="utf-8", newline="") as fd:
            reader = csv.DictReader(fd)
            required = {"workload", "client_count", "repetition", "seed", "design",
                        "correct_checkpoint_finalized", "error", "wall_ms", "gas_total", "verification_cpu_ms"}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(f"input missing required columns {sorted(required - set(reader.fieldnames or []))}: {path}")
            for row in reader:
                r = dict(row)
                r["window_label"] = r.get("window_label") or path.parent.name
                r["client_count"] = int(r["client_count"])
                r["repetition"] = int(r["repetition"])
                r["seed"] = int(r["seed"])
                r["ok"] = r["correct_checkpoint_finalized"].strip().lower() == "true" and not r["error"].strip()
                for measure in MEASURES:
                    r[measure] = float(r.get(measure, "0") or 0)
                if r["repetition"] < 0:
                    raise ValueError("warm-up rows must never appear in measured files")
                if r["design"] not in POLICIES:
                    raise ValueError(f"unknown policy: {r['design']}")
                rows.append(r)
    if not rows:
        raise ValueError("no measured observations")
    return rows


def summarize(rows: list[dict[str, Any]]):
    grouped = defaultdict(list)
    seen = set()
    for r in rows:
        group_id = (r["window_label"], r["client_count"], r["workload"])
        key = group_id + (r["seed"], r["repetition"], r["design"])
        if key in seen:
            raise ValueError(f"duplicate physical configuration / policy row: {key}")
        seen.add(key)
        grouped[(group_id, r["design"])].append(r)

    outcomes = []
    for (g, design), subset in sorted(grouped.items()):
        ok = [r for r in subset if r["ok"]]
        lo, hi = wilson(len(ok), len(subset))
        rec = {"window": g[0], "clients": g[1], "workload": g[2], "policy": design,
               "attempts": len(subset), "successes": len(ok), "failures": len(subset) - len(ok),
               "success_rate": len(ok) / len(subset), "success_ci95_low": lo, "success_ci95_high": hi}
        for m in MEASURES:
            good = [r[m] for r in ok]
            rec[m + "_median_success_only"] = median(good)
            rec[m + "_p95_success_only"] = percentile(good, .95)
            rec[m + "_median_ci95_low"], rec[m + "_median_ci95_high"] = boot_ci(
                good, seed=20261106 + g[1] + sum(map(ord, g[0] + g[2] + design + m)))
        outcomes.append(rec)

    effects = []
    comparisons = defaultdict(dict)
    for (g, policy), subset in grouped.items():
        comparisons[g][policy] = {(r["seed"], r["repetition"]): r for r in subset}
    for g, policies in sorted(comparisons.items()):
        if "contestfl" not in policies:
            raise ValueError(f"ContestFL control missing for group {g}")
        base = policies["contestfl"]
        for other in POLICIES:
            if other == "contestfl":
                continue
            if other not in policies:
                raise ValueError(f"policy {other} missing for group {g}")
            alt = policies[other]
            common = sorted(set(base) & set(alt))
            valid = [key for key in common if base[key]["ok"] and alt[key]["ok"]]
            line = {"window": g[0], "clients": g[1], "workload": g[2],
                    "alternative": other, "attempts_control": len(base), "attempts_alternative": len(alt),
                    "matched": len(common), "matched_both_success": len(valid),
                    "incomplete_pairs": len(set(base) ^ set(alt)), "failed_pairs": len(common) - len(valid)}
            for metric in MEASURES:
                differences = [alt[key][metric] - base[key][metric] for key in valid]
                denom = [base[key][metric] for key in valid]
                ratios = [100 * differences[i] / denom[i] for i in range(len(valid)) if denom[i] > 0]
                line[metric + "_delta_median"] = median(differences)
                line[metric + "_delta_ci_low"], line[metric + "_delta_ci_high"] = boot_ci(
                    differences, seed=20261106 + g[1] + sum(map(ord, g[0] + g[2] + other + metric)))
                line[metric + "_percent_median"] = median(ratios)
            effects.append(line)
    return outcomes, effects


def write_csv(path: Path, rows):
    if not rows:
        raise ValueError("refusing to write an empty table")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fd:
        writer = csv.DictWriter(fd, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fmt(x, n=1):
    if not math.isfinite(float(x)):
        return "n/a"
    return f"{x:,.{n}f}"


def latex_escape(s):
    return str(s).replace("_", r"\_").replace("%", r"\%")


def write_latex(path: Path, outcomes):
    # A single compact table intended to REPLACE (not add to) manuscript results.
    lines = [r"% Generated solely from measured v3 CSVs. Latency conditions on success.",
             r"\begin{tabular}{lllr rr}", r"\toprule",
             r"Window / clients & Fault & Policy & Success & Median finality (s) & Median gas (M) \\",
             r"\midrule"]
    for row in outcomes:
        label = latex_escape(row["window"] + " / " + str(row["clients"]))
        fault = latex_escape(row["workload"])
        policy = latex_escape(row["policy"])
        success = str(row["successes"]) + "/" + str(row["attempts"])
        wall = fmt(row["wall_ms_median_success_only"] / 1000, 2)
        gas = fmt(row["gas_total_median_success_only"] / 1e6, 3)
        lines.append(f"{label} & {fault} & {policy} & {success} & {wall} & {gas} " + r"\\")
    lines += [r"\bottomrule", r"\end{tabular}",
              r"% Conditional medians; never report the median without its success denominator."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(path, outcomes, effects):
    primary = [x for x in effects if x["window"] == "sized"]
    lines = ["# ContestFL v3 — results to substitute into existing figures/tables", "",
             "**Evidence status:** generated from measured on-chain output. No historical values were imputed.",
             "Each policy receives the same deterministic update arrays/seed within its window, client-size and fault configuration.",
             "This is matched by input, not simultaneous deployment or matched wall-clock block height.",
             "The on-chain *protocol* time does **not** measure end-to-end Flower training throughput.",
             "", "## Primary: correctly finalized checkpoints and conditional performance", "",
             "| Window | Clients | Fault | Policy | Correct / runs | Median finality (s) | Median gas (M) |",
             "|---|---:|---|---|---:|---:|---:|"]
    for r in outcomes:
        lines.append("| {window} | {clients} | {workload} | {policy} | {successes}/{attempts} | {t} | {g} |".format(
            **r, t=fmt(r["wall_ms_median_success_only"]/1000, 2), g=fmt(r["gas_total_median_success_only"]/1e6, 3)))
    lines += ["", "## Paired differences: positive = alternative more expensive than ContestFL", "",
              "Percentile bootstrap 95% CI of paired medians. Treat intervals from small samples as descriptive.",
              "Failed or unpaired runs are not silently replaced with zeros or excluded from the success denominator.", "",
              "| Window | Clients | Fault | Alternative | Pairs both correct | Wall Δ (s) [95% CI] | Gas Δ (M) [95% CI] |",
              "|---|---:|---|---|---:|---:|---:|"]
    for r in effects:
        lines.append(f"| {r['window']} | {r['clients']} | {r['workload']} | {r['alternative']} | {r['matched_both_success']}/{r['matched']} | "
                     f"{fmt(r['wall_ms_delta_median']/1000,2)} [{fmt(r['wall_ms_delta_ci_low']/1000,2)}, {fmt(r['wall_ms_delta_ci_high']/1000,2)}] | "
                     f"{fmt(r['gas_total_delta_median']/1e6,3)} [{fmt(r['gas_total_delta_ci_low']/1e6,3)}, {fmt(r['gas_total_delta_ci_high']/1e6,3)}] |")
    lines += ["", "## Scope and integrity", "",
              "- Eager pre-verifies all decision classes and does not wait for an optimistic challenge window.",
              "- Abort/restart and downstream re-audit are explicitly defined *policy designs on a common experimental substrate*; not reproductions of related work.",
              "- Root-only/Merkle storage ablations are not asserted to provide full semantic equivalence.",
              "- The chosen 'sized' window is a projection from measured local watcher time plus modeled bandwidth and object-store RTT; it does **not** prove C1 under adversarial load.",
              "- The 'short' window is a diagnostic sensitivity, not a production design recommendation.",
              "- Gas represents EVM resource use, not monetary cost. The external evidence policy/resolver assumptions remain explicit.",
              "- If the reviewer claim requires complete FL throughput, use the separate Flower path; do not relabel protocol completions as training throughput.",
              "- Conditional medians refer ONLY to runs with an independently checked on-chain correct checkpoint; the correctness counts must accompany any figure.",
              ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def make_figures(outdir: Path, outcomes: list[dict]):
    """Replacement for existing latency/cost figure, *one* compact 2-panel PDF."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    subset = [r for r in outcomes if r["window"] == "sized" and r["clients"] == max(x["clients"] for x in outcomes if x["window"] == "sized")]
    if not subset:
        return False
    faults = [x for x in ("clean", "bad_admission", "bad_omission", "bad_aggregate") if any(r["workload"] == x for r in subset)]
    if not faults:
        return False
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.2), constrained_layout=True)
    # Do not interpolate, impute or hide failed-only conditions.
    for j, policy in enumerate(POLICIES):
        vals = [next((r for r in subset if r["workload"] == f and r["policy"] == policy), None) for f in faults]
        xx = [i + (j - 1.5) * .18 for i in range(len(faults))]
        for ax, factor, field in ((axes[0], 1e-3, "wall_ms"),
                                   (axes[1], 1e-6, "gas_total")):
            for k, v in enumerate(vals):
                if not v or not v["successes"]:
                    continue
                center = v[field + "_median_success_only"]
                lo = v[field + "_median_ci95_low"]
                hi = v[field + "_median_ci95_high"]
                ax.bar(xx[k], center * factor, width=.17,
                       yerr=[[max(0, center-lo)*factor], [max(0, hi-center)*factor]],
                       capsize=2, label=policy if ax == axes[0] and k == 0 else None)
    axes[0].set_ylabel("Finalization wall time (s), successful only")
    axes[1].set_ylabel("Total receipt gas (million), successful only")
    for ax in axes:
        ax.set_xticks(range(len(faults)), [v.replace("bad_", "") for v in faults], rotation=18, ha="right")
        ax.grid(axis="y", alpha=.2)
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="outside upper center", ncol=4)
    fig.text(.5, -.02, "Bars: correct finalizations only; whiskers: 95% bootstrap CI of median. Success counts in accompanying table.",
             ha="center", fontsize=7)
    fig.savefig(outdir / "replacement_existing_cost_latency.pdf", bbox_inches="tight")
    plt.close(fig)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", type=Path, nargs="+", required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = read_rows(args.inputs)
    outcome, effects = summarize(rows)
    write_csv(args.output_dir / "focused_policy_summary.csv", outcome)
    write_csv(args.output_dir / "focused_paired_effects.csv", effects)
    write_latex(args.output_dir / "replacement_existing_table.tex", outcome)
    write_report(args.output_dir / "FOCUSED_REPLACEMENT_REPORT.md", outcome, effects)
    plotted = False if args.no_plot else make_figures(args.output_dir, outcome)
    (args.output_dir / "FOCUSED_ANALYSIS_MANIFEST.json").write_text(json.dumps({
        "input_paths": [str(p) for p in args.inputs], "measured_rows": len(rows),
        "groups": len(outcome), "paired_effects": len(effects),
        "figure_produced": plotted, "integrity": "no source value imputed; failed measurements are reported"
    }, indent=2) + "\n")
    print(json.dumps({"measured_rows": len(rows), "groups": len(outcome), "paired_effects": len(effects), "figure_produced": plotted}))


if __name__ == "__main__":
    main()
