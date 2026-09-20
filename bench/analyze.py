#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def q95(series: pd.Series) -> float:
    return float(series.quantile(0.95))


def save_table_tex(frame: pd.DataFrame, path: Path, caption: str, label: str) -> None:
    path.write_text(
        frame.to_latex(
            index=False,
            escape=True,
            float_format=lambda value: f"{value:.2f}",
            caption=caption,
            label=label,
        ),
        encoding="utf-8",
    )


def read_many(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        frame = pd.read_csv(path)
        if "campaign_tag" not in frame.columns:
            frame["campaign_tag"] = "core"
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def line_figure(frame: pd.DataFrame, groups: list[str], x: str, y: str, xlabel: str, ylabel: str, path: Path) -> None:
    if frame.empty:
        return
    fig, ax = plt.subplots(figsize=(6.7, 3.9))
    grouped = frame.groupby(groups) if groups else [((), frame)]
    for keys, group in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)
        group = group.sort_values(x)
        label = ", ".join(f"{name}={value}" for name, value in zip(groups, keys)) or None
        ax.plot(group[x], group[y], marker="o", label=label)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    if groups:
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(path.with_suffix(".png"), dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = ROOT / args.run_dir
    raw_dir = run_dir / "raw"
    figures = run_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    round_files = sorted(raw_dir.glob("rounds*_v*.csv"))
    transaction_files = sorted(raw_dir.glob("transactions*_v*.csv"))
    adapter_files = sorted(raw_dir.glob("adapters*_v*.csv"))
    if not round_files:
        raise RuntimeError(f"no blockchain result files found in {raw_dir}")
    rounds = read_many(round_files)
    transactions = read_many(transaction_files)
    adapters = read_many(adapter_files)

    rounds["invariant_ok"] = rounds["invariant_ok"].astype(str).str.lower().eq("true")
    for column, default in [
        ("batch_size", 50),
        ("challenge_blocks", 1),
        ("flood_count", 0),
        ("flood_parallelism", 0),
        ("network_rtt_ms", 0),
        ("update_dim", 0),
    ]:
        if column not in rounds:
            rounds[column] = default

    dimensions = [
        "campaign_tag",
        "validators",
        "clients",
        "scenario",
        "batch_size",
        "challenge_blocks",
        "flood_count",
        "flood_parallelism",
        "network_rtt_ms",
        "update_dim",
    ]
    summary = (
        rounds.groupby(dimensions, as_index=False)
        .agg(
            runs=("round_id", "count"),
            success_rate=("invariant_ok", "mean"),
            total_ms_median=("total_ms", "median"),
            total_ms_p95=("total_ms", q95),
            gas_median=("gas_total", "median"),
            gas_p95=("gas_total", q95),
            tx_median=("tx_count", "median"),
            blocks_median=("block_span", "median"),
            retries_median=("retries_used", "median"),
            challenges_median=("challenge_count", "median"),
            calldata_median=("calldata_bytes", "median"),
        )
        .sort_values(dimensions)
    )
    summary.to_csv(run_dir / "summary.csv", index=False)

    phase = pd.DataFrame()
    if not transactions.empty:
        phase = (
            transactions.groupby(
                ["campaign_tag", "validators", "clients", "scenario", "phase"], as_index=False
            )
            .agg(
                tx_count=("tx_hash", "count"),
                gas_median=("gas_used", "median"),
                gas_total=("gas_used", "sum"),
                latency_ms_median=("latency_ms", "median"),
                calldata_total=("calldata_bytes", "sum"),
            )
        )
        phase.to_csv(run_dir / "phase_summary.csv", index=False)

    adapter_summary = pd.DataFrame()
    if not adapters.empty:
        adapters["valid_evidence"] = adapters["valid_evidence"].astype(str).str.lower().eq("true")
        adapter_summary = (
            adapters.groupby(["adapter", "scenario", "validators", "clients", "verdict"], as_index=False)
            .agg(
                runs=("round_id", "count"),
                evidence_valid_rate=("valid_evidence", "mean"),
                generation_ms_median=("evidence_generation_ms", "median"),
                generation_cpu_ms_median=("evidence_generation_cpu_ms", "median"),
                verification_ms_median=("verification_ms", "median"),
                verification_cpu_ms_median=("verification_cpu_ms", "median"),
                verification_ms_p95=("verification_ms", q95),
                proof_bytes_median=("proof_bytes", "median"),
                artifact_bytes_median=("artifact_bytes", "median"),
            )
            .sort_values(["adapter", "scenario", "validators", "clients"])
        )
        adapter_summary.to_csv(run_dir / "adapter_summary.csv", index=False)

    core = summary[summary["campaign_tag"] == "core"].copy()
    core.to_csv(run_dir / "core_summary.csv", index=False)
    core_nominal = core[core["scenario"].isin(["logging_only", "nominal"])].copy()
    core_faults = core[~core["scenario"].isin(["logging_only", "nominal"])].copy()
    if not core_nominal.empty:
        save_table_tex(
            core_nominal[
                ["validators", "clients", "scenario", "total_ms_median", "total_ms_p95", "gas_median", "tx_median", "blocks_median"]
            ],
            run_dir / "table_nominal.tex",
            "Nominal-path overhead.",
            "tab:contestfl-nominal",
        )
        line_figure(
            core_nominal,
            ["validators", "scenario"],
            "clients",
            "blocks_median",
            "Simulated clients",
            "Median block span",
            figures / "nominal_blocks",
        )
        line_figure(
            core_nominal,
            ["validators", "scenario"],
            "clients",
            "gas_median",
            "Simulated clients",
            "Median gas / round",
            figures / "nominal_gas",
        )
    if not core_faults.empty:
        save_table_tex(
            core_faults[
                ["validators", "clients", "scenario", "success_rate", "total_ms_median", "gas_median", "retries_median", "blocks_median"]
            ],
            run_dir / "table_faults.tex",
            "Fault-injection and correction results.",
            "tab:contestfl-faults",
        )

    # Correction overhead at the largest core client count.
    overhead = pd.DataFrame()
    if not core.empty and not core[core["scenario"] == "nominal"].empty:
        largest = int(core["clients"].max())
        overhead = core[core["clients"] == largest].copy()
        baseline = overhead[overhead["scenario"] == "nominal"][
            ["validators", "total_ms_median", "gas_median", "blocks_median"]
        ].rename(
            columns={
                "total_ms_median": "nominal_ms",
                "gas_median": "nominal_gas",
                "blocks_median": "nominal_blocks",
            }
        )
        overhead = overhead.merge(baseline, on="validators", how="left")
        overhead["latency_delta_ms"] = overhead["total_ms_median"] - overhead["nominal_ms"]
        overhead["gas_delta"] = overhead["gas_median"] - overhead["nominal_gas"]
        overhead["block_delta"] = overhead["blocks_median"] - overhead["nominal_blocks"]
        overhead.to_csv(run_dir / "scenario_overhead.csv", index=False)
        plot = overhead[~overhead["scenario"].isin(["logging_only", "nominal"])].copy()
        if not plot.empty:
            fig, ax = plt.subplots(figsize=(8.4, 4.2))
            pivot = plot.pivot(index="scenario", columns="validators", values="block_delta").sort_index()
            pivot.plot(kind="bar", ax=ax)
            ax.set_ylabel("Additional blocks over nominal")
            ax.set_xlabel("")
            ax.grid(True, axis="y", alpha=0.3)
            ax.legend(title="Validators")
            fig.tight_layout()
            fig.savefig(figures / "correction_block_overhead.pdf", bbox_inches="tight")
            fig.savefig(figures / "correction_block_overhead.png", dpi=220, bbox_inches="tight")
            plt.close(fig)

    capacity = summary[summary["campaign_tag"].str.startswith("capacity_")].copy()
    if not capacity.empty:
        capacity.to_csv(run_dir / "capacity_summary.csv", index=False)
        line_figure(
            capacity[capacity["scenario"] == "nominal"],
            ["batch_size"],
            "clients",
            "blocks_median",
            "Simulated clients",
            "Median block span",
            figures / "capacity_blocks",
        )
        line_figure(
            capacity[capacity["scenario"] == "nominal"],
            ["batch_size"],
            "clients",
            "gas_median",
            "Simulated clients",
            "Median gas / round",
            figures / "capacity_gas",
        )

    window = summary[summary["campaign_tag"].str.startswith("window_")].copy()
    if not window.empty:
        window.to_csv(run_dir / "challenge_window_summary.csv", index=False)
        line_figure(
            window,
            ["clients"],
            "challenge_blocks",
            "total_ms_median",
            "Challenge window (blocks)",
            "Median round latency (ms)",
            figures / "challenge_window_latency",
        )
        line_figure(
            window,
            ["clients"],
            "challenge_blocks",
            "blocks_median",
            "Challenge window (blocks)",
            "Median block span",
            figures / "challenge_window_blocks",
        )

    flooding = summary[summary["campaign_tag"].str.startswith("flood_")].copy()
    if not flooding.empty:
        flooding.to_csv(run_dir / "flooding_summary.csv", index=False)
        line_figure(
            flooding,
            ["flood_parallelism"],
            "flood_count",
            "gas_median",
            "False challenges",
            "Median gas / round",
            figures / "flooding_gas",
        )
        line_figure(
            flooding,
            ["flood_parallelism"],
            "flood_count",
            "blocks_median",
            "False challenges",
            "Median block span",
            figures / "flooding_blocks",
        )

    network = summary[summary["campaign_tag"].str.startswith("network_")].copy()
    if not network.empty:
        network.to_csv(run_dir / "network_sensitivity_summary.csv", index=False)
        line_figure(
            network,
            ["validators", "clients"],
            "network_rtt_ms",
            "total_ms_median",
            "Emulated validator RTT (ms)",
            "Median round latency (ms)",
            figures / "network_latency",
        )

    if not adapter_summary.empty:
        # Aggregate over scenarios for a compact microbenchmark figure.
        compact = (
            adapter_summary.groupby(["adapter", "clients"], as_index=False)
            .agg(
                verification_ms_median=("verification_ms_median", "median"),
                proof_bytes_median=("proof_bytes_median", "median"),
                artifact_bytes_median=("artifact_bytes_median", "median"),
            )
        )
        line_figure(
            compact,
            ["adapter"],
            "clients",
            "verification_ms_median",
            "Simulated clients",
            "Median adapter verification (ms)",
            figures / "adapter_verification",
        )
        save_table_tex(
            adapter_summary[
                ["adapter", "scenario", "clients", "verdict", "verification_ms_median", "verification_cpu_ms_median", "verification_ms_p95", "proof_bytes_median", "artifact_bytes_median"]
            ],
            run_dir / "table_adapters.tex",
            "Evidence-adapter generation and verification costs.",
            "tab:contestfl-adapters",
        )

    local_path = raw_dir / "local_baselines_summary.csv"
    local = pd.read_csv(local_path) if local_path.exists() else pd.DataFrame()
    if not local.empty:
        line_figure(
            local,
            [],
            "clients",
            "eager_replay_ms_median",
            "Simulated clients",
            "Median eager replay (ms)",
            figures / "local_eager_replay",
        )

    optimistic_path = run_dir / "optimistic_regime.csv"
    optimistic = pd.read_csv(optimistic_path) if optimistic_path.exists() else pd.DataFrame()
    if not optimistic.empty:
        largest_artifact = optimistic["artifacts_bytes"].max()
        plot = optimistic[optimistic["artifacts_bytes"] == largest_artifact]
        line_figure(
            plot,
            ["clients", "update_bytes"],
            "challenge_rate",
            "optimistic_verification_cpu_ms_per_round",
            "Challenge rate",
            "Expected replay CPU / round (ms)",
            figures / "optimistic_regime",
        )

    fuzz_summary_path = raw_dir / "state_machine_fuzz_summary.json"
    fuzz_summary = json.loads(fuzz_summary_path.read_text(encoding="utf-8")) if fuzz_summary_path.exists() else {}
    failures = rounds[~rounds["invariant_ok"]]
    report_lines = [
        "# ContestFL experimental campaign report",
        "",
        f"- Measured blockchain rounds: **{len(rounds)}**",
        f"- Transaction receipts: **{len(transactions)}**",
        f"- Evidence-adapter executions: **{len(adapters)}**",
        f"- Validator configurations: **{', '.join(map(str, sorted(rounds['validators'].unique())))}**",
        f"- Failed blockchain invariants: **{len(failures)}**",
    ]
    if fuzz_summary:
        report_lines += [
            f"- Randomized model sequences: **{fuzz_summary.get('sequences', 0)}**",
            f"- Randomized invariant failures: **{fuzz_summary.get('failures', 0)}**",
        ]
    report_lines += [
        "",
        "## Core campaign",
        "",
        core.to_markdown(index=False, floatfmt=".2f") if not core.empty else "No core results.",
        "",
        "## Evidence adapters",
        "",
        adapter_summary.to_markdown(index=False, floatfmt=".3f") if not adapter_summary.empty else "No adapter results.",
        "",
        "## Targeted sweeps",
        "",
        f"- Capacity configurations: **{len(capacity)}**",
        f"- Challenge-window configurations: **{len(window)}**",
        f"- Flooding configurations: **{len(flooding)}**",
        f"- Network-sensitivity configurations: **{len(network)}**",
        "",
        "## Interpretation constraints",
        "",
        "Gas is deterministic for the deployed bytecode and calls. End-to-end latency depends on the Besu block period, challenge-window policy, host, and network emulation. Adapter measurements include actual receipt lookup, sparse-Merkle proof generation/verification, and deterministic aggregate replay. The tc/netem campaign applies controlled delay only to the validator P2P interfaces on one host and is not a substitute for a physical multi-host deployment.",
    ]
    if len(failures):
        report_lines += ["", "## Failed runs", "", failures.to_markdown(index=False)]
    (run_dir / "REPORT.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    manifest = {
        "round_files": [str(path) for path in round_files],
        "transaction_files": [str(path) for path in transaction_files],
        "adapter_files": [str(path) for path in adapter_files],
        "summary": str(run_dir / "summary.csv"),
        "core_summary": str(run_dir / "core_summary.csv"),
        "adapter_summary": str(run_dir / "adapter_summary.csv"),
        "report": str(run_dir / "REPORT.md"),
        "figures": [str(path) for path in sorted(figures.glob("*"))],
    }
    (run_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
