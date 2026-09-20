#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether a benchmark tag is complete and valid")
    parser.add_argument("--file", required=True)
    parser.add_argument("--clients", required=True)
    parser.add_argument("--rounds", type=int, required=True)
    parser.add_argument("--scenarios", required=True)
    args = parser.parse_args()

    path = Path(args.file)
    clients = [x for x in args.clients.split(",") if x]
    scenarios = [x for x in args.scenarios.split(",") if x]
    expected = len(clients) * args.rounds * len(scenarios)
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(1)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    ok = len(rows) == expected and all(
        str(row.get("invariant_ok", "")).lower() == "true"
        and not str(row.get("error", "")).strip()
        for row in rows
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
