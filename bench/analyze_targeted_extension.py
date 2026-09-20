#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def read_many(paths: Iterable[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(paths):
        if path.is_file() and path.stat().st_size:
            frame = pd.read_csv(path)
            frame["source_file"] = path.name
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def q1(series: pd.Series) -> float:
    return float(series.quantile(0.25))


def q3(series: pd.Series) -> float:
    return float(series.quantile(0.75))


def summarize(frame: pd.DataFrame, keys: list[str], columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    aggregations: dict[str, tuple[str, object]] = {"runs": (columns[0], "size")}
    for column in columns:
        aggregations[f"{column}_median"] = (column, "median")
        aggregations[f"{column}_q1"] = (column, q1)
        aggregations[f"{column}_q3"] = (column, q3)
        aggregations[f"{column}_min"] = (column, "min")
        aggregations[f"{column}_max"] = (column, "max")
    return frame.groupby(keys, dropna=False).agg(**aggregations).reset_index()


def normalize_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().eq("true")


def phase_class(phase: str) -> str:
    phase = str(phase)
    if phase in {"open", "submit", "decide", "publish_initial", "publish_state"}:
        return "Coordination"
    if phase == "challenge":
        return "Challenge"
    if phase in {"verify_evidence", "resolve"}:
        return "Resolution"
    if phase.startswith("replacement") or phase in {"terminal_replacement", "laundered_replacement"}:
        return "Replacement"
    if phase in {"fallback", "expire", "abort"}:
        return "Fallback/abort"
    if phase == "finalize":
        return "Finalization"
    return "Other"


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    if frame.empty:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze the final targeted ContestFL runs")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    run_dir = ROOT / args.run_dir
    raw = run_dir / "raw"
    run_dir.mkdir(parents=True, exist_ok=True)

    baseline_rounds = read_many(raw.glob("baseline_rounds_target_*_v*.csv"))
    contest_rounds = read_many(raw.glob("rounds_target_*_v*.csv"))
    baseline_txs = read_many(raw.glob("baseline_txs_target_*_v*.csv"))
    contest_txs = read_many(raw.glob("transactions_target_*_v*.csv"))

    failures: list[str] = []
    if not baseline_rounds.empty:
        bad = baseline_rounds[~normalize_bool(baseline_rounds["semantic_ok"])]
        if not bad.empty:
            failures.append(f"{len(bad)} baseline semantic failures")
    if not contest_rounds.empty:
        bad = contest_rounds[~normalize_bool(contest_rounds["invariant_ok"])]
        if not bad.empty:
            failures.append(f"{len(bad)} ContestFL invariant failures")

    # Clean-path scaling across the three principal design points.
    clean_base = baseline_rounds[
        (baseline_rounds.get("campaign_tag", pd.Series(dtype=str)) == "target_clean_scaling")
        & (baseline_rounds.get("workload", pd.Series(dtype=str)) == "clean")
    ].copy() if not baseline_rounds.empty else pd.DataFrame()
    if not clean_base.empty:
        clean_base["design_label"] = clean_base["design"].map(
            {"ledger_audit": "Audit-only", "eager_full": "Eager verification"}
        ).fillna(clean_base["design"])
        clean_base = clean_base.rename(columns={"offchain_verify_ms": "verification_ms"})

    clean_contest = contest_rounds[
        (contest_rounds.get("campaign_tag", pd.Series(dtype=str)) == "target_contestfl_clean_scaling")
        & (contest_rounds.get("scenario", pd.Series(dtype=str)) == "nominal")
    ].copy() if not contest_rounds.empty else pd.DataFrame()
    if not clean_contest.empty:
        clean_contest["design_label"] = "ContestFL"
        clean_contest["verification_ms"] = 0.0

    clean = pd.concat([clean_base, clean_contest], ignore_index=True, sort=False)
    clean_summary = summarize(
        clean,
        ["design_label", "validators", "clients"],
        ["gas_total", "calldata_bytes", "block_span", "total_ms", "verification_ms"],
    ) if not clean.empty else pd.DataFrame()
    write_csv(clean_summary, run_dir / "targeted_clean_scaling_summary.csv")

    # Amount of affected client-level state.
    affected = contest_rounds[
        contest_rounds.get("scenario", pd.Series(dtype=str)).eq("affected_decisions")
    ].copy() if not contest_rounds.empty else pd.DataFrame()
    affected_summary = summarize(
        affected,
        ["affected_decisions", "clients", "validators"],
        ["gas_total", "tx_count", "block_span", "total_ms", "challenge_count"],
    ) if not affected.empty else pd.DataFrame()
    write_csv(affected_summary, run_dir / "affected_decisions_summary.csv")

    # Repeated faulty replacements and bounded fallback.
    replacements = contest_rounds[
        contest_rounds.get("scenario", pd.Series(dtype=str)).eq("faulty_replacement_chain")
    ].copy() if not contest_rounds.empty else pd.DataFrame()
    if not replacements.empty:
        fallback_rounds: set[int] = set()
        if not contest_txs.empty:
            fallback_rounds = set(
                contest_txs.loc[contest_txs["phase"].eq("fallback"), "round_id"].astype(int)
            )
        replacements["fallback_used"] = replacements["round_id"].astype(int).isin(fallback_rounds)
    replacement_summary = summarize(
        replacements,
        ["faulty_replacements", "retry_budget", "fallback_used", "clients", "validators"],
        ["gas_total", "tx_count", "block_span", "total_ms", "retries_used", "challenge_count"],
    ) if not replacements.empty else pd.DataFrame()
    write_csv(replacement_summary, run_dir / "faulty_replacement_chain_summary.csv")

    # Flooding: resolution span starts at the final ChallengeOpened block.
    flooding = contest_rounds[
        contest_rounds.get("scenario", pd.Series(dtype=str)).eq("challenge_flooding")
    ].copy() if not contest_rounds.empty else pd.DataFrame()
    flooding_summary = summarize(
        flooding,
        ["flood_count", "flood_parallelism", "clients", "validators"],
        ["gas_total", "tx_count", "block_span", "resolution_block_span", "total_ms"],
    ) if not flooding.empty else pd.DataFrame()
    write_csv(flooding_summary, run_dir / "targeted_flooding_summary.csv")

    # Stable protocol-phase decomposition. Keep submission gas available as a
    # separate category so the plotting stage may show or de-emphasize it.
    phase_summary = pd.DataFrame()
    if not contest_txs.empty:
        contest_txs = contest_txs.copy()
        contest_txs["phase_class"] = contest_txs["phase"].map(phase_class)
        per_round_phase = (
            contest_txs.groupby(
                [
                    "campaign_tag", "scenario", "clients", "validators",
                    "round_id", "repetition", "phase_class",
                ],
                dropna=False,
            )
            .agg(
                tx_count=("tx_hash", "size"),
                gas_total=("gas_used", "sum"),
                calldata_bytes=("calldata_bytes", "sum"),
                first_block=("block_number", "min"),
                last_block=("block_number", "max"),
            )
            .reset_index()
        )
        phase_summary = (
            per_round_phase.groupby(
                ["campaign_tag", "scenario", "clients", "validators", "phase_class"],
                dropna=False,
            )
            .agg(
                runs=("round_id", "nunique"),
                tx_count_median=("tx_count", "median"),
                tx_count_q1=("tx_count", q1),
                tx_count_q3=("tx_count", q3),
                gas_total_median=("gas_total", "median"),
                gas_total_q1=("gas_total", q1),
                gas_total_q3=("gas_total", q3),
                calldata_bytes_median=("calldata_bytes", "median"),
            )
            .reset_index()
        )
    write_csv(phase_summary, run_dir / "targeted_phase_summary.csv")

    replay_path = run_dir / "replay_scaling_summary.csv"
    replay = pd.read_csv(replay_path) if replay_path.is_file() and replay_path.stat().st_size else pd.DataFrame()
    if not replay.empty:
        replay["artifact_mib"] = replay["artifact_bytes"] / (1024 * 1024)
        replay["update_kib"] = replay["update_bytes"] / 1024
        write_csv(replay, run_dir / "targeted_replay_summary.csv")

    report = [
        "# ContestFL targeted experimental extension",
        "",
        f"- Baseline rounds: **{len(baseline_rounds)}**",
        f"- ContestFL rounds: **{len(contest_rounds)}**",
        f"- Baseline transactions: **{len(baseline_txs)}**",
        f"- ContestFL transactions: **{len(contest_txs)}**",
        f"- Detected failures: **{'; '.join(failures) if failures else '0'}**",
        "",
        "## Generated summaries",
        "",
        "- `targeted_clean_scaling_summary.csv`",
        "- `affected_decisions_summary.csv`",
        "- `faulty_replacement_chain_summary.csv`",
        "- `targeted_flooding_summary.csv`",
        "- `targeted_phase_summary.csv`",
        "- `targeted_replay_summary.csv` when replay data are present",
        "",
        "## Interpretation constraints",
        "",
        "- The affected-decisions experiment varies the number of incorrect client-level admission decisions that jointly invalidate the aggregate; it does not create an artificial deeper FL dependency graph.",
        "- The replacement-chain experiment counts faulty coordinator replacements after the initially faulty state. At the retry budget, the resolver installs the terminal fallback.",
        "- Flooding resolution span is measured from the block containing the last opened challenge through finalization.",
        "- Gas and calldata are deterministic for identical calls. Block spans are discrete and host/ledger-configuration dependent.",
        "- Replay measures the in-memory deterministic aggregation kernel and excludes artifact retrieval, transfer, decryption, and deserialization.",
    ]
    (run_dir / "TARGETED_EXTENSION_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    metadata = {
        "baselineRounds": len(baseline_rounds),
        "contestflRounds": len(contest_rounds),
        "baselineTransactions": len(baseline_txs),
        "contestflTransactions": len(contest_txs),
        "failures": failures,
    }
    (run_dir / "targeted_analysis_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
