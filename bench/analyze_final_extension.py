#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: Sequence[float], p: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * p
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bootstrap_median_ci(values: Sequence[float], seed: int, samples: int = 5000) -> tuple[float, float]:
    array = np.asarray(list(values), dtype=float)
    if array.size < 2:
        value = float(array[0]) if array.size else math.nan
        return value, value
    rng = np.random.default_rng(seed)
    indexes = rng.integers(0, array.size, size=(samples, array.size))
    medians = np.median(array[indexes], axis=1)
    return float(np.quantile(medians, 0.025)), float(np.quantile(medians, 0.975))


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def read_concat(paths: Iterable[Path]) -> pd.DataFrame:
    frames = [pd.read_csv(path) for path in paths if path.is_file() and path.stat().st_size > 0]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def normalize_rounds(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    defaults = {
        "network_rtt_ms": 0,
        "campaign_tag": "unknown",
        "invariant_ok": True,
        "error": "",
    }
    for column, value in defaults.items():
        if column not in result.columns:
            result[column] = value
    result["network_rtt_ms"] = pd.to_numeric(result["network_rtt_ms"], errors="coerce").fillna(0)
    return result


def summarize_rounds(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    group_columns = ["campaign_tag", "validators", "clients", "scenario", "network_rtt_ms"]
    for keys, group in frame.groupby(group_columns, dropna=False):
        total = group["total_ms"].astype(float).tolist()
        gas = group["gas_total"].astype(float).tolist()
        tx = group["tx_count"].astype(float).tolist()
        blocks = group["block_span"].astype(float).tolist()
        calldata = group["calldata_bytes"].astype(float).tolist()
        seed = (
            int(group["validators"].iloc[0]) * 100_000
            + int(group["clients"].iloc[0]) * 10
            + int(float(group["network_rtt_ms"].iloc[0]))
        )
        ci_low, ci_high = bootstrap_median_ci(total, seed=seed)
        rows.append(
            {
                "campaign_tag": keys[0],
                "validators": int(keys[1]),
                "clients": int(keys[2]),
                "scenario": keys[3],
                "network_rtt_ms": float(keys[4]),
                "runs": len(group),
                "success_rate": float(group["invariant_ok"].astype(str).str.lower().eq("true").mean()),
                "total_ms_median": statistics.median(total),
                "total_ms_q1": percentile(total, 0.25),
                "total_ms_q3": percentile(total, 0.75),
                "total_ms_p95": percentile(total, 0.95),
                "total_ms_bootstrap_ci_low": ci_low,
                "total_ms_bootstrap_ci_high": ci_high,
                "gas_median": statistics.median(gas),
                "gas_q1": percentile(gas, 0.25),
                "gas_q3": percentile(gas, 0.75),
                "tx_median": statistics.median(tx),
                "blocks_median": statistics.median(blocks),
                "calldata_median": statistics.median(calldata),
            }
        )
    return pd.DataFrame(rows).sort_values(group_columns).reset_index(drop=True)


def validator_delta(summary: pd.DataFrame) -> pd.DataFrame:
    subset = summary[
        summary["campaign_tag"].isin(
            ["confirm_nominal", "confirm_corrections", "validator_nominal", "validator_corrections"]
        )
    ].copy()
    if subset.empty:
        return pd.DataFrame()
    reduced = subset[
        [
            "validators",
            "clients",
            "scenario",
            "runs",
            "total_ms_median",
            "total_ms_q1",
            "total_ms_q3",
            "gas_median",
            "tx_median",
            "blocks_median",
        ]
    ]
    v4 = reduced[reduced["validators"] == 4].drop(columns="validators").add_suffix("_v4")
    v7 = reduced[reduced["validators"] == 7].drop(columns="validators").add_suffix("_v7")
    merged = v4.merge(
        v7,
        left_on=["clients_v4", "scenario_v4"],
        right_on=["clients_v7", "scenario_v7"],
        how="inner",
    )
    if merged.empty:
        return pd.DataFrame()
    result = pd.DataFrame(
        {
            "clients": merged["clients_v4"].astype(int),
            "scenario": merged["scenario_v4"],
            "runs_v4": merged["runs_v4"].astype(int),
            "runs_v7": merged["runs_v7"].astype(int),
            "total_ms_median_v4": merged["total_ms_median_v4"],
            "total_ms_median_v7": merged["total_ms_median_v7"],
            "latency_delta_percent": 100
            * (merged["total_ms_median_v7"] - merged["total_ms_median_v4"])
            / merged["total_ms_median_v4"],
            "gas_median_v4": merged["gas_median_v4"],
            "gas_median_v7": merged["gas_median_v7"],
            "gas_delta_percent": 100
            * (merged["gas_median_v7"] - merged["gas_median_v4"])
            / merged["gas_median_v4"],
            "blocks_median_v4": merged["blocks_median_v4"],
            "blocks_median_v7": merged["blocks_median_v7"],
        }
    )
    return result.sort_values(["clients", "scenario"]).reset_index(drop=True)


def network_summary(summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    network = summary[summary["campaign_tag"].astype(str).str.startswith("network")].copy()
    if network.empty:
        return network, pd.DataFrame()
    network = network.sort_values(["validators", "scenario", "network_rtt_ms"]).reset_index(drop=True)
    baseline = network[network.network_rtt_ms == 0][
        ["validators", "clients", "scenario", "total_ms_median", "gas_median", "blocks_median"]
    ].rename(
        columns={
            "total_ms_median": "baseline_total_ms_median",
            "gas_median": "baseline_gas_median",
            "blocks_median": "baseline_blocks_median",
        }
    )
    delta = network.merge(baseline, on=["validators", "clients", "scenario"], how="left")
    delta["latency_delta_ms"] = delta.total_ms_median - delta.baseline_total_ms_median
    delta["latency_delta_percent"] = 100 * delta.latency_delta_ms / delta.baseline_total_ms_median
    delta["gas_delta_percent"] = 100 * (delta.gas_median - delta.baseline_gas_median) / delta.baseline_gas_median
    delta["blocks_delta"] = delta.blocks_median - delta.baseline_blocks_median
    return network, delta


def save_nominal_latency(summary: pd.DataFrame, figures: Path) -> None:
    subset = summary[(summary.validators == 4) & (summary.campaign_tag == "confirm_nominal")]
    if subset.empty:
        return
    plt.figure(figsize=(6.2, 3.7))
    for scenario in ["logging_only", "nominal"]:
        group = subset[subset.scenario == scenario].sort_values("clients")
        if group.empty:
            continue
        y = group.total_ms_median.to_numpy() / 1000.0
        lower = y - group.total_ms_q1.to_numpy() / 1000.0
        upper = group.total_ms_q3.to_numpy() / 1000.0 - y
        plt.errorbar(group.clients, y, yerr=np.vstack([lower, upper]), marker="o", capsize=3, label=scenario)
    plt.xlabel("Clients")
    plt.ylabel("End-to-end latency (s)")
    plt.title("Four-validator confirmation campaign")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figures / "confirmation_nominal_latency.pdf", bbox_inches="tight")
    plt.savefig(figures / "confirmation_nominal_latency.png", dpi=220, bbox_inches="tight")
    plt.close()


def save_correction_overhead(summary: pd.DataFrame, figures: Path) -> None:
    nominal_rows = summary[
        (summary.validators == 4)
        & (summary.campaign_tag == "confirm_nominal")
        & (summary.clients == 100)
        & (summary.scenario == "nominal")
    ]
    corrections = summary[
        (summary.validators == 4)
        & (summary.campaign_tag == "confirm_corrections")
        & (summary.clients == 100)
    ].copy()
    if nominal_rows.empty or corrections.empty:
        return
    nominal = nominal_rows.iloc[0]
    corrections["gas_overhead_millions"] = (corrections.gas_median - nominal.gas_median) / 1e6
    corrections["latency_overhead_s"] = (corrections.total_ms_median - nominal.total_ms_median) / 1000.0

    plt.figure(figsize=(6.5, 3.8))
    plt.bar(corrections.scenario, corrections.gas_overhead_millions)
    plt.ylabel("Additional gas (millions)")
    plt.title("Correction overhead at 100 clients")
    plt.xticks(rotation=20, ha="right")
    plt.grid(True, axis="y", alpha=0.25)
    plt.tight_layout()
    plt.savefig(figures / "confirmation_correction_gas_overhead.pdf", bbox_inches="tight")
    plt.savefig(figures / "confirmation_correction_gas_overhead.png", dpi=220, bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(6.5, 3.8))
    plt.bar(corrections.scenario, corrections.latency_overhead_s)
    plt.ylabel("Additional latency (s)")
    plt.title("Correction overhead at 100 clients")
    plt.xticks(rotation=20, ha="right")
    plt.grid(True, axis="y", alpha=0.25)
    plt.tight_layout()
    plt.savefig(figures / "confirmation_correction_latency_overhead.pdf", bbox_inches="tight")
    plt.savefig(figures / "confirmation_correction_latency_overhead.png", dpi=220, bbox_inches="tight")
    plt.close()


def save_validator_comparison(delta: pd.DataFrame, figures: Path) -> None:
    if delta.empty:
        return
    labels = [f"{row.scenario}\n{int(row.clients)} clients" for row in delta.itertuples()]
    x = np.arange(len(labels))
    width = 0.36

    plt.figure(figsize=(7.4, 4.0))
    plt.bar(x - width / 2, delta.total_ms_median_v4 / 1000.0, width, label="4 validators")
    plt.bar(x + width / 2, delta.total_ms_median_v7 / 1000.0, width, label="7 validators")
    plt.ylabel("Median latency (s)")
    plt.title("Same-host QBFT validator-count sensitivity")
    plt.xticks(x, labels, rotation=18, ha="right")
    plt.grid(True, axis="y", alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figures / "validator_count_latency.pdf", bbox_inches="tight")
    plt.savefig(figures / "validator_count_latency.png", dpi=220, bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(7.4, 4.0))
    plt.bar(x - width / 2, delta.gas_median_v4 / 1e6, width, label="4 validators")
    plt.bar(x + width / 2, delta.gas_median_v7 / 1e6, width, label="7 validators")
    plt.ylabel("Median gas (millions)")
    plt.title("EVM cost is validator-count independent")
    plt.xticks(x, labels, rotation=18, ha="right")
    plt.grid(True, axis="y", alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figures / "validator_count_gas.pdf", bbox_inches="tight")
    plt.savefig(figures / "validator_count_gas.png", dpi=220, bbox_inches="tight")
    plt.close()


def save_network_sensitivity(network: pd.DataFrame, probes: pd.DataFrame, figures: Path) -> None:
    if network.empty:
        return
    plt.figure(figsize=(6.8, 4.0))
    for (validators, scenario), group in network.groupby(["validators", "scenario"]):
        ordered = group.sort_values("network_rtt_ms")
        plt.plot(
            ordered.network_rtt_ms,
            ordered.total_ms_median / 1000.0,
            marker="o",
            label=f"{validators} validators — {scenario}",
        )
    plt.xlabel("Requested inter-validator RTT (ms)")
    plt.ylabel("Median end-to-end latency (s)")
    plt.title("Sensitivity to controlled P2P delay")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figures / "network_rtt_latency.pdf", bbox_inches="tight")
    plt.savefig(figures / "network_rtt_latency.png", dpi=220, bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(6.8, 4.0))
    for (validators, scenario), group in network.groupby(["validators", "scenario"]):
        ordered = group.sort_values("network_rtt_ms")
        plt.plot(
            ordered.network_rtt_ms,
            ordered.blocks_median,
            marker="o",
            label=f"{validators} validators — {scenario}",
        )
    plt.xlabel("Requested inter-validator RTT (ms)")
    plt.ylabel("Median block span")
    plt.title("Block-span sensitivity to P2P delay")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figures / "network_rtt_blocks.pdf", bbox_inches="tight")
    plt.savefig(figures / "network_rtt_blocks.png", dpi=220, bbox_inches="tight")
    plt.close()

    if not probes.empty:
        grouped = (
            probes.groupby(["validators", "requested_rtt_ms"], as_index=False)
            .agg(observed_rtt_ms=("observed_rtt_ms", "median"))
            .sort_values(["validators", "requested_rtt_ms"])
        )
        plt.figure(figsize=(5.8, 3.8))
        maximum = max(float(grouped.requested_rtt_ms.max()), float(grouped.observed_rtt_ms.max()), 1.0)
        plt.plot([0, maximum], [0, maximum], linestyle="--", label="requested = observed")
        for validators, group in grouped.groupby("validators"):
            plt.plot(
                group.requested_rtt_ms,
                group.observed_rtt_ms,
                marker="o",
                label=f"{validators} validators",
            )
        plt.xlabel("Requested RTT (ms)")
        plt.ylabel("Observed P2P ping RTT (ms)")
        plt.title("Network-emulation calibration")
        plt.grid(True, alpha=0.25)
        plt.legend()
        plt.tight_layout()
        plt.savefig(figures / "network_rtt_calibration.pdf", bbox_inches="tight")
        plt.savefig(figures / "network_rtt_calibration.png", dpi=220, bbox_inches="tight")
        plt.close()


def save_replay_plot(replay: pd.DataFrame, figures: Path) -> None:
    if replay.empty:
        return
    plt.figure(figsize=(6.4, 3.9))
    for clients, group in replay.groupby("clients"):
        ordered = group.sort_values("artifact_bytes")
        plt.plot(
            ordered.artifact_bytes / (1024 * 1024),
            ordered.verification_ms_median,
            marker="o",
            label=f"{int(clients)} clients",
        )
    plt.xscale("log")
    plt.yscale("log")
    plt.xlabel("Committed artifacts replayed (MiB)")
    plt.ylabel("Median verification time (ms)")
    plt.title("Memory-bounded deterministic replay")
    plt.grid(True, which="both", alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figures / "replay_scaling.pdf", bbox_inches="tight")
    plt.savefig(figures / "replay_scaling.png", dpi=220, bbox_inches="tight")
    plt.close()


def latex_escape(value: object) -> str:
    return str(value).replace("_", r"\_").replace("%", r"\%")


def write_latex_tables(
    run_dir: Path,
    summary: pd.DataFrame,
    delta: pd.DataFrame,
    replay: pd.DataFrame,
    network: pd.DataFrame,
) -> None:
    confirmation = summary[summary.campaign_tag.isin(["confirm_nominal", "confirm_corrections"])].copy()
    if not confirmation.empty:
        lines = [
            r"\begin{tabular}{lrrrrr}",
            r"\toprule",
            r"Scenario & Clients & Runs & Median (s) & Gas (M) & Blocks \\",
            r"\midrule",
        ]
        for row in confirmation.itertuples():
            lines.append(
                f"{latex_escape(row.scenario)} & {row.clients} & {row.runs} & "
                f"{row.total_ms_median / 1000:.3f} & {row.gas_median / 1e6:.3f} & {row.blocks_median:.0f}"
                + r" \\" 
            )
        lines += [r"\bottomrule", r"\end{tabular}"]
        (run_dir / "table_final_confirmation.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not delta.empty:
        lines = [
            r"\begin{tabular}{lrrrrr}",
            r"\toprule",
            r"Scenario & Clients & 4-val. (s) & 7-val. (s) & $\Delta$ latency & $\Delta$ gas \\",
            r"\midrule",
        ]
        for row in delta.itertuples():
            lines.append(
                f"{latex_escape(row.scenario)} & {row.clients} & {row.total_ms_median_v4 / 1000:.3f} & "
                f"{row.total_ms_median_v7 / 1000:.3f} & {row.latency_delta_percent:+.2f}\\% & "
                f"{row.gas_delta_percent:+.2f}\\%" + r" \\" 
            )
        lines += [r"\bottomrule", r"\end{tabular}"]
        (run_dir / "table_validator_comparison.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not replay.empty:
        lines = [
            r"\begin{tabular}{rrrrr}",
            r"\toprule",
            r"Clients & Update/client & Total artifacts & Runs & Replay (ms) \\",
            r"\midrule",
        ]
        for row in replay.itertuples():
            lines.append(
                f"{row.clients} & {row.update_bytes / 1024:.0f} KiB & "
                f"{row.artifact_bytes / (1024 * 1024):.2f} MiB & {row.runs} & "
                f"{row.verification_ms_median:.3f}" + r" \\" 
            )
        lines += [r"\bottomrule", r"\end{tabular}"]
        (run_dir / "table_replay_scaling.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not network.empty:
        lines = [
            r"\begin{tabular}{rrlrrrr}",
            r"\toprule",
            r"Validators & RTT & Scenario & Runs & Median (s) & Gas (M) & Blocks \\",
            r"\midrule",
        ]
        for row in network.itertuples():
            lines.append(
                f"{row.validators} & {row.network_rtt_ms:.0f} ms & {latex_escape(row.scenario)} & "
                f"{row.runs} & {row.total_ms_median / 1000:.3f} & "
                f"{row.gas_median / 1e6:.3f} & {row.blocks_median:.0f}" + r" \\" 
            )
        lines += [r"\bottomrule", r"\end{tabular}"]
        (run_dir / "table_network_sensitivity.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze ContestFL publication extension campaign")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    run_dir = ROOT / args.run_dir
    raw_dir = run_dir / "raw"
    figures = run_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    round_paths = sorted(raw_dir.glob("rounds_*.csv"))
    transaction_paths = sorted(raw_dir.glob("transactions_*.csv"))
    rounds = normalize_rounds(read_concat(round_paths))
    transactions = read_concat(transaction_paths)
    if rounds.empty:
        raise RuntimeError(f"no round CSVs found under {raw_dir}")

    failures = rounds[
        ~rounds["invariant_ok"].astype(str).str.lower().eq("true")
        | rounds["error"].fillna("").astype(str).str.strip().ne("")
    ]
    if not failures.empty:
        failures.to_csv(run_dir / "FAILED_ROUNDS.csv", index=False)
        raise RuntimeError(f"{len(failures)} failed rounds; see FAILED_ROUNDS.csv")

    summary = summarize_rounds(rounds)
    write_csv(run_dir / "final_confirmation_summary.csv", summary)
    delta = validator_delta(summary)
    write_csv(run_dir / "validator_comparison.csv", delta)
    network, network_delta = network_summary(summary)
    write_csv(run_dir / "network_sensitivity_summary.csv", network)
    write_csv(run_dir / "network_sensitivity_delta.csv", network_delta)

    replay_path = run_dir / "replay_scaling_summary.csv"
    replay = pd.read_csv(replay_path) if replay_path.is_file() else pd.DataFrame()
    probe_path = run_dir / "network_probe.csv"
    probes = pd.read_csv(probe_path) if probe_path.is_file() else pd.DataFrame()

    save_nominal_latency(summary, figures)
    save_correction_overhead(summary, figures)
    save_validator_comparison(delta, figures)
    save_network_sensitivity(network, probes, figures)
    save_replay_plot(replay, figures)
    write_latex_tables(run_dir, summary, delta, replay, network)

    measured_rounds = len(rounds)
    receipt_count = len(transactions)
    validators = sorted(int(value) for value in rounds.validators.unique())
    generated = [
        "`final_confirmation_summary.csv`",
        "`validator_comparison.csv`",
        "`network_sensitivity_summary.csv`",
        "`network_sensitivity_delta.csv`",
    ]
    if not replay.empty:
        generated.append("`replay_scaling_summary.csv`")
    if not probes.empty:
        generated.append("`network_probe.csv`")

    report = [
        "# ContestFL final experimental extension",
        "",
        f"- Measured blockchain rounds: **{measured_rounds}**",
        f"- Transaction receipts: **{receipt_count}**",
        f"- Validator counts evaluated: **{', '.join(map(str, validators))}**",
        f"- Failed blockchain invariants: **{len(failures)}**",
        f"- Replay configurations: **{len(replay)}**",
        f"- Network-delay configurations: **{len(network)}**",
        "",
        "## Scope",
        "",
        "The confirmation campaign increases the repetition count only for publication-critical paths. "
        "The validator-count study compares four and seven QBFT validators on the same physical host. "
        "The replay microbenchmark uses a memory-bounded implementation. The network extension applies "
        "Linux tc/netem only to the dedicated validator P2P interface; JSON-RPC traffic remains on an "
        "undelayed control network.",
        "",
        "## Interpretation constraints",
        "",
        "- Report medians and interquartile ranges as the primary latency statistics.",
        "- The bootstrap interval concerns run-to-run variability on this host; it is not a confidence interval over deployments.",
        "- Gas should be invariant to validator count and RTT for identical calls; use it as a consistency check.",
        "- Four versus seven validators are containerized on one host and do not constitute a WAN or multi-host QBFT evaluation.",
        "- tc/netem provides controlled P2P-delay sensitivity on one host; it is not a geographically distributed deployment.",
        "- Replay measurements exclude artifact-store retrieval, decryption, deserialization, and network transfer.",
        "",
        "## Generated artifacts",
        "",
        *[f"- {item}" for item in generated],
        "- `table_final_confirmation.tex` when confirmation data are present",
        "- `table_validator_comparison.tex` when both validator counts are present",
        "- `table_network_sensitivity.tex` when network data are present",
        "- `figures/network_rtt_latency.pdf` when network data are present",
        "- `figures/network_rtt_calibration.pdf` when probe data are present",
        "",
    ]
    (run_dir / "FINAL_EXTENSION_REPORT.md").write_text("\n".join(report), encoding="utf-8")
    metadata = {
        "roundFiles": [str(path.relative_to(run_dir)) for path in round_paths],
        "transactionFiles": [str(path.relative_to(run_dir)) for path in transaction_paths],
        "rounds": measured_rounds,
        "receipts": receipt_count,
        "validators": validators,
        "failures": len(failures),
        "replayConfigurations": len(replay),
        "networkConfigurations": len(network),
        "networkProbeRows": len(probes),
    }
    (run_dir / "final_extension_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
