#!/usr/bin/env python3
"""Create checksummed run manifest and archive of reviewer-specific output."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import zipfile
from pathlib import Path


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_version(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True,
                              timeout=15).stdout.strip()
    except Exception:
        return None


def build_manifest(root: Path, output: Path, profile: str) -> dict:
    if not output.is_relative_to(root):
        raise ValueError("output must be inside the repository")
    statuses = []
    for row in (output / "STAGE_STATUS.tsv").read_text().splitlines()[1:]:
        stage, status, epoch = row.split("\t")
        statuses.append({"stage": stage, "status": status, "epoch": epoch})
    # A resumed experiment may retain an earlier FAIL followed by a successful
    # retry of the same stage. Keep *every* attempt in the manifest, but assess
    # completeness from the latest status of each distinct stage.
    latest = {}
    for item in statuses:
        latest[item["stage"]] = item["status"]
    previous_failures = [item for item in statuses if item["status"].startswith("FAIL_")]
    files = []
    for f in sorted(output.rglob("*")):
        if f.is_file() and f.name != "REVIEW_RUN_MANIFEST.json":
            files.append({"file": str(f.relative_to(root)), "bytes": f.stat().st_size,
                          "sha256": sha(f)})
    source_files = []
    for folder in ("review", "bench", "contracts", "formal", "tests", "scripts", "tools"):
        for f in sorted((root / folder).rglob("*")):
            if f.is_file() and f.suffix in (".py", ".sol", ".sh"):
                source_files.append({"file": str(f.relative_to(root)), "sha256": sha(f)})
    return {
        "build_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "profile": profile, "completed_all_stages": bool(latest) and all(v == "PASS" for v in latest.values()),
        "stages": statuses,
        "latest_stage_status": latest,
        "prior_failed_attempts_retained": len(previous_failures),
        "repository_commit": run_version(["git", "rev-parse", "HEAD"]) if (root / ".git").is_dir() else None,
        "python_version": sys.version, "platform": platform.platform(),
        "docker_version": run_version(["docker", "--version"]),
        "docker_compose_version": run_version(["docker", "compose", "version"]),
        "source_files": source_files,
        "produced_files": files,
        "important_limitation": "Source archive is not a git checkout; source hashes substitute for a git commit when unavailable. Measured studies are same-host Besu; modeled WAN sensitivity is not direct WAN validation.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--profile", choices=("check", "smoke", "full", "focused", "causal", "extended"), required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (root / args.result_dir).resolve()
    if not output.is_dir():
        parser.error("results directory not found")
    manifest = build_manifest(root, output, args.profile)
    (output / "REVIEW_RUN_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    dest = output.with_suffix(".zip")
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(output.rglob("*")):
            if f.is_file():
                z.write(f, arcname=str(f.relative_to(output)))
    print(json.dumps({"archive": str(dest), "size_bytes": dest.stat().st_size,
                      "stages": len(manifest["stages"]),
                      "complete": manifest["completed_all_stages"]}, indent=2))


if __name__ == "__main__":
    main()
