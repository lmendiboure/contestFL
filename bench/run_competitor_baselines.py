#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from eth_account import Account
from web3 import Web3

try:
    from .adapters import AdapterResult, AdmissionAdapter, AggregateAdapter, InclusionAdapter
    from .run_scenarios import RoundData, TxMetric, TxSender, private_key, sha256
except ImportError:  # direct script execution from bench/
    from adapters import AdapterResult, AdmissionAdapter, AggregateAdapter, InclusionAdapter
    from run_scenarios import RoundData, TxMetric, TxSender, private_key, sha256

ROOT = Path(__file__).resolve().parents[1]
ZERO32 = b"\x00" * 32
DESIGNS = ("plain_fl", "ledger_audit", "eager_full", "single_shot")
WORKLOADS = (
    "clean",
    "bad_admission",
    "bad_omission",
    "bad_aggregate",
    "dependent_fault",
    "correction_laundering",
    "resolver_unavailable",
)
KIND = {"ADMIT": 0, "INCLUDE": 1, "AGGREGATE": 2}
OUTCOME = {"OPEN": 0, "UPHELD": 1, "REVISED": 2, "DISMISSED": 3}


@dataclass
class BaselineRound:
    campaign_tag: str
    design: str
    workload: str
    validators: int
    clients: int
    repetition: int
    round_id: int
    expected_outcome: str
    semantic_outcome: str
    semantic_ok: bool
    terminal_state: str
    correct_checkpoint_finalized: bool
    fault_detected: bool
    fault_corrected: bool
    total_ms: float
    offchain_verify_ms: float
    offchain_verify_cpu_ms: float
    tx_count: int
    gas_total: int
    calldata_bytes: int
    first_block: int
    last_block: int
    block_span: int
    update_dim: int
    batch_size: int
    challenge_blocks: int
    response_blocks: int
    error: str = ""


@dataclass
class BaselineAdapter:
    campaign_tag: str
    design: str
    workload: str
    validators: int
    clients: int
    repetition: int
    round_id: int
    adapter: str
    item_index: int
    verdict: str
    corrected_state: int
    valid_evidence: bool
    evidence_hash: str
    certificate_hash: str
    evidence_generation_ms: float
    evidence_generation_cpu_ms: float
    verification_ms: float
    verification_cpu_ms: float
    proof_bytes: int
    artifact_bytes: int
    detail: str


def write_rows(path: Path, rows: Iterable[Any]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    dictionaries = [asdict(row) if not isinstance(row, dict) else row for row in rows]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dictionaries[0]))
        writer.writeheader()
        writer.writerows(dictionaries)


def load_contracts(w3: Web3) -> dict[str, Any]:
    artifact = json.loads((ROOT / "network" / "contracts.json").read_text(encoding="utf-8"))
    result = {}
    for name in ("LoggingOnly", "EagerVerification", "SingleShotOptimistic"):
        entry = artifact["contracts"][name]
        result[name] = w3.eth.contract(address=entry["address"], abi=entry["abi"])
    return result


def keys() -> dict[str, str]:
    result = {
        "coordinator": private_key("coordinator"),
        "resolver": private_key("resolver"),
        "submitter": private_key("submitter"),
        "challenger": private_key("challenger0"),
    }
    return result


def state_for_workload(workload: str, clients: int) -> tuple[list[int], bytes | None]:
    states = [3] * clients
    checkpoint_modifier: bytes | None = None
    if workload in {"bad_admission", "dependent_fault"}:
        states[0] = 1
    elif workload == "bad_omission":
        states[0] = 2
    if workload in {"bad_aggregate", "dependent_fault", "correction_laundering", "resolver_unavailable"}:
        checkpoint_modifier = workload.encode("utf-8")
    return states, checkpoint_modifier


def expected_outcome(design: str, workload: str) -> str:
    if workload == "clean":
        return "CLEAN"
    if workload == "resolver_unavailable":
        return {
            "plain_fl": "NOT_APPLICABLE",
            "ledger_audit": "NOT_APPLICABLE",
            "eager_full": "SAFE_ABORT",
            "single_shot": "STUCK",
        }[design]
    if design == "plain_fl":
        return "FAULTY_FINALIZED"
    if design == "ledger_audit":
        return "DETECTED_ONLY"
    if design == "eager_full":
        return "PREVENTED"
    if design == "single_shot":
        if workload in {"dependent_fault", "correction_laundering"}:
            return "FAULTY_FINALIZED"
        return "CORRECTED"
    raise KeyError((design, workload))


def aggregate_certificate(results: Sequence[AdapterResult]) -> tuple[bytes, bytes]:
    certificates = b"".join(result.certificate_hash for result in results)
    evidences = b"".join(result.evidence_hash for result in results)
    return sha256(b"ContestFL:eager:certificate-root" + certificates), sha256(
        b"ContestFL:eager:evidence-root" + evidences
    )


def adapter_row(
    *, tag: str, design: str, workload: str, validators: int, clients: int,
    repetition: int, round_id: int, item_index: int, result: AdapterResult,
) -> BaselineAdapter:
    return BaselineAdapter(
        campaign_tag=tag,
        design=design,
        workload=workload,
        validators=validators,
        clients=clients,
        repetition=repetition,
        round_id=round_id,
        adapter=result.adapter,
        item_index=item_index,
        verdict=result.verdict,
        corrected_state=result.corrected_state,
        valid_evidence=result.valid_evidence,
        evidence_hash=result.evidence_hash.hex(),
        certificate_hash=result.certificate_hash.hex(),
        evidence_generation_ms=result.evidence_generation_ms,
        evidence_generation_cpu_ms=result.evidence_generation_cpu_ms,
        verification_ms=result.verification_ms,
        verification_cpu_ms=result.verification_cpu_ms,
        proof_bytes=result.proof_bytes,
        artifact_bytes=result.artifact_bytes,
        detail=result.detail,
    )


def receipt_audit(
    *, w3: Web3, logging_contract: Any, round_id: int, client_id: bytes,
    update_hash: bytes, submission_tx_hash: str, state_block: int,
    observed_state: int, policy_state: int,
) -> AdapterResult:
    started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    payload = (
        b"ContestFL:ledger-audit:admission" + round_id.to_bytes(32, "big")
        + client_id + update_hash + observed_state.to_bytes(1, "big")
        + policy_state.to_bytes(1, "big")
    )
    evidence_hash = sha256(payload)
    generation_ms = (time.perf_counter_ns() - started) / 1e6
    generation_cpu_ms = (time.process_time_ns() - cpu_started) / 1e6
    started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    receipt = w3.eth.get_transaction_receipt(submission_tx_hash)
    committed = bytes(logging_contract.functions.submissions(round_id, client_id).call())
    valid = int(receipt.status) == 1 and int(receipt.blockNumber) <= state_block and committed == update_hash
    expected_state = policy_state if valid else 1
    verdict = "REVISED" if observed_state != expected_state else "UPHELD"
    certificate_hash = sha256(evidence_hash + verdict.encode() + expected_state.to_bytes(1, "big"))
    verification_ms = (time.perf_counter_ns() - started) / 1e6
    verification_cpu_ms = (time.process_time_ns() - cpu_started) / 1e6
    return AdapterResult(
        adapter="admission_receipt_audit",
        verdict=verdict,
        corrected_state=expected_state,
        valid_evidence=valid,
        evidence_hash=evidence_hash,
        certificate_hash=certificate_hash,
        evidence_generation_ms=generation_ms,
        evidence_generation_cpu_ms=generation_cpu_ms,
        verification_ms=verification_ms,
        verification_cpu_ms=verification_cpu_ms,
        proof_bytes=len(payload),
        artifact_bytes=0,
        detail=f"receipt={valid}; observed={observed_state}; expected={expected_state}",
    )


def summarize_txs(sender: TxSender | None) -> tuple[int, int, int, int, int, int]:
    if sender is None or not sender.metrics:
        return 0, 0, 0, -1, -1, 0
    blocks = [metric.block_number for metric in sender.metrics]
    return (
        len(sender.metrics),
        sum(metric.gas_used for metric in sender.metrics),
        sum(metric.calldata_bytes for metric in sender.metrics),
        min(blocks),
        max(blocks),
        max(blocks) - min(blocks) + 1,
    )


def finalize_metric(
    *, tag: str, design: str, workload: str, validators: int, clients: int,
    repetition: int, round_id: int, outcome: str, terminal: str,
    correct_checkpoint_finalized: bool, detected: bool, corrected: bool,
    total_ms: float, adapters: Sequence[AdapterResult], sender: TxSender | None,
    update_dim: int, batch_size: int, challenge_blocks: int, response_blocks: int,
    error: str = "",
) -> BaselineRound:
    tx_count, gas, calldata, first_block, last_block, block_span = summarize_txs(sender)
    expected = expected_outcome(design, workload)
    verify_ms = sum(result.evidence_generation_ms + result.verification_ms for result in adapters)
    verify_cpu_ms = sum(
        result.evidence_generation_cpu_ms + result.verification_cpu_ms for result in adapters
    )
    return BaselineRound(
        campaign_tag=tag,
        design=design,
        workload=workload,
        validators=validators,
        clients=clients,
        repetition=repetition,
        round_id=round_id,
        expected_outcome=expected,
        semantic_outcome=outcome,
        semantic_ok=(outcome == expected and not error),
        terminal_state=terminal,
        correct_checkpoint_finalized=correct_checkpoint_finalized,
        fault_detected=detected,
        fault_corrected=corrected,
        total_ms=total_ms,
        offchain_verify_ms=verify_ms,
        offchain_verify_cpu_ms=verify_cpu_ms,
        tx_count=tx_count,
        gas_total=gas,
        calldata_bytes=calldata,
        first_block=first_block,
        last_block=last_block,
        block_span=block_span,
        update_dim=update_dim,
        batch_size=batch_size,
        challenge_blocks=challenge_blocks,
        response_blocks=response_blocks,
        error=error,
    )


def publish_decisions(
    sender: TxSender, contract: Any, round_id: int, data: RoundData,
    states: Sequence[int], batch_size: int, key: str,
) -> None:
    for start in range(0, len(states), batch_size):
        sender.send_one(
            contract.functions.publishDecisions(
                round_id,
                data.client_ids[start : start + batch_size],
                list(states[start : start + batch_size]),
            ),
            key,
            "decide",
        )


def submit_all(
    sender: TxSender, contract: Any, round_id: int, data: RoundData, key: str,
) -> dict[bytes, TxMetric]:
    calls = [
        contract.functions.submit(round_id, client_id, update_hash)
        for client_id, update_hash in zip(data.client_ids, data.update_hashes)
    ]
    metrics = sender.send_many(calls, key, "submit", gas_hint=220_000)
    return {client_id: metric for client_id, metric in zip(data.client_ids, metrics)}


def wait_until_after(w3: Web3, block_number: int) -> None:
    while w3.eth.block_number <= block_number:
        time.sleep(0.05)


def run_plain(
    *, tag: str, validators: int, clients: int, repetition: int, round_id: int,
    data: RoundData, workload: str, update_dim: int, batch_size: int,
    challenge_blocks: int, response_blocks: int,
) -> tuple[BaselineRound, list[BaselineAdapter], list[TxMetric]]:
    started = time.perf_counter_ns()
    correct_states = [3] * clients
    correct_checkpoint = data.checkpoint(correct_states)
    candidate_states, modifier = state_for_workload(workload, clients)
    candidate_checkpoint = data.checkpoint(candidate_states)
    if modifier is not None:
        candidate_checkpoint = sha256(candidate_checkpoint + modifier)
    if workload == "resolver_unavailable":
        outcome = "NOT_APPLICABLE"
        terminal = "NOT_APPLICABLE"
        correct = False
    elif workload == "clean":
        outcome = "CLEAN"
        terminal = "LOCAL_FINALIZED"
        correct = candidate_checkpoint == correct_checkpoint
    else:
        outcome = "FAULTY_FINALIZED"
        terminal = "LOCAL_FINALIZED"
        correct = candidate_checkpoint == correct_checkpoint
    total_ms = (time.perf_counter_ns() - started) / 1e6
    metric = finalize_metric(
        tag=tag, design="plain_fl", workload=workload, validators=validators,
        clients=clients, repetition=repetition, round_id=round_id, outcome=outcome,
        terminal=terminal, correct_checkpoint_finalized=correct, detected=False,
        corrected=False, total_ms=total_ms, adapters=[], sender=None,
        update_dim=update_dim, batch_size=batch_size,
        challenge_blocks=challenge_blocks, response_blocks=response_blocks,
    )
    return metric, [], []


def run_logging(
    *, w3: Web3, contract: Any, keyset: dict[str, str], tag: str,
    validators: int, clients: int, repetition: int, round_id: int,
    data: RoundData, workload: str, update_dim: int, batch_size: int,
    challenge_blocks: int, response_blocks: int,
) -> tuple[BaselineRound, list[BaselineAdapter], list[TxMetric]]:
    sender = TxSender(w3, validators, clients, repetition, workload, round_id, tag)
    started = time.perf_counter_ns()
    adapters: list[AdapterResult] = []
    adapter_rows: list[BaselineAdapter] = []
    correct_states = [3] * clients
    correct_checkpoint = data.checkpoint(correct_states)
    if workload == "resolver_unavailable":
        metric = finalize_metric(
            tag=tag, design="ledger_audit", workload=workload, validators=validators,
            clients=clients, repetition=repetition, round_id=round_id,
            outcome="NOT_APPLICABLE", terminal="NOT_APPLICABLE",
            correct_checkpoint_finalized=False, detected=False, corrected=False,
            total_ms=0.0, adapters=[], sender=sender, update_dim=update_dim,
            batch_size=batch_size, challenge_blocks=challenge_blocks,
            response_blocks=response_blocks,
        )
        return metric, [], sender.metrics

    states, modifier = state_for_workload(workload, clients)
    trees = data.trees(states)
    checkpoint = data.checkpoint(states)
    if modifier is not None:
        checkpoint = sha256(checkpoint + modifier)
    sender.send_one(contract.functions.openRound(round_id, clients), keyset["coordinator"], "open")
    submission = submit_all(sender, contract, round_id, data, keyset["submitter"])
    publish = sender.send_one(
        contract.functions.publishState(round_id, *(tree.root for tree in trees), checkpoint),
        keyset["coordinator"],
        "publish_state",
    )
    sender.send_one(contract.functions.finalize(round_id), keyset["coordinator"], "finalize")

    if workload != "clean":
        if workload in {"bad_admission", "dependent_fault"}:
            result = receipt_audit(
                w3=w3, logging_contract=contract, round_id=round_id,
                client_id=data.client_ids[0], update_hash=data.update_hashes[0],
                submission_tx_hash=submission[data.client_ids[0]].tx_hash,
                state_block=publish.block_number, observed_state=states[0], policy_state=3,
            )
        elif workload == "bad_omission":
            result = InclusionAdapter.verify(
                client_id=data.client_ids[0], admitted_tree=trees[1], aggregate_tree=trees[2],
                admitted_root=trees[1].root, aggregate_root=trees[2].root,
                observed_state=states[0],
            )
        else:
            result = AggregateAdapter.verify(
                updates=data.updates, states=states, claimed_checkpoint=checkpoint,
                aggregate_root=trees[2].root,
            )
        adapters.append(result)
        adapter_rows.append(adapter_row(
            tag=tag, design="ledger_audit", workload=workload, validators=validators,
            clients=clients, repetition=repetition, round_id=round_id, item_index=0,
            result=result,
        ))
    total_ms = (time.perf_counter_ns() - started) / 1e6
    correct = checkpoint == correct_checkpoint
    outcome = "CLEAN" if workload == "clean" else "DETECTED_ONLY"
    metric = finalize_metric(
        tag=tag, design="ledger_audit", workload=workload, validators=validators,
        clients=clients, repetition=repetition, round_id=round_id, outcome=outcome,
        terminal="FINALIZED", correct_checkpoint_finalized=correct,
        detected=bool(adapters), corrected=False, total_ms=total_ms, adapters=adapters,
        sender=sender, update_dim=update_dim, batch_size=batch_size,
        challenge_blocks=challenge_blocks, response_blocks=response_blocks,
    )
    return metric, adapter_rows, sender.metrics


def eager_suite(
    *, w3: Web3, contract: Any, round_id: int, data: RoundData,
    states: Sequence[int], trees: Sequence[Any], checkpoint: bytes,
    submission: dict[bytes, TxMetric], state_block: int,
) -> list[AdapterResult]:
    results: list[AdapterResult] = []
    for index, client_id in enumerate(data.client_ids):
        results.append(AdmissionAdapter.verify(
            w3=w3, contract=contract, round_id=round_id, client_id=client_id,
            update_hash=data.update_hashes[index],
            submission_tx_hash=submission[client_id].tx_hash,
            initial_state_block=state_block, observed_state=int(states[index]), policy_state=3,
        ))
    for index, client_id in enumerate(data.client_ids):
        results.append(InclusionAdapter.verify(
            client_id=client_id, admitted_tree=trees[1], aggregate_tree=trees[2],
            admitted_root=trees[1].root, aggregate_root=trees[2].root,
            observed_state=int(states[index]),
        ))
    results.append(AggregateAdapter.verify(
        updates=data.updates, states=states, claimed_checkpoint=checkpoint,
        aggregate_root=trees[2].root,
    ))
    return results


def run_eager(
    *, w3: Web3, contract: Any, keyset: dict[str, str], tag: str,
    validators: int, clients: int, repetition: int, round_id: int,
    data: RoundData, workload: str, update_dim: int, batch_size: int,
    challenge_blocks: int, response_blocks: int,
) -> tuple[BaselineRound, list[BaselineAdapter], list[TxMetric]]:
    sender = TxSender(w3, validators, clients, repetition, workload, round_id, tag)
    started = time.perf_counter_ns()
    adapter_rows: list[BaselineAdapter] = []
    correct_states = [3] * clients
    correct_trees = data.trees(correct_states)
    correct_checkpoint = data.checkpoint(correct_states)
    states, modifier = state_for_workload(workload, clients)
    trees = data.trees(states)
    checkpoint = data.checkpoint(states)
    if modifier is not None:
        checkpoint = sha256(checkpoint + modifier)

    verification_blocks = max(response_blocks, 12, math.ceil(clients / 10) + 8)
    sender.send_one(
        contract.functions.openRound(round_id, clients, verification_blocks),
        keyset["coordinator"], "open",
    )
    submission = submit_all(sender, contract, round_id, data, keyset["submitter"])
    publish_decisions(sender, contract, round_id, data, states, batch_size, keyset["coordinator"])
    publish = sender.send_one(
        contract.functions.publishCandidateState(
            round_id, *(tree.root for tree in trees), checkpoint
        ),
        keyset["coordinator"], "publish_candidate",
    )

    if workload == "resolver_unavailable":
        status = contract.functions.getRoundStatus(round_id).call()
        wait_until_after(w3, int(status[3]))
        sender.send_one(
            contract.functions.expireVerification(round_id), keyset["challenger"], "expire"
        )
        total_ms = (time.perf_counter_ns() - started) / 1e6
        metric = finalize_metric(
            tag=tag, design="eager_full", workload=workload, validators=validators,
            clients=clients, repetition=repetition, round_id=round_id,
            outcome="SAFE_ABORT", terminal="ABORTED",
            correct_checkpoint_finalized=False, detected=False, corrected=False,
            total_ms=total_ms, adapters=[], sender=sender, update_dim=update_dim,
            batch_size=batch_size, challenge_blocks=challenge_blocks,
            response_blocks=verification_blocks,
        )
        return metric, [], sender.metrics

    results = eager_suite(
        w3=w3, contract=contract, round_id=round_id, data=data, states=states,
        trees=trees, checkpoint=checkpoint, submission=submission,
        state_block=publish.block_number,
    )
    for index, result in enumerate(results):
        adapter_rows.append(adapter_row(
            tag=tag, design="eager_full", workload=workload, validators=validators,
            clients=clients, repetition=repetition, round_id=round_id,
            item_index=index, result=result,
        ))
    certificate, evidence_root = aggregate_certificate(results)
    sender.send_one(
        contract.functions.installVerifiedState(
            round_id, *(tree.root for tree in correct_trees), correct_checkpoint,
            certificate, evidence_root,
        ),
        keyset["resolver"], "verify_install",
    )
    sender.send_one(contract.functions.finalize(round_id), keyset["coordinator"], "finalize")
    total_ms = (time.perf_counter_ns() - started) / 1e6
    detected = any(result.verdict == "REVISED" for result in results)
    outcome = "CLEAN" if workload == "clean" else "PREVENTED"
    metric = finalize_metric(
        tag=tag, design="eager_full", workload=workload, validators=validators,
        clients=clients, repetition=repetition, round_id=round_id, outcome=outcome,
        terminal="FINALIZED", correct_checkpoint_finalized=True,
        detected=detected, corrected=workload != "clean", total_ms=total_ms,
        adapters=results, sender=sender, update_dim=update_dim, batch_size=batch_size,
        challenge_blocks=challenge_blocks, response_blocks=verification_blocks,
    )
    return metric, adapter_rows, sender.metrics


def single_evidence(
    *, workload: str, w3: Web3, contract: Any, round_id: int, data: RoundData,
    states: Sequence[int], trees: Sequence[Any], checkpoint: bytes,
    submission: dict[bytes, TxMetric], state_block: int,
) -> tuple[str, bytes, int, AdapterResult]:
    if workload in {"bad_admission", "dependent_fault"}:
        result = AdmissionAdapter.verify(
            w3=w3, contract=contract, round_id=round_id,
            client_id=data.client_ids[0], update_hash=data.update_hashes[0],
            submission_tx_hash=submission[data.client_ids[0]].tx_hash,
            initial_state_block=state_block, observed_state=int(states[0]), policy_state=3,
        )
        return "ADMIT", data.client_ids[0], 3, result
    if workload == "bad_omission":
        result = InclusionAdapter.verify(
            client_id=data.client_ids[0], admitted_tree=trees[1], aggregate_tree=trees[2],
            admitted_root=trees[1].root, aggregate_root=trees[2].root,
            observed_state=int(states[0]),
        )
        return "INCLUDE", data.client_ids[0], 3, result
    result = AggregateAdapter.verify(
        updates=data.updates, states=states, claimed_checkpoint=checkpoint,
        aggregate_root=trees[2].root,
    )
    return "AGGREGATE", ZERO32, 0, result


def run_single_shot(
    *, w3: Web3, contract: Any, keyset: dict[str, str], tag: str,
    validators: int, clients: int, repetition: int, round_id: int,
    data: RoundData, workload: str, update_dim: int, batch_size: int,
    challenge_blocks: int, response_blocks: int,
) -> tuple[BaselineRound, list[BaselineAdapter], list[TxMetric]]:
    sender = TxSender(w3, validators, clients, repetition, workload, round_id, tag)
    started = time.perf_counter_ns()
    correct_states = [3] * clients
    correct_trees = data.trees(correct_states)
    correct_checkpoint = data.checkpoint(correct_states)
    states, modifier = state_for_workload(workload, clients)
    trees = data.trees(states)
    checkpoint = data.checkpoint(states)
    if modifier is not None:
        checkpoint = sha256(checkpoint + modifier)

    sender.send_one(
        contract.functions.openRound(round_id, clients, challenge_blocks, response_blocks),
        keyset["coordinator"], "open",
    )
    submission = submit_all(sender, contract, round_id, data, keyset["submitter"])
    publish_decisions(sender, contract, round_id, data, states, batch_size, keyset["coordinator"])
    publish = sender.send_one(
        contract.functions.publishInitialState(
            round_id, *(tree.root for tree in trees), checkpoint
        ),
        keyset["coordinator"], "publish_initial",
    )

    if workload == "clean":
        status = contract.functions.getRoundStatus(round_id).call()
        wait_until_after(w3, int(status[2]))
        sender.send_one(contract.functions.finalize(round_id), keyset["coordinator"], "finalize")
        total_ms = (time.perf_counter_ns() - started) / 1e6
        return finalize_metric(
            tag=tag, design="single_shot", workload=workload, validators=validators,
            clients=clients, repetition=repetition, round_id=round_id, outcome="CLEAN",
            terminal="FINALIZED", correct_checkpoint_finalized=True,
            detected=False, corrected=False, total_ms=total_ms, adapters=[], sender=sender,
            update_dim=update_dim, batch_size=batch_size,
            challenge_blocks=challenge_blocks, response_blocks=response_blocks,
        ), [], sender.metrics

    kind, client_id, claimed_state, result = single_evidence(
        workload=workload,
        w3=w3, contract=contract, round_id=round_id, data=data, states=states,
        trees=trees, checkpoint=checkpoint, submission=submission,
        state_block=publish.block_number,
    )
    challenge_id = int(contract.functions.nextChallengeId().call())
    sender.send_one(
        contract.functions.openChallenge(
            round_id, KIND[kind], client_id, claimed_state, result.evidence_hash
        ),
        keyset["challenger"], "challenge",
    )
    row = adapter_row(
        tag=tag, design="single_shot", workload=workload, validators=validators,
        clients=clients, repetition=repetition, round_id=round_id, item_index=0,
        result=result,
    )

    if workload == "resolver_unavailable":
        challenge = contract.functions.challenges(challenge_id).call()
        wait_until_after(w3, int(challenge[6]))
        total_ms = (time.perf_counter_ns() - started) / 1e6
        return finalize_metric(
            tag=tag, design="single_shot", workload=workload, validators=validators,
            clients=clients, repetition=repetition, round_id=round_id, outcome="STUCK",
            terminal="CHALLENGE", correct_checkpoint_finalized=False,
            detected=True, corrected=False, total_ms=total_ms, adapters=[result], sender=sender,
            update_dim=update_dim, batch_size=batch_size,
            challenge_blocks=challenge_blocks, response_blocks=response_blocks,
        ), [row], sender.metrics

    sender.send_one(
        contract.functions.resolveChallenge(
            challenge_id, OUTCOME["REVISED"], result.corrected_state,
            result.certificate_hash,
        ),
        keyset["resolver"], "resolve",
    )
    replacement_checkpoint = correct_checkpoint
    replacement_trees = correct_trees
    if workload == "dependent_fault":
        replacement_checkpoint = checkpoint
    elif workload == "correction_laundering":
        replacement_checkpoint = sha256(correct_checkpoint + b":single-shot-laundered")
    sender.send_one(
        contract.functions.publishTerminalReplacement(
            round_id, *(tree.root for tree in replacement_trees), replacement_checkpoint
        ),
        keyset["coordinator"], "terminal_replacement",
    )
    sender.send_one(contract.functions.finalize(round_id), keyset["coordinator"], "finalize")
    total_ms = (time.perf_counter_ns() - started) / 1e6
    correct = replacement_checkpoint == correct_checkpoint
    outcome = "CORRECTED" if correct else "FAULTY_FINALIZED"
    return finalize_metric(
        tag=tag, design="single_shot", workload=workload, validators=validators,
        clients=clients, repetition=repetition, round_id=round_id, outcome=outcome,
        terminal="FINALIZED", correct_checkpoint_finalized=correct,
        detected=True, corrected=correct, total_ms=total_ms, adapters=[result], sender=sender,
        update_dim=update_dim, batch_size=batch_size,
        challenge_blocks=challenge_blocks, response_blocks=response_blocks,
    ), [row], sender.metrics


def run_one(
    *, design: str, workload: str, w3: Web3, contracts: dict[str, Any],
    keyset: dict[str, str], tag: str, validators: int, clients: int,
    repetition: int, round_id: int, update_dim: int, smt_depth: int,
    batch_size: int, challenge_blocks: int, response_blocks: int,
) -> tuple[BaselineRound, list[BaselineAdapter], list[TxMetric]]:
    data = RoundData.generate(
        clients=clients,
        update_dim=update_dim,
        seed=round_id * 131 + max(repetition, 0),
        smt_depth=smt_depth,
    )
    kwargs = dict(
        tag=tag, validators=validators, clients=clients, repetition=repetition,
        round_id=round_id, data=data, workload=workload, update_dim=update_dim,
        batch_size=batch_size, challenge_blocks=challenge_blocks,
        response_blocks=response_blocks,
    )
    if design == "plain_fl":
        return run_plain(**kwargs)
    if design == "ledger_audit":
        return run_logging(w3=w3, contract=contracts["LoggingOnly"], keyset=keyset, **kwargs)
    if design == "eager_full":
        return run_eager(w3=w3, contract=contracts["EagerVerification"], keyset=keyset, **kwargs)
    if design == "single_shot":
        return run_single_shot(
            w3=w3, contract=contracts["SingleShotOptimistic"], keyset=keyset, **kwargs
        )
    raise KeyError(design)


def parse_list(value: str, allowed: Sequence[str] | None = None) -> list[str]:
    result = [part.strip() for part in value.split(",") if part.strip()]
    if allowed is not None:
        unknown = set(result) - set(allowed)
        if unknown:
            raise ValueError(f"unknown values: {sorted(unknown)}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="ContestFL representative competitor baselines")
    parser.add_argument("--validators", type=int, default=4)
    parser.add_argument("--clients", default="10,50,100")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--designs", default=",".join(DESIGNS))
    parser.add_argument("--workloads", default="clean")
    parser.add_argument("--update-dim", type=int, default=1024)
    parser.add_argument("--smt-depth", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--challenge-blocks", type=int, default=1)
    parser.add_argument("--response-blocks", type=int, default=4)
    parser.add_argument("--tag", default="competitor_clean")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL", "http://node1:8545"), request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        raise RuntimeError("Besu RPC is unavailable")
    contracts = load_contracts(w3)
    keyset = keys()
    clients_list = [int(value) for value in parse_list(args.clients)]
    designs = parse_list(args.designs, DESIGNS)
    workloads = parse_list(args.workloads, WORKLOADS)

    rounds: list[BaselineRound] = []
    adapters: list[BaselineAdapter] = []
    transactions: list[dict[str, Any]] = []
    failures = 0
    tag_component = int.from_bytes(sha256(args.tag.encode())[:4], "big")
    round_counter = int(time.time_ns() // 1_000_000) * 1_000_000 + tag_component

    for clients in clients_list:
        for design_index, design in enumerate(designs):
            for workload_index, workload in enumerate(workloads):
                for repetition in range(-args.warmup, args.rounds):
                    round_counter += 1
                    round_id = round_counter
                    try:
                        metric, adapter_metrics, tx_metrics = run_one(
                            design=design, workload=workload, w3=w3, contracts=contracts,
                            keyset=keyset, tag=args.tag, validators=args.validators,
                            clients=clients, repetition=repetition, round_id=round_id,
                            update_dim=args.update_dim, smt_depth=args.smt_depth,
                            batch_size=args.batch_size,
                            challenge_blocks=args.challenge_blocks,
                            response_blocks=args.response_blocks,
                        )
                    except Exception as exc:
                        failures += int(repetition >= 0)
                        metric = BaselineRound(
                            campaign_tag=args.tag, design=design, workload=workload,
                            validators=args.validators, clients=clients,
                            repetition=repetition, round_id=round_id,
                            expected_outcome=expected_outcome(design, workload),
                            semantic_outcome="ERROR", semantic_ok=False,
                            terminal_state="ERROR", correct_checkpoint_finalized=False,
                            fault_detected=False, fault_corrected=False, total_ms=0.0,
                            offchain_verify_ms=0.0, offchain_verify_cpu_ms=0.0,
                            tx_count=0, gas_total=0, calldata_bytes=0,
                            first_block=-1, last_block=-1, block_span=0,
                            update_dim=args.update_dim, batch_size=args.batch_size,
                            challenge_blocks=args.challenge_blocks,
                            response_blocks=args.response_blocks,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                        adapter_metrics, tx_metrics = [], []
                    if repetition >= 0:
                        rounds.append(metric)
                        adapters.extend(adapter_metrics)
                        for tx in tx_metrics:
                            row = asdict(tx)
                            row["design"] = design
                            row["workload"] = workload
                            transactions.append(row)
                    print(json.dumps({
                        "tag": args.tag, "design": design, "workload": workload,
                        "clients": clients, "repetition": repetition,
                        "outcome": metric.semantic_outcome,
                        "total_ms": round(metric.total_ms, 3),
                        "tx": metric.tx_count, "error": not metric.semantic_ok,
                    }))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_rows(args.output_dir / f"baseline_rounds_{args.tag}_v{args.validators}.csv", rounds)
    write_rows(args.output_dir / f"baseline_adapters_{args.tag}_v{args.validators}.csv", adapters)
    write_rows(args.output_dir / f"baseline_txs_{args.tag}_v{args.validators}.csv", transactions)
    semantic_failures = sum(not row.semantic_ok for row in rounds)
    print(json.dumps({
        "output": str(args.output_dir),
        "rounds": len(rounds),
        "semantic_failures": semantic_failures,
        "runtime_failures": failures,
    }, indent=2))
    if semantic_failures or failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
