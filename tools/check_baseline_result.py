#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a representative-baseline result file")
    parser.add_argument("--file", required=True)
    parser.add_argument("--clients", required=True)
    parser.add_argument("--rounds", type=int, required=True)
    parser.add_argument("--designs", required=True)
    parser.add_argument("--workloads", required=True)
    args = parser.parse_args()

    path = Path(args.file)
    expected = (
        len(split_csv(args.clients))
        * args.rounds
        * len(split_csv(args.designs))
        * len(split_csv(args.workloads))
    )
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(1)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    valid = len(rows) == expected and all(
        str(row.get("semantic_ok", "")).lower() == "true"
        and not str(row.get("error", "")).strip()
        for row in rows
    )
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
