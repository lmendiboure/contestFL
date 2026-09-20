#!/usr/bin/env python3
"""Merge per-gas-limit bounded-contention result directories."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

try:
    from .bounded_gas_contention import summarize, write_csv, write_report
except ImportError:
    from bounded_gas_contention import summarize, write_csv, write_report  # type: ignore


def read_csv(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def convert(row: dict[str, object]) -> dict[str, object]:
    integer_fields = {
        "validators", "repetition", "flood_count", "resolver_parallelism",
        "block_gas_limit", "gas_price", "broadcast_parallelism", "alignment_block",
        "head_before_broadcast", "head_after_flood_broadcast", "honest_block",
        "honest_block_offset", "honest_blocks_after_first_flood", "honest_gas_used",
        "honest_status", "honest_block_gas_used", "honest_block_gas_limit",
        "first_flood_block", "last_flood_block", "flood_block_span",
        "flood_gas_total", "flood_calldata_total", "flood_in_honest_block",
    }
    float_fields = {
        "honest_delay_ms_configured", "alignment_delay_ms_configured",
        "flood_broadcast_ms", "honest_latency_ms", "honest_block_utilization",
    }
    bool_fields = {"probe_finalized", "attack_finalized", "invariant_ok"}
    converted: dict[str, object] = {}
    for key, value in row.items():
        text = str(value)
        if key in integer_fields:
            converted[key] = int(float(text))
        elif key in float_fields:
            converted[key] = float(text)
        elif key in bool_fields:
            converted[key] = text.strip().lower() in {"1", "true", "yes"}
        else:
            converted[key] = text
    return converted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir
    paths = sorted(run_dir.glob("gas_*/bounded_gas_contention_raw.csv"))
    if not paths:
        raise SystemExit(f"no per-limit raw files found under {run_dir}")
    rows: list[dict[str, object]] = []
    for path in paths:
        rows.extend(convert(row) for row in read_csv(path))
    write_csv(run_dir / "bounded_gas_contention_raw.csv", rows)
    summary = summarize(rows)  # type: ignore[arg-type]
    write_csv(run_dir / "bounded_gas_contention_summary.csv", summary)
    write_report(run_dir / "BOUNDED_GAS_CONTENTION_REPORT.md", summary)
    metadata = {
        "sources": [str(path.relative_to(run_dir)) for path in paths],
        "blockGasLimits": sorted({int(row["block_gas_limit"]) for row in rows}),
        "floodCounts": sorted({int(row["flood_count"]) for row in rows}),
        "rows": len(rows),
    }
    (run_dir / "bounded_gas_contention_merged_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
