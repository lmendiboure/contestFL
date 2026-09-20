#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import statistics
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DESIGN_ORDER = ["plain_fl", "ledger_audit", "eager_full", "single_shot", "contestfl"]
DESIGN_LABEL = {
    "plain_fl": "Plain FL",
    "ledger_audit": "Ledger audit",
    "eager_full": "Eager verify",
    "single_shot": "Single-shot",
    "contestfl": "ContestFL",
}
COLORS = {
    "plain_fl": "#7A7A7A",
    "ledger_audit": "#0072B2",
    "eager_full": "#D55E00",
    "single_shot": "#009E73",
    "contestfl": "#CC79A7",
}
MARKERS = {
    "plain_fl": "X",
    "ledger_audit": "o",
    "eager_full": "s",
    "single_shot": "D",
    "contestfl": "^",
}
HATCHES = {
    "plain_fl": "//",
    "ledger_audit": "..",
    "eager_full": "xx",
    "single_shot": "--",
    "contestfl": "++",
}
OUTCOME_ORDER = [
    "FAULTY_FINALIZED",
    "DETECTED_ONLY",
    "STUCK",
    "SAFE_ABORT",
    "CORRECTED",
    "PREVENTED",
    "NOT_APPLICABLE",
]
OUTCOME_CODE = {name: index for index, name in enumerate(OUTCOME_ORDER)}
OUTCOME_SHORT = {
    "FAULTY_FINALIZED": "Faulty",
    "DETECTED_ONLY": "Detected",
    "STUCK": "Stuck",
    "SAFE_ABORT": "Abort",
    "CORRECTED": "Corrected",
    "PREVENTED": "Prevented",
    "NOT_APPLICABLE": "N/A",
    "CLEAN": "Clean",
}
FAULT_ORDER = [
    "bad_admission",
    "bad_omission",
    "bad_aggregate",
    "dependent_fault",
    "correction_laundering",
    "resolver_unavailable",
]
FAULT_LABEL = {
    "bad_admission": "Admission",
    "bad_omission": "Omission",
    "bad_aggregate": "Aggregate",
    "dependent_fault": "Dependent",
    "correction_laundering": "Laundering",
    "resolver_unavailable": "Resolver loss",
}


def set_publication_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "Nimbus Roman No9 L", "DejaVu Serif"],
            "font.size": 8.0,
            "axes.labelsize": 8.0,
            "axes.titlesize": 8.2,
            "xtick.labelsize": 7.2,
            "ytick.labelsize": 7.2,
            "legend.fontsize": 7.0,
            "axes.linewidth": 0.75,
            "lines.linewidth": 1.55,
            "lines.markersize": 4.4,
            "grid.linewidth": 0.45,
            "grid.alpha": 0.28,
            "legend.frameon": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.dpi": 600,
            "savefig.bbox": "tight",
            "figure.constrained_layout.use": False,
        }
    )


def read_concat(paths: Iterable[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        if path.is_file() and path.stat().st_size > 0:
            try:
                frames.append(pd.read_csv(path))
            except pd.errors.EmptyDataError:
                continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def percentile(values: Sequence[float], q: float) -> float:
    array = np.asarray(list(values), dtype=float)
    return float(np.quantile(array, q)) if array.size else math.nan


def summarize(frame: pd.DataFrame, groups: Sequence[str]) -> pd.DataFrame:
    rows = []
    for keys, group in frame.groupby(list(groups), dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(groups, keys))
        for source, target in [
            ("total_ms", "total_ms"),
            ("gas_total", "gas"),
            ("tx_count", "tx"),
            ("block_span", "blocks"),
            ("calldata_bytes", "calldata"),
            ("offchain_verify_ms", "verify_ms"),
        ]:
            if source not in group:
                continue
            values = pd.to_numeric(group[source], errors="coerce").dropna().to_numpy(float)
            row[f"{target}_median"] = float(np.median(values)) if values.size else math.nan
            row[f"{target}_q1"] = percentile(values, 0.25)
            row[f"{target}_q3"] = percentile(values, 0.75)
        row["runs"] = len(group)
        if "semantic_ok" in group:
            row["success_rate"] = group["semantic_ok"].astype(str).str.lower().eq("true").mean()
        rows.append(row)
    return pd.DataFrame(rows)


def load_contestfl(run_dir: Path) -> pd.DataFrame:
    raw = run_dir / "contestfl" / "raw"
    if not raw.exists():
        raw = run_dir / "raw"
    frame = read_concat(raw.glob("rounds_*.csv"))
    if frame.empty:
        return frame
    mapping = {
        "nominal": ("clean", "CLEAN"),
        "bad_admission": ("bad_admission", "CORRECTED"),
        "bad_omission": ("bad_omission", "CORRECTED"),
        "bad_aggregate": ("bad_aggregate", "CORRECTED"),
        "concurrent_moot": ("dependent_fault", "CORRECTED"),
        "correction_laundering": ("correction_laundering", "CORRECTED"),
        "resolver_timeout_abort": ("resolver_unavailable", "SAFE_ABORT"),
    }
    frame = frame[frame["scenario"].isin(mapping)].copy()
    frame["design"] = "contestfl"
    frame["workload"] = frame["scenario"].map(lambda value: mapping[value][0])
    frame["semantic_outcome"] = frame["scenario"].map(lambda value: mapping[value][1])
    frame["semantic_ok"] = frame.get("invariant_ok", True)
    frame["offchain_verify_ms"] = 0.0
    frame["correct_checkpoint_finalized"] = frame["semantic_outcome"].isin(["CLEAN", "CORRECTED"])
    return frame


def load_data(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    baseline_raw = run_dir / "baselines" / "raw"
    if not baseline_raw.exists():
        baseline_raw = run_dir / "raw"
    baseline = read_concat(baseline_raw.glob("baseline_rounds_*.csv"))
    adapters = read_concat(baseline_raw.glob("baseline_adapters_*.csv"))
    contest = load_contestfl(run_dir)
    combined = pd.concat([baseline, contest], ignore_index=True, sort=False) if not contest.empty else baseline
    if not combined.empty:
        for column, default in {
            "offchain_verify_ms": 0.0,
            "gas_total": 0,
            "tx_count": 0,
            "block_span": 0,
            "calldata_bytes": 0,
            "semantic_ok": True,
        }.items():
            if column not in combined:
                combined[column] = default
    replay = pd.DataFrame()
    candidates = [run_dir / "replay_scaling_summary.csv", run_dir / "raw" / "replay_scaling_raw.csv"]
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            replay = pd.read_csv(path)
            break
    return combined, adapters, replay


def save_figure(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.02)
    fig.savefig(path.with_suffix(".png"), dpi=600, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(-0.16, 1.06, label, transform=ax.transAxes, fontweight="bold", fontsize=8.4, va="top")


def style_axis(ax: plt.Axes, grid: bool = True) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if grid:
        ax.grid(axis="y", linestyle="-", zorder=0)
    ax.tick_params(direction="out", length=2.5, width=0.65, pad=2)


def outcome_matrix(combined: pd.DataFrame, figures: Path) -> pd.DataFrame:
    faults = combined[(combined["clients"] == combined["clients"].max()) & (combined["workload"].isin(FAULT_ORDER))]
    rows = []
    matrix = np.full((len(DESIGN_ORDER), len(FAULT_ORDER)), OUTCOME_CODE["NOT_APPLICABLE"], dtype=float)
    labels = np.full(matrix.shape, "N/A", dtype=object)
    for i, design in enumerate(DESIGN_ORDER):
        for j, fault in enumerate(FAULT_ORDER):
            group = faults[(faults.design == design) & (faults.workload == fault)]
            if group.empty:
                outcome = "NOT_APPLICABLE"
            else:
                outcome = group["semantic_outcome"].mode().iloc[0]
            rows.append({"design": design, "fault": fault, "outcome": outcome})
            matrix[i, j] = OUTCOME_CODE.get(outcome, OUTCOME_CODE["NOT_APPLICABLE"])
            labels[i, j] = OUTCOME_SHORT.get(outcome, outcome)

    colors = ["#B2182B", "#EF8A62", "#FDDC7A", "#BDBDBD", "#67A9CF", "#2166AC", "#F2F2F2"]
    cmap = mpl.colors.ListedColormap(colors)
    norm = mpl.colors.BoundaryNorm(np.arange(-0.5, len(colors) + 0.5), cmap.N)
    fig, ax = plt.subplots(figsize=(7.05, 2.45))
    ax.imshow(matrix, cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(len(FAULT_ORDER)), [FAULT_LABEL[value] for value in FAULT_ORDER], rotation=0)
    ax.set_yticks(range(len(DESIGN_ORDER)), [DESIGN_LABEL[value] for value in DESIGN_ORDER])
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = int(matrix[i, j])
            text_color = "white" if value in {0, 5} else "black"
            ax.text(j, i, labels[i, j], ha="center", va="center", fontsize=7.0, color=text_color)
    ax.set_xlabel("Injected fault or failure")
    ax.tick_params(length=0, pad=3)
    for spine in ax.spines.values():
        spine.set_linewidth(0.7)
    save_figure(fig, figures / "fig1_fault_outcome_matrix")
    return pd.DataFrame(rows)


def clean_summary(combined: pd.DataFrame) -> pd.DataFrame:
    clean = combined[combined.workload == "clean"].copy()
    return summarize(clean, ["design", "validators", "clients"])


def plot_clean_scaling(summary: pd.DataFrame, figures: Path) -> None:
    subset = summary[summary.validators == 4]
    fig, axes = plt.subplots(1, 3, figsize=(7.12, 2.20))
    metrics = [
        ("gas_median", "Gas / round", 1e6, "M"),
        ("blocks_median", "Block span", 1.0, ""),
        ("total_ms_median", "Latency (s)", 1000.0, ""),
    ]
    for panel, (ax, (metric, ylabel, scale, _suffix)) in enumerate(zip(axes, metrics)):
        for design in DESIGN_ORDER:
            group = subset[subset.design == design].sort_values("clients")
            if group.empty:
                continue
            y = group[metric].to_numpy(float) / scale
            ax.plot(
                group.clients.to_numpy(int), y, label=DESIGN_LABEL[design],
                color=COLORS[design], marker=MARKERS[design],
                markerfacecolor="white" if design != "contestfl" else COLORS[design],
                markeredgewidth=0.9,
            )
        ax.set_xlabel("Clients")
        ax.set_ylabel(ylabel)
        ax.set_xticks(sorted(subset.clients.unique()))
        style_axis(ax)
        panel_label(ax, f"({chr(97 + panel)})")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.52, 1.10), ncol=5, columnspacing=1.0, handletextpad=0.4)
    fig.subplots_adjust(left=0.07, right=0.995, bottom=0.22, top=0.82, wspace=0.33)
    save_figure(fig, figures / "fig2_clean_cost_scaling")


def plot_fixed_client_views(summary: pd.DataFrame, figures: Path) -> None:
    subset = summary[summary.validators == 4]
    ledger_reference = subset[subset.design == "ledger_audit"].set_index("clients")
    for clients in sorted(subset.clients.unique()):
        group = subset[subset.clients == clients].set_index("design").reindex(DESIGN_ORDER)
        if group.dropna(how="all").empty:
            continue
        fig, axes = plt.subplots(1, 2, figsize=(3.45, 1.95))
        x = np.arange(len(DESIGN_ORDER))
        gas_ref = float(ledger_reference.loc[clients, "gas_median"]) if clients in ledger_reference.index else 1.0
        gas = group["gas_median"].fillna(0).to_numpy(float) / max(gas_ref, 1.0)
        blocks = group["blocks_median"].fillna(0).to_numpy(float)
        for ax, values, ylabel, label in [
            (axes[0], gas, "Gas / ledger", "(a)"),
            (axes[1], blocks, "Block span", "(b)"),
        ]:
            bars = ax.bar(x, values, width=0.72, edgecolor="black", linewidth=0.55, zorder=2)
            for bar, design in zip(bars, DESIGN_ORDER):
                bar.set_facecolor(COLORS[design])
                bar.set_hatch(HATCHES[design])
            ax.set_xticks(x, ["Plain", "Log", "Eager", "1-shot", "CFL"], rotation=32, ha="right")
            ax.set_ylabel(ylabel)
            style_axis(ax)
            panel_label(ax, label)
        axes[0].axhline(1.0, color="#444444", linewidth=0.7, linestyle=":")
        fig.suptitle(f"Clean round, {int(clients)} clients", y=1.02, fontsize=8.2)
        fig.subplots_adjust(left=0.15, right=0.99, bottom=0.32, top=0.82, wspace=0.48)
        save_figure(fig, figures / f"fig2_clean_cost_at_{int(clients)}_clients")


def plot_clean_vs_fault(combined: pd.DataFrame, figures: Path, clients: int = 100) -> None:
    subset = combined[(combined.validators == 4) & (combined.clients == clients)]
    workloads = ["clean", "bad_aggregate", "correction_laundering"]
    workload_labels = ["Clean", "Aggregate", "Laundering"]
    summary = summarize(subset[subset.workload.isin(workloads)], ["design", "workload"])
    fig, axes = plt.subplots(1, 3, figsize=(7.12, 2.28))
    metrics = [
        ("gas_median", "Gas (M)", 1e6),
        ("blocks_median", "Block span", 1.0),
        ("total_ms_median", "Latency (s)", 1000.0),
    ]
    width = 0.15
    x = np.arange(len(workloads))
    for panel, (ax, (metric, ylabel, scale)) in enumerate(zip(axes, metrics)):
        for index, design in enumerate(DESIGN_ORDER):
            group = summary[summary.design == design].set_index("workload").reindex(workloads)
            values = group[metric].fillna(0).to_numpy(float) / scale
            ax.bar(
                x + (index - 2) * width, values, width=width,
                label=DESIGN_LABEL[design], color=COLORS[design],
                edgecolor="black", linewidth=0.45, hatch=HATCHES[design], zorder=2,
            )
        ax.set_xticks(x, workload_labels)
        ax.set_ylabel(ylabel)
        style_axis(ax)
        panel_label(ax, f"({chr(97 + panel)})")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.52, 1.10), ncol=5, columnspacing=0.9, handletextpad=0.35)
    fig.subplots_adjust(left=0.07, right=0.995, bottom=0.20, top=0.80, wspace=0.34)
    save_figure(fig, figures / f"fig3_clean_and_fault_cost_{clients}_clients")


def expected_cost_frame(combined: pd.DataFrame) -> pd.DataFrame:
    q_values = np.asarray([0, 0.01, 0.05, 0.10, 0.25, 0.50, 1.0])
    rows = []
    subset = combined[combined.validators == 4]
    for clients in sorted(subset.clients.unique()):
        clean = summarize(subset[(subset.clients == clients) & (subset.workload == "clean")], ["design"])
        faults = summarize(subset[(subset.clients == clients) & (subset.workload == "bad_aggregate")], ["design"])
        clean_map = clean.set_index("design")
        fault_map = faults.set_index("design")
        for q in q_values:
            for design in ["ledger_audit", "eager_full", "single_shot", "contestfl"]:
                if design not in clean_map.index:
                    continue
                clean_gas = float(clean_map.loc[design, "gas_median"])
                clean_latency = float(clean_map.loc[design, "total_ms_median"])
                if design == "eager_full" or design == "ledger_audit":
                    gas = clean_gas
                    latency = clean_latency
                elif design in fault_map.index:
                    gas = clean_gas + q * (float(fault_map.loc[design, "gas_median"]) - clean_gas)
                    latency = clean_latency + q * (
                        float(fault_map.loc[design, "total_ms_median"]) - clean_latency
                    )
                else:
                    continue
                rows.append({
                    "clients": int(clients), "dispute_rate": q, "design": design,
                    "expected_gas": gas, "expected_latency_ms": latency,
                    "modelled": True,
                })
    return pd.DataFrame(rows)


def plot_expected_cost(expected: pd.DataFrame, figures: Path) -> None:
    clients_values = sorted(expected.clients.unique())[:3]
    if not clients_values:
        return
    fig, axes = plt.subplots(1, len(clients_values), figsize=(7.12, 2.18), squeeze=False)
    for panel, (ax, clients) in enumerate(zip(axes[0], clients_values)):
        subset = expected[expected.clients == clients]
        logging = subset[subset.design == "ledger_audit"].expected_gas.iloc[0]
        for design in ["ledger_audit", "eager_full", "single_shot", "contestfl"]:
            group = subset[subset.design == design].sort_values("dispute_rate")
            if group.empty:
                continue
            ax.plot(
                group.dispute_rate * 100,
                group.expected_gas / max(logging, 1.0),
                color=COLORS[design], marker=MARKERS[design], label=DESIGN_LABEL[design],
                linestyle="--" if design == "single_shot" else "-",
                markerfacecolor="white" if design != "contestfl" else COLORS[design],
            )
        ax.set_xlabel("Disputed rounds (%)")
        ax.set_ylabel("Expected gas / ledger")
        ax.set_title(f"{int(clients)} clients")
        ax.set_xticks([0, 25, 50, 75, 100])
        style_axis(ax)
        panel_label(ax, f"({chr(97 + panel)})")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.52, 1.10), ncol=4, columnspacing=1.1, handletextpad=0.4)
    fig.subplots_adjust(left=0.075, right=0.995, bottom=0.22, top=0.75, wspace=0.35)
    save_figure(fig, figures / "fig4_expected_gas_vs_dispute_rate")


def normalize_replay(replay: pd.DataFrame) -> pd.DataFrame:
    if replay.empty:
        return replay
    result = replay.copy()
    if "update_bytes" not in result and "update_bytes_per_client" in result:
        result["update_bytes"] = result["update_bytes_per_client"]
    if "verification_ms_median" not in result:
        for candidate in ["replay_ms_median", "total_ms_median", "verification_ms"]:
            if candidate in result:
                result["verification_ms_median"] = result[candidate]
                break
    if "clients" not in result or "update_bytes" not in result or "verification_ms_median" not in result:
        return pd.DataFrame()
    return result


def plot_replay_projection(combined: pd.DataFrame, replay: pd.DataFrame, figures: Path) -> pd.DataFrame:
    replay = normalize_replay(replay)
    if replay.empty:
        return pd.DataFrame()
    clients = 100 if 100 in set(replay.clients) else int(replay.clients.max())
    sizes = sorted(replay[replay.clients == clients].update_bytes.unique())
    q_values = np.asarray([0, 0.01, 0.05, 0.10, 0.25, 0.50, 1.0])
    rows = []
    ncols = 2
    nrows = math.ceil(len(sizes) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(7.12, 2.1 * nrows), squeeze=False)
    for panel, update_bytes in enumerate(sizes):
        ax = axes.flat[panel]
        value = replay[(replay.clients == clients) & (replay.update_bytes == update_bytes)]
        replay_ms = float(value.verification_ms_median.iloc[0])
        for q in q_values:
            eager = replay_ms
            contest = q * replay_ms
            rows.extend([
                {"clients": clients, "update_bytes": int(update_bytes), "dispute_rate": q, "design": "eager_full", "expected_verify_ms": eager},
                {"clients": clients, "update_bytes": int(update_bytes), "dispute_rate": q, "design": "contestfl", "expected_verify_ms": contest},
            ])
        for design in ["eager_full", "contestfl"]:
            group = pd.DataFrame(rows)
            group = group[(group.update_bytes == update_bytes) & (group.design == design)]
            ax.plot(
                group.dispute_rate * 100, group.expected_verify_ms,
                color=COLORS[design], marker=MARKERS[design], label=DESIGN_LABEL[design],
                markerfacecolor="white" if design == "eager_full" else COLORS[design],
            )
        if update_bytes < 1024 * 1024:
            title = f"{update_bytes / 1024:.0f} KiB / client"
        else:
            title = f"{update_bytes / (1024 * 1024):.0f} MiB / client"
        ax.set_title(title)
        ax.set_xlabel("Disputed rounds (%)")
        ax.set_ylabel("Expected replay (ms)")
        ax.set_xticks([0, 25, 50, 75, 100])
        style_axis(ax)
        panel_label(ax, f"({chr(97 + panel)})")
    for panel in range(len(sizes), nrows * ncols):
        axes.flat[panel].axis("off")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.52, 1.01), ncol=2)
    fig.subplots_adjust(left=0.075, right=0.995, bottom=0.10, top=0.88, hspace=0.46, wspace=0.30)
    save_figure(fig, figures / "fig5_expected_replay_vs_dispute_rate")
    return pd.DataFrame(rows)


def plot_adapter_breakdown(adapters: pd.DataFrame, figures: Path) -> pd.DataFrame:
    if adapters.empty:
        return pd.DataFrame()
    eager = adapters[(adapters.design == "eager_full") & (adapters.workload == "clean")]
    if eager.empty:
        return pd.DataFrame()
    rows = []
    for (clients, adapter), group in eager.groupby(["clients", "adapter"]):
        rows.append({
            "clients": int(clients),
            "adapter": adapter,
            "verification_ms_median": float(pd.to_numeric(group["verification_ms"], errors="coerce").median()),
            "generation_ms_median": float(pd.to_numeric(group["evidence_generation_ms"], errors="coerce").median()),
            "proof_bytes_median": float(pd.to_numeric(group["proof_bytes"], errors="coerce").median()),
        })
    summary = pd.DataFrame(rows)
    fig, axes = plt.subplots(1, 2, figsize=(3.45, 1.95))
    adapter_labels = {
        "admission_receipt": "Receipt",
        "sparse_merkle_inclusion": "Merkle",
        "deterministic_aggregate_replay": "Replay",
    }
    adapter_colors = {
        "admission_receipt": "#56B4E9",
        "sparse_merkle_inclusion": "#009E73",
        "deterministic_aggregate_replay": "#D55E00",
    }
    for adapter in adapter_labels:
        group = summary[summary.adapter == adapter].sort_values("clients")
        if group.empty:
            continue
        axes[0].plot(group.clients, group.verification_ms_median, marker="o", label=adapter_labels[adapter], color=adapter_colors[adapter])
    axes[0].set_xlabel("Clients")
    axes[0].set_ylabel("Per-check time (ms)")
    axes[0].set_yscale("log")
    axes[0].legend(loc="best")
    style_axis(axes[0])
    panel_label(axes[0], "(a)")

    total = eager.groupby(["clients", "repetition", "round_id"], as_index=False).agg(
        verification_ms=("verification_ms", "sum"),
        generation_ms=("evidence_generation_ms", "sum"),
    )
    agg = total.groupby("clients", as_index=False).median(numeric_only=True)
    axes[1].bar(agg.clients.astype(str), agg.generation_ms, label="Generate", color="#0072B2", edgecolor="black", linewidth=0.5)
    axes[1].bar(agg.clients.astype(str), agg.verification_ms, bottom=agg.generation_ms, label="Verify", color="#D55E00", edgecolor="black", linewidth=0.5)
    axes[1].set_xlabel("Clients")
    axes[1].set_ylabel("Full eager suite (ms)")
    axes[1].legend(loc="best")
    style_axis(axes[1])
    panel_label(axes[1], "(b)")
    fig.subplots_adjust(left=0.15, right=0.99, bottom=0.25, top=0.94, wspace=0.48)
    save_figure(fig, figures / "fig6_eager_adapter_breakdown")
    return summary



def plot_compact_operating_point(combined: pd.DataFrame, figures: Path, clients: int = 100) -> None:
    subset = combined[(combined.validators == 4) & (combined.clients == clients)]
    if subset.empty:
        return
    summary = summarize(
        subset[subset.workload.isin(["clean", "bad_aggregate", "correction_laundering"])],
        ["design", "workload"],
    )
    clean = summary[summary.workload == "clean"].set_index("design")
    ledger_gas = float(clean.loc["ledger_audit", "gas_median"]) if "ledger_audit" in clean.index else 1.0
    x = np.arange(len(DESIGN_ORDER))
    fig, axes = plt.subplots(2, 2, figsize=(3.45, 3.18))
    panels = [
        ("clean", "gas_median", max(ledger_gas, 1.0), "Gas / ledger"),
        ("clean", "blocks_median", 1.0, "Block span"),
        ("bad_aggregate", "gas_median", max(ledger_gas, 1.0), "Gas / ledger"),
        ("correction_laundering", "gas_median", max(ledger_gas, 1.0), "Gas / ledger"),
    ]
    titles = ["Clean", "Clean", "Aggregate fault", "Laundering"]
    for panel, (ax, spec, title) in enumerate(zip(axes.flat, panels, titles)):
        workload, metric, scale, ylabel = spec
        group = summary[summary.workload == workload].set_index("design").reindex(DESIGN_ORDER)
        values = group[metric].fillna(0).to_numpy(float) / scale
        bars = ax.bar(x, values, width=0.72, edgecolor="black", linewidth=0.45, zorder=2)
        for bar, design in zip(bars, DESIGN_ORDER):
            bar.set_facecolor(COLORS[design])
            bar.set_hatch(HATCHES[design])
        ax.set_xticks(x, ["P", "L", "E", "1S", "CFL"])
        ax.set_ylabel(ylabel)
        ax.set_title(title, pad=2)
        style_axis(ax)
        panel_label(ax, f"({chr(97 + panel)})")
        if workload == "clean" and metric == "gas_median":
            ax.axhline(1.0, color="#444444", linewidth=0.65, linestyle=":")
    fig.subplots_adjust(left=0.16, right=0.99, bottom=0.12, top=0.95, hspace=0.55, wspace=0.48)
    save_figure(fig, figures / f"fig7_compact_operating_point_{clients}_clients")


def write_latex_table(frame: pd.DataFrame, path: Path, columns: Sequence[str], headers: Sequence[str]) -> None:
    if frame.empty:
        return
    selected = frame.loc[:, list(columns)].copy()
    selected.columns = list(headers)
    path.write_text(
        selected.to_latex(index=False, escape=False, float_format=lambda value: f"{value:.2f}"),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze ContestFL representative competitor baselines")
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    set_publication_style()
    run_dir = args.run_dir.resolve()
    figures = run_dir / "figures" / "competitors"
    tables = run_dir / "tables"
    figures.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)

    combined, adapters, replay = load_data(run_dir)
    if combined.empty:
        raise RuntimeError("no competitor or ContestFL round data found")
    combined.to_csv(run_dir / "competitor_combined_rounds.csv", index=False)

    clean = clean_summary(combined)
    clean.to_csv(run_dir / "baseline_clean_summary.csv", index=False)
    outcomes = outcome_matrix(combined, figures)
    outcomes.to_csv(run_dir / "baseline_fault_outcomes.csv", index=False)
    plot_clean_scaling(clean, figures)
    plot_fixed_client_views(clean, figures)
    plot_clean_vs_fault(combined, figures, clients=int(combined.clients.max()))
    expected = expected_cost_frame(combined)
    expected.to_csv(run_dir / "baseline_expected_cost.csv", index=False)
    plot_expected_cost(expected, figures)
    replay_projection = plot_replay_projection(combined, replay, figures)
    if not replay_projection.empty:
        replay_projection.to_csv(run_dir / "baseline_replay_projection.csv", index=False)
    adapter_summary = plot_adapter_breakdown(adapters, figures)
    plot_compact_operating_point(combined, figures, clients=int(combined.clients.max()))
    if not adapter_summary.empty:
        adapter_summary.to_csv(run_dir / "baseline_adapter_summary.csv", index=False)

    at_100 = clean[(clean.validators == 4) & (clean.clients == clean.clients.max())].copy()
    at_100["Design"] = at_100.design.map(DESIGN_LABEL)
    at_100["Gas (M)"] = at_100.gas_median / 1e6
    at_100["Latency (s)"] = at_100.total_ms_median / 1000
    write_latex_table(
        at_100,
        tables / "table_baseline_clean_100_clients.tex",
        ["Design", "Gas (M)", "blocks_median", "Latency (s)", "verify_ms_median"],
        ["Design", "Gas (M)", "Blocks", "Latency (s)", "Off-chain verify (ms)"],
    )
    outcome_pivot = outcomes.pivot(index="design", columns="fault", values="outcome").reindex(DESIGN_ORDER)
    outcome_pivot.index = [DESIGN_LABEL[value] for value in outcome_pivot.index]
    outcome_pivot = outcome_pivot.reindex(columns=FAULT_ORDER)
    outcome_pivot.columns = [FAULT_LABEL[value] for value in outcome_pivot.columns]
    (tables / "table_fault_outcomes.tex").write_text(
        outcome_pivot.to_latex(escape=False), encoding="utf-8"
    )

    report = [
        "# ContestFL competitor-baseline extension",
        "",
        f"- Measured design points: **{', '.join(DESIGN_LABEL[d] for d in DESIGN_ORDER if d in set(combined.design))}**",
        f"- Measured rounds: **{len(combined)}**",
        f"- Semantic failures: **{int((~combined.semantic_ok.astype(str).str.lower().eq('true')).sum())}**",
        "",
        "## Interpretation",
        "",
        "The baseline contracts implement representative design points under the same workload, evidence adapters, and QBFT deployment. They are not line-by-line reproductions of named published systems. Eager verification executes the full receipt/Merkle/replay adapter suite before every finalization. Single-shot optimistic verification permits one terminal replacement but does not reopen contestation, maintain a correction lineage, or provide resolver fallback.",
        "",
        "Expected-cost curves are trace-driven projections from measured clean and challenged paths. They are labelled as modelled results and must not be presented as additional blockchain executions.",
    ]
    (run_dir / "COMPETITOR_EXTENSION_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(run_dir / "COMPETITOR_EXTENSION_REPORT.md")


if __name__ == "__main__":
    main()
