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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = ROOT / args.run_dir
    raw = run_dir / "raw"
    round_files = sorted(raw.glob("root_only_rounds_depth_d*_v*.csv"))
    tx_files = sorted(raw.glob("root_only_transactions_depth_d*_v*.csv"))
    if not round_files or not tx_files:
        raise FileNotFoundError("depth-sensitivity CSVs are incomplete")

    rounds = pd.concat([pd.read_csv(path) for path in round_files], ignore_index=True)
    txs = pd.concat([pd.read_csv(path) for path in tx_files], ignore_index=True)
    rounds["semantic_ok"] = as_bool(rounds["semantic_ok"])
    proof_txs = txs[txs["phase"] == "challenge_with_proof"].copy()

    summary = rounds.groupby("smt_depth", as_index=False).agg(
        runs=("round_id", "count"),
        success_rate=("semantic_ok", "mean"),
        proof_bytes=("proof_bytes", "median"),
        total_gas=("gas_total", "median"),
        total_calldata=("calldata_bytes", "median"),
        total_latency_ms=("total_ms", "median"),
    )
    challenge = proof_txs.groupby("smt_depth", as_index=False).agg(
        challenge_gas=("gas_used", "median"),
        challenge_calldata=("calldata_bytes", "median"),
    ) if "smt_depth" in proof_txs.columns else pd.DataFrame()

    if challenge.empty:
        # TxMetric does not carry the depth in older files; recover it from the
        # tag, which is emitted as depth_d<depth> by the launcher.
        proof_txs["smt_depth"] = proof_txs["campaign_tag"].str.extract(r"depth_d(\d+)", expand=False).astype(int)
        challenge = proof_txs.groupby("smt_depth", as_index=False).agg(
            challenge_gas=("gas_used", "median"),
            challenge_calldata=("calldata_bytes", "median"),
        )
    summary = summary.merge(challenge, on="smt_depth", how="left").sort_values("smt_depth")
    summary.to_csv(run_dir / "root_depth_sensitivity_summary.csv", index=False)

    lines = [
        "# Sparse-Merkle depth sensitivity",
        "",
        f"- Failed semantic checks: **{int((~rounds['semantic_ok']).sum())}**",
        "- Workload: one challenged client decision at 500 clients.",
        "",
        summary.to_markdown(index=False, floatfmt=".2f"),
        "",
        "The proof path grows linearly with the configured depth. Clean-path root publication is depth-independent, whereas challenged-path calldata and verification gas are not. Depth 32 is therefore reported as an evaluated benchmark point, not as a universal production setting.",
    ]
    (run_dir / "ROOT_DEPTH_SENSITIVITY_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    if (~rounds["semantic_ok"]).any():
        raise SystemExit(2)
    print(run_dir / "ROOT_DEPTH_SENSITIVITY_REPORT.md")


if __name__ == "__main__":
    main()
