#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile")
    parser.add_argument("--config", default="config/campaign.yaml")
    args = parser.parse_args()
    config = yaml.safe_load((ROOT / args.config).read_text(encoding="utf-8"))
    try:
        profile = config["profiles"][args.profile]
    except KeyError as exc:
        raise SystemExit(f"unknown profile {args.profile!r}") from exc
    values = {
        "VALIDATOR_LIST": " ".join(str(item) for item in profile["validators"]),
        "CLIENTS": ",".join(str(item) for item in profile["clients"]),
        "ROUNDS": str(profile["rounds"]),
        "WARMUP": str(profile["warmup"]),
        "SCENARIOS": ",".join(profile["scenarios"]),
    }
    for key, value in values.items():
        print(f"{key}={shlex.quote(value)}")


if __name__ == "__main__":
    main()
