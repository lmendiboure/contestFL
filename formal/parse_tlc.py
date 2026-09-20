#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_one(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace")
    generated = distinct = queue = None
    matches = re.findall(
        r"([0-9][0-9,]*) states generated, ([0-9][0-9,]*) distinct states found, ([0-9][0-9,]*) states left on queue",
        text,
    )
    if matches:
        g, d, q = matches[-1]
        generated, distinct, queue = (int(value.replace(",", "")) for value in (g, d, q))
    depth_match = re.search(r"The depth of the complete state graph search is ([0-9]+)", text)
    elapsed_match = re.search(r"Finished in ([^\n]+)", text)
    success = "Model checking completed. No error has been found." in text
    return {
        "file": path.name,
        "success": success,
        "statesGenerated": generated,
        "distinctStates": distinct,
        "statesLeftOnQueue": queue,
        "graphDepth": int(depth_match.group(1)) if depth_match else None,
        "elapsed": elapsed_match.group(1).strip() if elapsed_match else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("outputs", nargs="+")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    runs = [parse_one(Path(item)) for item in args.outputs]
    payload = {"runs": runs, "allSuccessful": all(bool(run["success"]) for run in runs)}
    (output_dir / "TLC_RESULTS.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# TLC model-checking results",
        "",
        "| Model | Successful | Generated states | Distinct states | Graph depth | Elapsed |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for run in runs:
        lines.append(
            f"| {run['file']} | {run['success']} | {run['statesGenerated']} | "
            f"{run['distinctStates']} | {run['graphDepth']} | {run['elapsed']} |"
        )
    lines.extend([
        "",
        "TLC exhaustively explores the finite configurations defined in the accompanying `.cfg` files. This bounded model checking supports the state-machine argument but does not replace the parameterized mathematical proofs in the supplementary material.",
    ])
    (output_dir / "TLC_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    tex = [
        r"\begin{table}[h]",
        r"\centering",
        r"\caption{Exhaustive TLC results for the supplied finite configurations.}",
        r"\begin{tabular}{@{}lrrrr@{}}",
        r"\toprule",
        r"Model & Generated & Distinct & Depth & Success \\",
        r"\midrule",
    ]
    for run in runs:
        model = str(run["file"]).replace("_", r"\_")
        generated_value = "--" if run["statesGenerated"] is None else str(run["statesGenerated"])
        distinct_value = "--" if run["distinctStates"] is None else str(run["distinctStates"])
        depth_value = "--" if run["graphDepth"] is None else str(run["graphDepth"])
        success_value = "yes" if run["success"] else "no"
        tex.append(
            f"{model} & {generated_value} & {distinct_value} & {depth_value} & {success_value} \\\\")
    tex.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}"])
    (output_dir / "TLC_RESULTS.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if not payload["allSuccessful"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
