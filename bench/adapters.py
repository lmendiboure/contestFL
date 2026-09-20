from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

try:
    from .smt import SparseMerkleMap, SparseProof
except ImportError:  # script execution from bench/
    from smt import SparseMerkleMap, SparseProof


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _canonical_json(payload: dict[str, Any]) -> bytes:
    def normalize(value: Any) -> Any:
        if isinstance(value, bytes):
            return "0x" + value.hex()
        if isinstance(value, tuple):
            return [normalize(item) for item in value]
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in sorted(value.items())}
        return value

    return json.dumps(normalize(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class AdapterResult:
    adapter: str
    verdict: str
    corrected_state: int
    valid_evidence: bool
    evidence_hash: bytes
    certificate_hash: bytes
    evidence_generation_ms: float
    evidence_generation_cpu_ms: float
    verification_ms: float
    verification_cpu_ms: float
    proof_bytes: int
    artifact_bytes: int
    detail: str


class AdmissionAdapter:
    """Reassess an ADMIT decision from a ledger receipt and public policy.

    The benchmark policy is deliberately simple and explicit: a submission whose
    successful receipt is committed on chain before publication of the initial
    state receives the policy state supplied by the campaign. This exercises the
    receipt/context binding rather than hard-coding the resolver verdict.
    """

    name = "admission_receipt"

    @classmethod
    def verify(
        cls,
        *,
        w3: Any,
        contract: Any,
        round_id: int,
        client_id: bytes,
        update_hash: bytes,
        submission_tx_hash: str,
        initial_state_block: int,
        observed_state: int,
        policy_state: int,
    ) -> AdapterResult:
        started = time.perf_counter_ns()
        cpu_started = time.process_time_ns()
        evidence = {
            "adapter": cls.name,
            "round": round_id,
            "client": client_id,
            "update": update_hash,
            "submissionTx": submission_tx_hash,
            "initialStateBlock": initial_state_block,
            "observedState": observed_state,
            "policyState": policy_state,
        }
        encoded = _canonical_json(evidence)
        evidence_hash = sha256(encoded)
        generation_ms = (time.perf_counter_ns() - started) / 1e6
        generation_cpu_ms = (time.process_time_ns() - cpu_started) / 1e6

        started = time.perf_counter_ns()
        cpu_started = time.process_time_ns()
        receipt = w3.eth.get_transaction_receipt(submission_tx_hash)
        committed = bytes(contract.functions.submissionHash(round_id, client_id).call())
        valid_receipt = (
            int(receipt.status) == 1
            and int(receipt.blockNumber) <= int(initial_state_block)
            and committed == update_hash
        )
        expected_state = policy_state if valid_receipt else 1
        verdict = "REVISED" if observed_state != expected_state else "UPHELD"
        detail = (
            f"receipt_status={int(receipt.status)}; receipt_block={int(receipt.blockNumber)}; "
            f"initial_state_block={initial_state_block}; committed={committed.hex() == update_hash.hex()}; "
            f"observed={observed_state}; expected={expected_state}"
        )
        certificate_hash = sha256(
            b"ContestFL:certificate:admission"
            + evidence_hash
            + verdict.encode()
            + expected_state.to_bytes(1, "big")
        )
        verification_ms = (time.perf_counter_ns() - started) / 1e6
        verification_cpu_ms = (time.process_time_ns() - cpu_started) / 1e6
        return AdapterResult(
            adapter=cls.name,
            verdict=verdict,
            corrected_state=expected_state,
            valid_evidence=valid_receipt,
            evidence_hash=evidence_hash,
            certificate_hash=certificate_hash,
            evidence_generation_ms=generation_ms,
            evidence_generation_cpu_ms=generation_cpu_ms,
            verification_ms=verification_ms,
            verification_cpu_ms=verification_cpu_ms,
            proof_bytes=len(encoded),
            artifact_bytes=0,
            detail=detail,
        )


class InclusionAdapter:
    """Verify sparse-Merkle membership/non-membership for INCLUDE disputes."""

    name = "sparse_merkle_inclusion"

    @staticmethod
    def _proof_payload(proof: SparseProof) -> dict[str, Any]:
        return {
            "siblings": list(proof.siblings),
            "exists": proof.exists,
            "value": proof.value,
        }

    @classmethod
    def verify(
        cls,
        *,
        client_id: bytes,
        admitted_tree: SparseMerkleMap,
        aggregate_tree: SparseMerkleMap,
        admitted_root: bytes,
        aggregate_root: bytes,
        observed_state: int,
    ) -> AdapterResult:
        started = time.perf_counter_ns()
        cpu_started = time.process_time_ns()
        admitted_proof = admitted_tree.prove(client_id)
        aggregate_proof = aggregate_tree.prove(client_id)
        evidence = {
            "adapter": cls.name,
            "client": client_id,
            "admittedRoot": admitted_root,
            "aggregateRoot": aggregate_root,
            "admittedProof": cls._proof_payload(admitted_proof),
            "aggregateProof": cls._proof_payload(aggregate_proof),
            "observedState": observed_state,
        }
        encoded = _canonical_json(evidence)
        evidence_hash = sha256(encoded)
        generation_ms = (time.perf_counter_ns() - started) / 1e6
        generation_cpu_ms = (time.process_time_ns() - cpu_started) / 1e6

        started = time.perf_counter_ns()
        cpu_started = time.process_time_ns()
        admitted_ok = admitted_tree.verify(client_id, admitted_proof, admitted_root)
        aggregate_ok = aggregate_tree.verify(client_id, aggregate_proof, aggregate_root)
        valid = admitted_ok and aggregate_ok
        if admitted_proof.exists:
            expected_state = 3
            mismatch = not aggregate_proof.exists or observed_state != 3
        else:
            expected_state = 1
            mismatch = aggregate_proof.exists or observed_state != 1
        verdict = "REVISED" if valid and mismatch else "UPHELD" if valid else "DISMISSED"
        detail = (
            f"admitted_proof={admitted_ok}/{admitted_proof.exists}; "
            f"aggregate_proof={aggregate_ok}/{aggregate_proof.exists}; "
            f"observed={observed_state}; expected={expected_state}"
        )
        certificate_hash = sha256(
            b"ContestFL:certificate:inclusion"
            + evidence_hash
            + verdict.encode()
            + expected_state.to_bytes(1, "big")
        )
        verification_ms = (time.perf_counter_ns() - started) / 1e6
        verification_cpu_ms = (time.process_time_ns() - cpu_started) / 1e6
        proof_bytes = 2 * (len(admitted_proof.siblings) * 32 + 1) + len(admitted_proof.value) + len(aggregate_proof.value)
        return AdapterResult(
            adapter=cls.name,
            verdict=verdict,
            corrected_state=expected_state,
            valid_evidence=valid,
            evidence_hash=evidence_hash,
            certificate_hash=certificate_hash,
            evidence_generation_ms=generation_ms,
            evidence_generation_cpu_ms=generation_cpu_ms,
            verification_ms=verification_ms,
            verification_cpu_ms=verification_cpu_ms,
            proof_bytes=proof_bytes,
            artifact_bytes=0,
            detail=detail,
        )


class AggregateAdapter:
    """Deterministically replay the declared integer FedAvg-style aggregate."""

    name = "deterministic_aggregate_replay"

    @classmethod
    def verify(
        cls,
        *,
        updates: Sequence[np.ndarray],
        states: Sequence[int],
        claimed_checkpoint: bytes,
        aggregate_root: bytes,
    ) -> AdapterResult:
        selected = [update for update, state in zip(updates, states) if state == 3]
        started = time.perf_counter_ns()
        cpu_started = time.process_time_ns()
        evidence_header = {
            "adapter": cls.name,
            "aggregateRoot": aggregate_root,
            "claimedCheckpoint": claimed_checkpoint,
            "selected": len(selected),
            "dtype": "int32->int64-sum",
        }
        encoded = _canonical_json(evidence_header)
        evidence_hash = sha256(encoded)
        generation_ms = (time.perf_counter_ns() - started) / 1e6
        generation_cpu_ms = (time.process_time_ns() - cpu_started) / 1e6

        started = time.perf_counter_ns()
        cpu_started = time.process_time_ns()
        if selected:
            accumulator = np.zeros_like(selected[0], dtype=np.int64)
            for update in selected:
                accumulator += update.astype(np.int64, copy=False)
            expected_checkpoint = sha256(
                b"ContestFL:canonical-aggregate"
                + len(selected).to_bytes(8, "big")
                + accumulator.tobytes(order="C")
            )
        else:
            expected_checkpoint = sha256(b"ContestFL:empty-checkpoint")
        verdict = "REVISED" if expected_checkpoint != claimed_checkpoint else "UPHELD"
        detail = (
            f"selected={len(selected)}; claimed={claimed_checkpoint.hex()}; "
            f"replayed={expected_checkpoint.hex()}"
        )
        certificate_hash = sha256(
            b"ContestFL:certificate:aggregate"
            + evidence_hash
            + verdict.encode()
            + expected_checkpoint
        )
        verification_ms = (time.perf_counter_ns() - started) / 1e6
        verification_cpu_ms = (time.process_time_ns() - cpu_started) / 1e6
        artifact_bytes = sum(int(update.nbytes) for update in selected)
        return AdapterResult(
            adapter=cls.name,
            verdict=verdict,
            corrected_state=0,
            valid_evidence=True,
            evidence_hash=evidence_hash,
            certificate_hash=certificate_hash,
            evidence_generation_ms=generation_ms,
            evidence_generation_cpu_ms=generation_cpu_ms,
            verification_ms=verification_ms,
            verification_cpu_ms=verification_cpu_ms,
            proof_bytes=len(encoded),
            artifact_bytes=artifact_bytes,
            detail=detail,
        )
