#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


def command_output(command: Sequence[str]) -> dict[str, object]:
    executable = shutil.which(command[0])
    if executable is None:
        return {"available": False, "command": list(command), "output": None}
    try:
        completed = subprocess.run(
            list(command), check=False, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=60,
        )
        return {
            "available": True,
            "command": list(command),
            "returnCode": completed.returncode,
            "output": completed.stdout.strip(),
        }
    except Exception as exc:  # pragma: no cover - environment-dependent
        return {"available": True, "command": list(command), "error": repr(exc)}


def read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-run-id", required=True)
    parser.add_argument("--suite", required=True)
    args = parser.parse_args()

    payload = {
        "capturedAtUtc": datetime.now(timezone.utc).isoformat(),
        "baseRunId": args.base_run_id,
        "suite": args.suite,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "hostname": platform.node(),
            "cpuCount": os.cpu_count(),
            "meminfo": read_text("/proc/meminfo"),
            "cpuinfo": read_text("/proc/cpuinfo"),
        },
        "commands": {
            "dockerVersion": command_output(["docker", "version"]),
            "dockerComposeVersion": command_output(["docker", "compose", "version"]),
            "dockerInfo": command_output(["docker", "info"]),
            "javaVersion": command_output(["java", "-version"]),
            "gitVersion": command_output(["git", "--version"]),
            "gitRevision": command_output(["git", "rev-parse", "HEAD"]),
            "gitStatus": command_output(["git", "status", "--short"]),
            "uname": command_output(["uname", "-a"]),
            "lscpu": command_output(["lscpu"]),
            "df": command_output(["df", "-h", "."]),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
