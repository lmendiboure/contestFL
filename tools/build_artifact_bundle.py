#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_PARTS = {
    ".git", ".cache", "artifacts", "results", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules",
}
EXCLUDED_NAMES = {".env"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def include_source(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.name in EXCLUDED_NAMES or path.suffix in {".pyc", ".pyo"}:
        return False
    if relative.parts[:2] == ("ml", "cache"):
        return False
    if relative.parts and relative.parts[0] == "network" and any(
        part in {"data", "nodes", "generated", "runtime", "work", "secrets"}
        for part in relative.parts[1:]
    ):
        return False
    return True


def make_source_archive(root: Path, destination: Path) -> None:
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and include_source(path, root):
                archive.add(path, arcname=Path("contestfl-source") / path.relative_to(root))


def copy_if_present(source: Path, destination: Path) -> bool:
    if not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--base-run-id", required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--release-dir", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    release = Path(args.release_dir).resolve()
    bundles = release / "experiment-bundles"
    reports = release / "selected-reports"
    release.mkdir(parents=True, exist_ok=True)
    bundles.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    run_root = root / "results" / "runs"
    run_dirs = sorted(
        path for path in run_root.glob(f"{args.base_run_id}*") if path.is_dir()
    )
    copied_runs: list[dict[str, object]] = []
    report_names = {
        "REPORT.md", "COMPETITOR_EXTENSION_REPORT.md", "TARGETED_EXTENSION_REPORT.md",
        "ROOT_ONLY_ABLATION_REPORT.md", "MERKLE_GAS_AUDIT.md",
        "NETWORK_SMOKE_REPORT.md", "SMT_OFFCHAIN_REPORT.md", "ROOT_DEPTH_SENSITIVITY_REPORT.md", "TLC_RESULTS.md",
        "FLOWER_MNIST_E2E_REPORT.md", "WATCHER_PIPELINE_REPORT.md",
        "C1_COST_REPORT.md", "BOUNDED_GAS_CONTENTION_REPORT.md", "DAG_EXHAUSTIVE_REPORT.md",
    }

    for run_dir in run_dirs:
        archive = run_dir.with_suffix(".zip")
        if not archive.is_file():
            shutil.make_archive(str(run_dir), "zip", root_dir=run_dir)
        target = bundles / archive.name
        shutil.copy2(archive, target)
        selected: list[str] = []
        for path in run_dir.rglob("*"):
            if path.is_file() and (path.name in report_names or path.suffix in {".json", ".csv"} and path.name in {
                "TLC_RESULTS.json", "MERKLE_GAS_AUDIT.json", "FLOWER_MNIST_E2E_REPORT.json",
                "root_only_ablation_summary.csv", "root_only_ablation_comparison.csv",
                "network_smoke_summary.csv", "smt_offchain_summary.csv", "root_depth_sensitivity_summary.csv",
                "watcher_pipeline_summary.csv", "watcher_cost_projection.csv",
                "c1_cost_model.csv", "bounded_gas_contention_summary.csv", "recovery_feature_ablation.csv", "dag_exhaustive_results.csv",
            }):
                rel = path.relative_to(run_dir)
                dst = reports / run_dir.name / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dst)
                selected.append(str(rel))
        copied_runs.append({
            "runId": run_dir.name,
            "archive": str(target.relative_to(release)),
            "archiveSha256": sha256_file(target),
            "selectedReports": selected,
        })

    source_archive = release / "contestfl-source.tar.gz"
    make_source_archive(root, source_archive)

    for path in [
        root / "supplementary" / "contestfl_supplement.tex",
        root / "supplementary" / "ROOT_ONLY_SPECIFICATION.tex",
        root / "formal" / "ContestFL.tla",
        root / "formal" / "MC_Coverage.cfg",
        root / "formal" / "MC_Structural.cfg",
        root / "README.md",
        root / "ARTIFACT_EVALUATION.md",
        root / "RESULTS.md",
    ]:
        copy_if_present(path, release / "documentation" / path.relative_to(root))

    files = sorted(path for path in release.rglob("*") if path.is_file())
    checksum_path = release / "SHA256SUMS"
    with checksum_path.open("w", encoding="utf-8") as handle:
        for path in files:
            if path == checksum_path:
                continue
            handle.write(f"{sha256_file(path)}  {path.relative_to(release)}\n")

    manifest = {
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "baseRunId": args.base_run_id,
        "suite": args.suite,
        "sourceArchive": {
            "path": source_archive.name,
            "sha256": sha256_file(source_archive),
        },
        "runs": copied_runs,
        "notes": [
            "Each experiment bundle retains raw transaction receipts and campaign metadata generated by its launcher.",
            "The source archive excludes generated results, caches, the local .env file, and version-control metadata.",
            "Verify every file with SHA256SUMS before analysis.",
        ],
    }
    (release / "ARTIFACT_INDEX.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (release / "ARTIFACT_INDEX.md").write_text(
        "# ContestFL artifact index\n\n"
        f"- Base run identifier: `{args.base_run_id}`\n"
        f"- Suite: `{args.suite}`\n"
        f"- Experiment bundles: {len(copied_runs)}\n"
        "- Integrity file: `SHA256SUMS`\n"
        "- Machine-readable manifest: `ARTIFACT_INDEX.json`\n\n"
        "The release contains the exact source snapshot, one ZIP per retained experiment, "
        "selected human-readable reports, formal specifications, and environment logs.\n",
        encoding="utf-8",
    )

    outer = release.with_suffix(".zip")
    if outer.exists():
        outer.unlink()
    with zipfile.ZipFile(outer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(release.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=Path(release.name) / path.relative_to(release))
    print(json.dumps({"releaseDir": str(release), "releaseZip": str(outer)}, indent=2))


if __name__ == "__main__":
    main()
