#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def summarize(df: pd.DataFrame, design: str, workload_col: str, scenario_map: dict[str, str]) -> pd.DataFrame:
    data = df.copy()
    data["design"] = design
    data["workload"] = data[workload_col].map(scenario_map).fillna(data[workload_col])
    if "invariant_ok" in data:
        data["semantic_ok_normalized"] = as_bool(data["invariant_ok"])
    else:
        data["semantic_ok_normalized"] = as_bool(data["semantic_ok"])
    grouped = data.groupby(["design", "workload", "clients"], as_index=False)
    return grouped.agg(
        runs=("round_id", "count"),
        success_rate=("semantic_ok_normalized", "mean"),
        gas_median=("gas_total", "median"),
        calldata_median=("calldata_bytes", "median"),
        tx_median=("tx_count", "median"),
        blocks_median=("block_span", "median"),
        latency_ms_median=("total_ms", "median"),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = ROOT / args.run_dir
    raw = run_dir / "raw"

    materialized_files = sorted(raw.glob("rounds_root_materialized_v*.csv"))
    root_files = sorted(raw.glob("root_only_rounds_root_only_v*.csv"))
    if not materialized_files or not root_files:
        raise FileNotFoundError("root-only ablation CSVs are incomplete")

    materialized = pd.concat([pd.read_csv(path) for path in materialized_files], ignore_index=True)
    root_only = pd.concat([pd.read_csv(path) for path in root_files], ignore_index=True)
    materialized_ok = as_bool(materialized["invariant_ok"])
    root_ok = as_bool(root_only["semantic_ok"])

    materialized_summary = summarize(
        materialized,
        "materialized",
        "scenario",
        {"nominal": "clean", "bad_admission": "bad_admission", "bad_aggregate": "bad_aggregate"},
    )
    root_summary = summarize(root_only, "root_only", "workload", {})
    summary = pd.concat([materialized_summary, root_summary], ignore_index=True)

    audit = summary.pivot_table(
        index=["workload", "clients"],
        columns="design",
        values=["gas_median", "calldata_median", "tx_median", "blocks_median"],
    )
    rows: list[dict[str, float | int | str]] = []
    for (workload, clients), values in audit.iterrows():
        row: dict[str, float | int | str] = {"workload": workload, "clients": int(clients)}
        for metric in ("gas_median", "calldata_median", "tx_median", "blocks_median"):
            materialized_value = float(values.get((metric, "materialized"), float("nan")))
            root_value = float(values.get((metric, "root_only"), float("nan")))
            row[f"materialized_{metric}"] = materialized_value
            row[f"root_only_{metric}"] = root_value
            row[f"root_only_reduction_{metric}_pct"] = (
                100.0 * (materialized_value - root_value) / materialized_value
                if materialized_value > 0 else float("nan")
            )
        rows.append(row)
    comparison = pd.DataFrame(rows).sort_values(["workload", "clients"])

    summary.to_csv(run_dir / "root_only_ablation_summary.csv", index=False)
    comparison.to_csv(run_dir / "root_only_ablation_comparison.csv", index=False)

    failures = int((~materialized_ok).sum() + (~root_ok).sum())
    lines = [
        "# Root-only authenticated-state ablation",
        "",
        f"- Materialized rounds: **{len(materialized)}**",
        f"- Root-only rounds: **{len(root_only)}**",
        f"- Failed semantic/invariant checks: **{failures}**",
        "",
        "The materialized design stores one submission and one decision state per client. The root-only design stores authenticated roots and reveals a sparse-Merkle path only for the challenged client. Both use the same client populations, update dimensions, QBFT network, challenge policy, and resolver trust boundary.",
        "",
        "## Comparison",
        "",
        comparison.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## Interpretation boundary",
        "",
        "The root-only contract is an ablation of storage representation, not a replacement implementation of every ContestFL recovery path. The measured workloads cover a client-decision revision with an on-chain sparse-Merkle proof and an aggregate-checkpoint revision with O(1) on-chain state. Dependent-challenge mooting, correction laundering, resolver fallback, and flooding remain evaluated by the materialized prototype.",
    ]
    (run_dir / "ROOT_ONLY_ABLATION_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(run_dir / "ROOT_ONLY_ABLATION_REPORT.md")


if __name__ == "__main__":
    main()
