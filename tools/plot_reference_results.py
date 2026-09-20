#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "results" / "reference" / "summaries"
OUTPUT = ROOT / "figures" / "reference"
OUTPUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 7.5,
    "axes.labelsize": 7.5,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 6.5,
    "lines.linewidth": 1.1,
    "lines.markersize": 4,
    "axes.linewidth": 0.7,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})


def save(fig: plt.Figure, stem: str) -> None:
    fig.tight_layout(pad=0.35)
    fig.savefig(OUTPUT / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUTPUT / f"{stem}.png", dpi=500, bbox_inches="tight")
    plt.close(fig)


def plot_root(metric: str, ylabel: str, stem: str) -> None:
    data = pd.read_csv(REFERENCE / "root_only" / "root_only_ablation_summary.csv")
    series = [
        ("materialized", "clean", "Materialized, clean", "o", "-"),
        ("materialized", "bad_admission", "Materialized, challenged", "s", "-"),
        ("root_only", "clean", "Root-only, clean", "o", "--"),
        ("root_only", "bad_admission", "Root-only, challenged", "s", "--"),
    ]
    fig, ax = plt.subplots(figsize=(3.35, 2.05))
    for design, workload, label, marker, linestyle in series:
        frame = data[(data.design == design) & (data.workload == workload)].sort_values("clients")
        ax.plot(frame.clients, frame[metric], marker=marker, linestyle=linestyle, label=label)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks([10, 100, 500], labels=["10", "100", "500"])
    ax.set_xlabel("Number of FL clients")
    ax.set_ylabel(ylabel)
    ax.grid(True, which="major", linewidth=0.35, alpha=0.45)
    ax.legend(frameon=False, loc="upper left")
    save(fig, stem)


def plot_smt() -> None:
    data = pd.read_csv(REFERENCE / "smt_offchain" / "smt_offchain_summary.csv")
    labels = {
        "build_and_root": "Build + root",
        "single_update_and_root": "One update + root",
        "proof_generation": "Proof generation",
        "proof_verification": "Proof verification",
    }
    markers = {"build_and_root": "o", "single_update_and_root": "s", "proof_generation": "^", "proof_verification": "D"}
    linestyles = {"build_and_root": "-", "single_update_and_root": "--", "proof_generation": "-.", "proof_verification": ":"}
    fig, ax = plt.subplots(figsize=(3.35, 2.05))
    for operation, label in labels.items():
        frame = data[data.operation == operation].sort_values("clients")
        median = frame.wall_ms_median.to_numpy()
        upper = np.maximum(frame.wall_ms_p95.to_numpy() - median, 0)
        ax.errorbar(
            frame.clients,
            median,
            yerr=np.vstack([np.zeros_like(upper), upper]),
            marker=markers[operation],
            linestyle=linestyles[operation],
            capsize=2,
            label=label,
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks([10, 100, 500], labels=["10", "100", "500"])
    ax.set_xlabel("Number of FL clients")
    ax.set_ylabel("Off-chain wall time (ms)")
    ax.grid(True, which="major", linewidth=0.35, alpha=0.45)
    ax.legend(frameon=False, ncol=2, loc="upper left")
    save(fig, "contestfl_smt_offchain_latency")


def plot_flower() -> None:
    report = json.loads((REFERENCE / "flower_mnist" / "FLOWER_MNIST_E2E_REPORT.json").read_text())
    tx = pd.DataFrame(report["chain"]["transactions"])
    labels = ["Open round", "Submit C1", "Submit C2", "Decisions", "Faulty state", "Challenge", "REVISED", "Corrected state", "Finalize"]
    fig, ax = plt.subplots(figsize=(3.35, 2.25))
    bars = ax.barh(np.arange(len(tx)), tx.gasUsed / 1000.0)
    ax.set_yticks(np.arange(len(tx)), labels)
    ax.invert_yaxis()
    ax.set_xlabel("Gas used (thousands)")
    ax.grid(True, axis="x", linewidth=0.35, alpha=0.45)
    for bar, gas in zip(bars, tx.gasUsed):
        ax.text(bar.get_width() + 2, bar.get_y() + bar.get_height() / 2, f"{gas / 1000:.1f}", va="center", fontsize=6.2)
    ax.set_xlim(0, max(tx.gasUsed / 1000.0) * 1.2)
    save(fig, "contestfl_flower_revised_gas")


def main() -> None:
    plot_root("gas_median", "Total gas per round", "contestfl_root_gas")
    plot_root("calldata_median", "Total calldata (bytes)", "contestfl_root_calldata")
    plot_smt()
    plot_flower()
    print(f"Figures written to {OUTPUT}")


if __name__ == "__main__":
    main()
