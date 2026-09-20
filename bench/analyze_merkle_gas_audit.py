#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit that Merkle verification is included in retained gas")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = ROOT / args.run_dir
    raw = run_dir / "raw"

    tx_files = sorted(raw.glob("root_only_transactions_root_only_v*.csv"))
    round_files = sorted(raw.glob("root_only_rounds_root_only_v*.csv"))
    if not tx_files or not round_files:
        raise FileNotFoundError("root-only transaction/round CSVs are missing")

    txs = pd.concat([pd.read_csv(path) for path in tx_files], ignore_index=True)
    rounds = pd.concat([pd.read_csv(path) for path in round_files], ignore_index=True)
    proof_txs = txs[txs["phase"] == "challenge_with_proof"].copy()
    if proof_txs.empty:
        raise RuntimeError("no challenge_with_proof transaction was retained")
    if not (proof_txs["status"] == 1).all():
        raise RuntimeError("at least one proof-bearing challenge transaction failed")

    proof_rounds = rounds[rounds["workload"] == "bad_admission"]
    if proof_rounds.empty or (proof_rounds["proof_bytes"] <= 0).any():
        raise RuntimeError("proof-bearing rounds do not report a non-zero witness size")

    source_path = ROOT / "contracts" / "RootOnlyContestFL.sol"
    source = source_path.read_text(encoding="utf-8")
    required_fragments = [
        "function openDecisionChallenge",
        "if (!verifySparseProof",
        "function verifySparseProof",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in source]
    if missing:
        raise RuntimeError(f"contract source no longer proves the expected call path: {missing}")

    summary = proof_txs.groupby("clients", as_index=False).agg(
        runs=("round_id", "count"),
        gas_median=("gas_used", "median"),
        gas_min=("gas_used", "min"),
        gas_max=("gas_used", "max"),
        calldata_median=("calldata_bytes", "median"),
        status_success_rate=("status", lambda values: float((values == 1).mean())),
    )
    witness = proof_rounds.groupby("clients", as_index=False).agg(
        proof_bytes=("proof_bytes", "median"),
        smt_depth=("smt_depth", "median"),
    )
    summary = summary.merge(witness, on="clients", how="left")
    summary.to_csv(run_dir / "merkle_gas_audit.csv", index=False)

    payload = {
        "conclusion": "included",
        "reason": (
            "openDecisionChallenge calls verifySparseProof before any challenge state is accepted, "
            "and TxSender records receipt.gasUsed for that same state-changing transaction."
        ),
        "contractSha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "proofTransactionPhase": "challenge_with_proof",
        "summary": summary.to_dict(orient="records"),
        "scope": (
            "The transaction gas includes Merkle verification, calldata decoding, duplicate protection, "
            "challenge storage, and event emission. It is not an isolated precompile-only measurement."
        ),
    }
    (run_dir / "MERKLE_GAS_AUDIT.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Merkle-verification gas audit",
        "",
        "**Conclusion: the sparse-Merkle verification is included in the retained gas measurement.**",
        "",
        "The measured transaction is `openDecisionChallenge`. The contract invokes `verifySparseProof(...)` and reverts on failure before recording the challenge. The harness then stores `receipt.gasUsed` for this same state-changing transaction under the phase `challenge_with_proof`. Consequently, the reported gas includes the full on-chain SHA-256 path reconstruction.",
        "",
        "| Clients | Runs | SMT depth | Witness bytes | Median transaction gas | Median calldata (B) |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.to_dict(orient="records"):
        lines.append(
            f"| {int(row['clients'])} | {int(row['runs'])} | {int(row['smt_depth'])} | "
            f"{int(row['proof_bytes'])} | {int(row['gas_median'])} | {int(row['calldata_median'])} |"
        )
    lines.extend([
        "",
        "The value is deliberately reported as a complete challenge-acceptance transaction, not as an isolated Merkle primitive: it also includes ABI decoding, duplicate-challenge protection, persistent challenge state, and event emission.",
    ])
    (run_dir / "MERKLE_GAS_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(run_dir / "MERKLE_GAS_AUDIT.md")


if __name__ == "__main__":
    main()
