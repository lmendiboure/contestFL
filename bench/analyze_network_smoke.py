#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = ROOT / args.run_dir
    files = sorted((run_dir / "raw").glob("rounds_rtt*_v*.csv"))
    if not files:
        raise FileNotFoundError("no RTT round CSVs found")
    data = pd.concat([pd.read_csv(path) for path in files], ignore_index=True)
    ok = data["invariant_ok"].astype(str).str.lower().isin({"true", "1"})
    data["ok"] = ok
    summary = data.groupby(
        ["validators", "network_rtt_ms", "clients", "scenario"], as_index=False
    ).agg(
        runs=("round_id", "count"),
        success_rate=("ok", "mean"),
        latency_ms_median=("total_ms", "median"),
        latency_ms_q1=("total_ms", lambda x: x.quantile(0.25)),
        latency_ms_q3=("total_ms", lambda x: x.quantile(0.75)),
        blocks_median=("block_span", "median"),
        gas_median=("gas_total", "median"),
        tx_median=("tx_count", "median"),
    )
    baseline = summary[summary.network_rtt_ms == 0].rename(columns={
        "latency_ms_median": "baseline_latency_ms",
        "blocks_median": "baseline_blocks",
        "gas_median": "baseline_gas",
    })[["validators", "clients", "scenario", "baseline_latency_ms", "baseline_blocks", "baseline_gas"]]
    impaired = summary[summary.network_rtt_ms > 0].merge(
        baseline, on=["validators", "clients", "scenario"], how="left"
    )
    impaired["latency_delta_ms"] = impaired.latency_ms_median - impaired.baseline_latency_ms
    impaired["latency_delta_pct"] = 100.0 * impaired.latency_delta_ms / impaired.baseline_latency_ms
    impaired["block_delta"] = impaired.blocks_median - impaired.baseline_blocks
    impaired["gas_delta"] = impaired.gas_median - impaired.baseline_gas

    summary.to_csv(run_dir / "network_smoke_summary.csv", index=False)
    impaired.to_csv(run_dir / "network_smoke_delta.csv", index=False)
    probe_path = run_dir / "network_probe.csv"
    probes = pd.read_csv(probe_path) if probe_path.exists() and probe_path.stat().st_size else pd.DataFrame()

    failures = int((~ok).sum())
    lines = [
        "# Controlled P2P RTT smoke experiment",
        "",
        f"- Measured rounds: **{len(data)}**",
        f"- Failed invariants: **{failures}**",
        "- Emulation scope: validator P2P interfaces only; JSON-RPC remains on the control network.",
        "",
        "## Summary",
        "",
        summary.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## Relative to zero-delay runs",
        "",
        impaired.to_markdown(index=False, floatfmt=".2f"),
    ]
    if not probes.empty:
        lines += ["", "## RTT calibration", "", probes.to_markdown(index=False, floatfmt=".3f")]
    lines += [
        "",
        "## Interpretation boundary",
        "",
        "The validators remain co-located on one physical host. tc/netem adds controlled symmetric egress delay to the dedicated P2P network; the experiment is a delay-sensitivity check, not a geographically distributed QBFT benchmark.",
    ]
    (run_dir / "NETWORK_SMOKE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(run_dir / "NETWORK_SMOKE_REPORT.md")
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
