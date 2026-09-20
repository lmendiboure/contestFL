#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import socket
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np
from eth_account import Account
from web3 import Web3

try:
    from .adapters import AdapterResult, AdmissionAdapter, AggregateAdapter, InclusionAdapter
    from .smt import SparseMerkleMap
except ImportError:  # direct script execution from bench/
    from adapters import AdapterResult, AdmissionAdapter, AggregateAdapter, InclusionAdapter
    from smt import SparseMerkleMap

ROOT = Path(__file__).resolve().parents[1]
ZERO32 = b"\x00" * 32

PHASE = {
    "NONE": 0,
    "SUBMIT": 1,
    "CHALLENGE": 2,
    "RESOLVING": 3,
    "READY": 4,
    "FINALIZED": 5,
    "ABORTED": 6,
}
KIND = {"ADMIT": 0, "INCLUDE": 1, "AGGREGATE": 2}
OUTCOME = {"OPEN": 0, "UPHELD": 1, "REVISED": 2, "DISMISSED": 3, "MOOT": 4}


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def percentile(values: Sequence[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * p
    low = int(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def private_key(name: str) -> str:
    return (ROOT / "network" / "secrets" / f"{name}.key").read_text(encoding="utf-8").strip()


@dataclass
class TxMetric:
    campaign_tag: str
    scenario: str
    validators: int
    clients: int
    repetition: int
    round_id: int
    phase: str
    tx_index: int
    tx_hash: str
    sender: str
    gas_used: int
    calldata_bytes: int
    block_number: int
    latency_ms: float
    status: int


@dataclass
class RoundMetric:
    campaign_tag: str
    scenario: str
    validators: int
    clients: int
    repetition: int
    round_id: int
    expected_terminal: str
    actual_terminal: str
    invariant_ok: bool
    corrected: bool
    retries_used: int
    epoch: int
    challenge_count: int
    total_ms: float
    challenge_wait_ms: float
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
    retry_budget: int
    flood_count: int
    flood_parallelism: int
    network_rtt_ms: int
    affected_decisions: int
    faulty_replacements: int
    last_challenge_block: int
    first_resolution_block: int
    last_resolution_block: int
    finalization_block: int
    resolution_block_span: int
    error: str = ""


@dataclass
class AdapterMetric:
    campaign_tag: str
    scenario: str
    validators: int
    clients: int
    repetition: int
    round_id: int
    challenge_id: int
    adapter: str
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


@dataclass
class RoundData:
    client_ids: list[bytes]
    updates: list[np.ndarray]
    update_hashes: list[bytes]
    smt_depth: int

    @classmethod
    def generate(cls, clients: int, update_dim: int, seed: int, smt_depth: int) -> "RoundData":
        rng = np.random.default_rng(seed)
        client_ids = [sha256(b"ContestFL:client" + i.to_bytes(8, "big")) for i in range(clients)]
        updates = [rng.integers(-32_768, 32_767, size=update_dim, dtype=np.int32) for _ in range(clients)]
        update_hashes = [sha256(update.tobytes(order="C")) for update in updates]
        return cls(client_ids, updates, update_hashes, smt_depth)

    @property
    def submissions(self) -> dict[bytes, bytes]:
        return dict(zip(self.client_ids, self.update_hashes))

    def trees(self, states: Sequence[int]) -> tuple[SparseMerkleMap, SparseMerkleMap, SparseMerkleMap]:
        submission = SparseMerkleMap(self.smt_depth)
        admitted = SparseMerkleMap(self.smt_depth)
        included = SparseMerkleMap(self.smt_depth)
        for client_id, update_hash, state in zip(self.client_ids, self.update_hashes, states):
            submission.set(client_id, update_hash)
            if state >= 2:
                admitted.set(client_id, b"\x01")
            if state == 3:
                included.set(client_id, b"\x01")
        return submission, admitted, included

    def roots(self, states: Sequence[int]) -> tuple[bytes, bytes, bytes]:
        return tuple(tree.root for tree in self.trees(states))

    def custom_trees(
        self, *, admitted_indices: set[int], included_indices: set[int]
    ) -> tuple[SparseMerkleMap, SparseMerkleMap, SparseMerkleMap]:
        submission = SparseMerkleMap(self.smt_depth)
        admitted = SparseMerkleMap(self.smt_depth)
        included = SparseMerkleMap(self.smt_depth)
        for index, (client_id, update_hash) in enumerate(zip(self.client_ids, self.update_hashes)):
            submission.set(client_id, update_hash)
            if index in admitted_indices:
                admitted.set(client_id, b"\x01")
            if index in included_indices:
                included.set(client_id, b"\x01")
        return submission, admitted, included

    def checkpoint(self, states: Sequence[int]) -> bytes:
        selected = [update for update, state in zip(self.updates, states) if state == 3]
        if not selected:
            return sha256(b"ContestFL:empty-checkpoint")
        accumulator = np.sum(np.stack(selected), axis=0, dtype=np.int64)
        return sha256(
            b"ContestFL:canonical-aggregate"
            + len(selected).to_bytes(8, "big")
            + accumulator.tobytes(order="C")
        )


class TxSender:
    def __init__(self, w3: Web3, validators: int, clients: int, repetition: int, scenario: str, round_id: int, campaign_tag: str) -> None:
        self.w3 = w3
        self.campaign_tag = campaign_tag
        self.validators = validators
        self.clients = clients
        self.repetition = repetition
        self.scenario = scenario
        self.round_id = round_id
        self.metrics: list[TxMetric] = []
        self._tx_index = 0

    def send_one(self, call: Any, key: str, phase: str, gas_hint: int | None = None) -> TxMetric:
        return self.send_many([call], key, phase, gas_hint=gas_hint)[0]

    def send_many(
        self, calls: Sequence[Any], key: str, phase: str, gas_hint: int | None = None,
        max_inflight_override: int | None = None,
    ) -> list[TxMetric]:
        if not calls:
            return []
        max_inflight = max_inflight_override or int(os.getenv("MAX_INFLIGHT_PER_SENDER", "50"))
        if len(calls) > max_inflight:
            metrics: list[TxMetric] = []
            for start in range(0, len(calls), max_inflight):
                metrics.extend(
                    self.send_many(
                        calls[start : start + max_inflight], key, phase, gas_hint, max_inflight_override
                    )
                )
            return metrics
        account = Account.from_key(key)
        nonce = self.w3.eth.get_transaction_count(account.address, "pending")
        signed_transactions = []
        for offset, call in enumerate(calls):
            base = {
                "from": account.address,
                "nonce": nonce + offset,
                "chainId": self.w3.eth.chain_id,
                "gasPrice": 0,
            }
            if gas_hint is None:
                estimated = int(call.estimate_gas(base))
                base["gas"] = int(estimated * 1.25) + 40_000
            else:
                base["gas"] = gas_hint
            built = call.build_transaction(base)
            signed_transactions.append(Account.sign_transaction(built, key))

        sent: list[tuple[Any, int]] = []
        for signed in signed_transactions:
            started = time.perf_counter_ns()
            transaction_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            sent.append((transaction_hash, started))

        result = []
        for transaction_hash, started in sent:
            receipt = self.w3.eth.wait_for_transaction_receipt(transaction_hash, timeout=240)
            latency_ms = (time.perf_counter_ns() - started) / 1e6
            transaction = self.w3.eth.get_transaction(transaction_hash)
            metric = TxMetric(
                campaign_tag=self.campaign_tag,
                scenario=self.scenario,
                validators=self.validators,
                clients=self.clients,
                repetition=self.repetition,
                round_id=self.round_id,
                phase=phase,
                tx_index=self._tx_index,
                tx_hash=transaction_hash.hex(),
                sender=account.address,
                gas_used=int(receipt.gasUsed),
                calldata_bytes=len(bytes(transaction["input"])),
                block_number=int(receipt.blockNumber),
                latency_ms=latency_ms,
                status=int(receipt.status),
            )
            self._tx_index += 1
            self.metrics.append(metric)
            result.append(metric)
            if metric.status != 1:
                raise RuntimeError(f"transaction failed in phase {phase}: {metric.tx_hash}")
        return result

    def send_many_multi_sender(
        self, keyed_calls: Sequence[tuple[Any, str]], phase: str,
        gas_hint: int | None = None,
    ) -> list[TxMetric]:
        """Broadcast transactions from several accounts before waiting for receipts.

        Calls belonging to one account retain nonce order, while account groups are
        broadcast concurrently.  This avoids turning a flooding experiment into a
        single-sender nonce/RPC bottleneck and ensures that the admission load can
        actually reach the challenge window.
        """
        if not keyed_calls:
            return []

        groups: dict[str, list[tuple[int, Any, str, str]]] = {}
        for index, (call, key) in enumerate(keyed_calls):
            account = Account.from_key(key)
            groups.setdefault(account.address, []).append((index, call, key, account.address))

        signed_groups: list[list[tuple[int, Any, str, str]]] = []
        for address, items in groups.items():
            nonce = self.w3.eth.get_transaction_count(address, "pending")
            signed_group: list[tuple[int, Any, str, str]] = []
            for offset, (index, call, key, sender_address) in enumerate(items):
                base = {
                    "from": sender_address,
                    "nonce": nonce + offset,
                    "chainId": self.w3.eth.chain_id,
                    "gasPrice": 0,
                }
                if gas_hint is None:
                    estimated = int(call.estimate_gas(base))
                    base["gas"] = int(estimated * 1.25) + 40_000
                else:
                    base["gas"] = gas_hint
                built = call.build_transaction(base)
                signed = Account.sign_transaction(built, key)
                signed_group.append((index, signed, sender_address, key))
            signed_groups.append(signed_group)

        endpoint = getattr(self.w3.provider, "endpoint_uri", None)

        def broadcast_group(group: list[tuple[int, Any, str, str]]) -> list[tuple[int, Any, int, str]]:
            local_w3 = (
                Web3(Web3.HTTPProvider(endpoint, request_kwargs={"timeout": 60}))
                if endpoint else self.w3
            )
            sent_group: list[tuple[int, Any, int, str]] = []
            for index, signed, sender_address, _key in group:
                started = time.perf_counter_ns()
                transaction_hash = local_w3.eth.send_raw_transaction(signed.raw_transaction)
                sent_group.append((index, transaction_hash, started, sender_address))
            return sent_group

        sent: list[tuple[int, Any, int, str]] = []
        workers = min(len(signed_groups), 32)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = [executor.submit(broadcast_group, group) for group in signed_groups]
            for future in as_completed(futures):
                sent.extend(future.result())
        sent.sort(key=lambda item: item[0])

        result: list[TxMetric] = []
        failed: list[TxMetric] = []
        for _index, transaction_hash, started, sender_address in sent:
            receipt = self.w3.eth.wait_for_transaction_receipt(transaction_hash, timeout=240)
            latency_ms = (time.perf_counter_ns() - started) / 1e6
            transaction = self.w3.eth.get_transaction(transaction_hash)
            metric = TxMetric(
                campaign_tag=self.campaign_tag,
                scenario=self.scenario,
                validators=self.validators,
                clients=self.clients,
                repetition=self.repetition,
                round_id=self.round_id,
                phase=phase,
                tx_index=self._tx_index,
                tx_hash=transaction_hash.hex(),
                sender=sender_address,
                gas_used=int(receipt.gasUsed),
                calldata_bytes=len(bytes(transaction["input"])),
                block_number=int(receipt.blockNumber),
                latency_ms=latency_ms,
                status=int(receipt.status),
            )
            self._tx_index += 1
            self.metrics.append(metric)
            result.append(metric)
            if metric.status != 1:
                failed.append(metric)

        if failed:
            first = failed[0]
            raise RuntimeError(
                f"transaction failed in phase {phase}: {first.tx_hash} "
                f"(block={first.block_number}, failed={len(failed)}/{len(result)})"
            )
        return result


@dataclass
class Context:
    w3: Web3
    contract: Any
    logging_contract: Any
    evidence_contract: Any
    validators: int
    clients: int
    repetition: int
    scenario: str
    round_id: int
    data: RoundData
    batch_size: int
    challenge_blocks: int
    response_blocks: int
    retry_budget: int
    flood_count: int
    flood_parallelism: int
    flood_challenge_blocks: int
    affected_decisions: int
    faulty_replacements: int
    campaign_tag: str
    network_rtt_ms: int
    keys: dict[str, str]
    sender: TxSender = field(init=False)
    challenge_count: int = 0
    challenge_wait_ms: float = 0.0
    corrected: bool = False
    adapter_metrics: list[AdapterMetric] = field(default_factory=list)
    submission_metrics: dict[bytes, TxMetric] = field(default_factory=dict)
    current_states: list[int] = field(default_factory=list)
    current_trees: tuple[SparseMerkleMap, SparseMerkleMap, SparseMerkleMap] | None = None
    current_checkpoint: bytes = ZERO32
    initial_state_block: int = -1

    def __post_init__(self) -> None:
        self.sender = TxSender(self.w3, self.validators, self.clients, self.repetition, self.scenario, self.round_id, self.campaign_tag)

    def wait_challenge_window(self) -> None:
        status = self.contract.functions.getRoundStatus(self.round_id).call()
        end_block = int(status[5])
        started = time.perf_counter_ns()
        while self.w3.eth.block_number <= end_block:
            time.sleep(0.05)
        self.challenge_wait_ms += (time.perf_counter_ns() - started) / 1e6

    def wait_response_deadline(self, challenge_id: int) -> None:
        challenge = self.contract.functions.challenges(challenge_id).call()
        deadline = int(challenge[10])
        started = time.perf_counter_ns()
        while self.w3.eth.block_number <= deadline:
            time.sleep(0.05)
        self.challenge_wait_ms += (time.perf_counter_ns() - started) / 1e6

    def open_contract_round(
        self,
        states: Sequence[int],
        checkpoint: bytes | None = None,
        trees_override: tuple[SparseMerkleMap, SparseMerkleMap, SparseMerkleMap] | None = None,
    ) -> tuple[bytes, bytes, bytes, bytes]:
        self.sender.send_one(
            self.contract.functions.openRound(
                self.round_id,
                self.clients,
                self.challenge_blocks,
                self.response_blocks,
                self.retry_budget,
            ),
            self.keys["coordinator"],
            "open",
        )
        submission_calls = [
            self.contract.functions.submit(self.round_id, client_id, update_hash)
            for client_id, update_hash in zip(self.data.client_ids, self.data.update_hashes)
        ]
        submission_metrics = self.sender.send_many(submission_calls, self.keys["submitter"], "submit", gas_hint=220_000)
        self.submission_metrics = {
            client_id: metric for client_id, metric in zip(self.data.client_ids, submission_metrics)
        }
        for start in range(0, self.clients, self.batch_size):
            client_batch = self.data.client_ids[start : start + self.batch_size]
            state_batch = list(states[start : start + self.batch_size])
            self.sender.send_one(
                self.contract.functions.publishDecisions(self.round_id, client_batch, state_batch),
                self.keys["coordinator"],
                "decide",
            )
        trees = trees_override or self.data.trees(states)
        roots = tuple(tree.root for tree in trees)
        checkpoint_hash = checkpoint or self.data.checkpoint(states)
        publish_metric = self.sender.send_one(
            self.contract.functions.publishInitialState(self.round_id, *roots, checkpoint_hash),
            self.keys["coordinator"],
            "publish_initial",
        )
        self.current_states = list(states)
        self.current_trees = trees
        self.current_checkpoint = checkpoint_hash
        self.initial_state_block = publish_metric.block_number
        return (*roots, checkpoint_hash)

    def open_challenge(
        self,
        kind: str,
        client_id: bytes = ZERO32,
        claimed_state: int = 0,
        reason: str = "policy_mismatch",
        challenger_index: int = 0,
        evidence_hash: bytes | None = None,
    ) -> int:
        challenge_id = int(self.contract.functions.nextChallengeId().call())
        key_name = f"challenger{challenger_index % max(1, len([k for k in self.keys if k.startswith('challenger')]))}"
        self.sender.send_one(
            self.contract.functions.openChallenge(
                self.round_id,
                KIND[kind],
                client_id,
                claimed_state,
                sha256(reason.encode()),
                evidence_hash or sha256((reason + ":evidence").encode()),
            ),
            self.keys[key_name],
            "challenge",
        )
        self.challenge_count += 1
        return challenge_id

    def open_false_challenges_batch(self, count: int) -> list[int]:
        calls = []
        challenger_names = sorted(
            (name for name in self.keys if name.startswith("challenger")),
            key=lambda name: int(name.removeprefix("challenger")),
        )
        if not challenger_names:
            raise RuntimeError("no challenger accounts configured")

        keyed_calls: list[tuple[Any, str]] = []
        for i in range(count):
            call = self.contract.functions.openChallenge(
                self.round_id,
                KIND["ADMIT"],
                self.data.client_ids[i],
                1,
                sha256(f"false_reason_{i}".encode()),
                sha256(f"false_reason_{i}:evidence".encode()),
            )
            keyed_calls.append((call, self.keys[challenger_names[i % len(challenger_names)]]))

        # Broadcast one nonce-ordered stream per challenger account concurrently.
        # The earlier single-account implementation occasionally pushed the last
        # transactions beyond a one-block challenge window and also hit practical
        # future-nonce limits for the 100-challenge sweep.
        metrics = self.sender.send_many_multi_sender(keyed_calls, "challenge")
        self.challenge_count += count

        # Challenge identifiers are assigned by mining order, which is not the
        # original call order when several senders are active.  Recover the exact
        # client-to-challenge mapping from ChallengeOpened events so that each
        # evidence record remains bound to the correct decision instance.
        index_by_client = {client_id: index for index, client_id in enumerate(self.data.client_ids[:count])}
        mapped: list[int | None] = [None] * count
        for metric in metrics:
            receipt = self.w3.eth.get_transaction_receipt(metric.tx_hash)
            events = self.contract.events.ChallengeOpened().process_receipt(receipt)
            if len(events) != 1:
                raise RuntimeError(f"expected one ChallengeOpened event in {metric.tx_hash}")
            args = events[0]["args"]
            client_id = bytes(args["clientId"])
            if client_id not in index_by_client:
                raise RuntimeError("unexpected client in ChallengeOpened event")
            mapped[index_by_client[client_id]] = int(args["challengeId"])
        if any(challenge_id is None for challenge_id in mapped):
            raise RuntimeError("incomplete ChallengeOpened mapping")
        return [int(challenge_id) for challenge_id in mapped]

    def open_admission_challenges_batch(
        self, indices: Sequence[int], results: Sequence[AdapterResult],
        reason_prefix: str = "affected_admission",
    ) -> list[int]:
        if len(indices) != len(results):
            raise ValueError("index/result length mismatch")
        challenger_names = sorted(
            (name for name in self.keys if name.startswith("challenger")),
            key=lambda name: int(name.removeprefix("challenger")),
        )
        if not challenger_names:
            raise RuntimeError("no challenger accounts configured")

        keyed_calls: list[tuple[Any, str]] = []
        for ordinal, (index, result) in enumerate(zip(indices, results)):
            call = self.contract.functions.openChallenge(
                self.round_id,
                KIND["ADMIT"],
                self.data.client_ids[index],
                3,
                sha256(f"{reason_prefix}_{index}".encode()),
                result.evidence_hash,
            )
            keyed_calls.append(
                (call, self.keys[challenger_names[ordinal % len(challenger_names)]])
            )

        metrics = self.sender.send_many_multi_sender(keyed_calls, "challenge")
        self.challenge_count += len(indices)
        index_by_client = {self.data.client_ids[index]: position for position, index in enumerate(indices)}
        mapped: list[int | None] = [None] * len(indices)
        for metric in metrics:
            receipt = self.w3.eth.get_transaction_receipt(metric.tx_hash)
            events = self.contract.events.ChallengeOpened().process_receipt(receipt)
            if len(events) != 1:
                raise RuntimeError(f"expected one ChallengeOpened event in {metric.tx_hash}")
            args = events[0]["args"]
            client_id = bytes(args["clientId"])
            if client_id not in index_by_client:
                raise RuntimeError("unexpected client in ChallengeOpened event")
            mapped[index_by_client[client_id]] = int(args["challengeId"])
        if any(challenge_id is None for challenge_id in mapped):
            raise RuntimeError("incomplete ChallengeOpened mapping")
        return [int(challenge_id) for challenge_id in mapped]

    def resolve_many_upheld(self, challenge_ids: Sequence[int]) -> None:
        calls = [
            self.contract.functions.resolveChallenge(challenge_id, OUTCOME["UPHELD"], 0, sha256(b"ContestFL:false-challenge-upheld" + challenge_id.to_bytes(32, "big")), [])
            for challenge_id in challenge_ids
        ]
        self.sender.send_many(calls, self.keys["resolver"], "resolve")

    def resolve_many_results(self, challenge_ids: Sequence[int], results: Sequence[AdapterResult]) -> None:
        if len(challenge_ids) != len(results):
            raise ValueError("challenge/result length mismatch")
        calls = [
            self.contract.functions.resolveChallenge(
                challenge_id, OUTCOME[result.verdict], result.corrected_state,
                result.certificate_hash, []
            )
            for challenge_id, result in zip(challenge_ids, results)
        ]
        parallelism = max(1, self.flood_parallelism)
        for start in range(0, len(calls), parallelism):
            self.sender.send_many(
                calls[start : start + parallelism], self.keys["resolver"], "resolve",
                max_inflight_override=parallelism,
            )

    def resolve(
        self, challenge_id: int, outcome: str, corrected_state: int = 0,
        moot_ids: Sequence[int] = (), certificate_hash: bytes | None = None
    ) -> None:
        self.sender.send_one(
            self.contract.functions.resolveChallenge(
                challenge_id,
                OUTCOME[outcome],
                corrected_state,
                certificate_hash or sha256(b"ContestFL:certificate:" + outcome.encode() + challenge_id.to_bytes(32, "big")),
                list(moot_ids),
            ),
            self.keys["resolver"],
            "resolve",
        )
        if outcome == "REVISED":
            self.corrected = True

    def record_adapter(self, challenge_id: int, result: AdapterResult) -> None:
        self.adapter_metrics.append(
            AdapterMetric(
                campaign_tag=self.campaign_tag,
                scenario=self.scenario,
                validators=self.validators,
                clients=self.clients,
                repetition=self.repetition,
                round_id=self.round_id,
                challenge_id=challenge_id,
                adapter=result.adapter,
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
        )

    def admission_evidence(self, client_index: int, observed_state: int, policy_state: int) -> AdapterResult:
        client_id = self.data.client_ids[client_index]
        metric = self.submission_metrics[client_id]
        return AdmissionAdapter.verify(
            w3=self.w3, contract=self.contract, round_id=self.round_id,
            client_id=client_id, update_hash=self.data.update_hashes[client_index],
            submission_tx_hash=metric.tx_hash, initial_state_block=self.initial_state_block,
            observed_state=observed_state, policy_state=policy_state,
        )

    def inclusion_evidence(self, client_index: int, observed_state: int) -> AdapterResult:
        if self.current_trees is None:
            raise RuntimeError("state trees are unavailable")
        _, admitted, aggregate = self.current_trees
        return InclusionAdapter.verify(
            client_id=self.data.client_ids[client_index], admitted_tree=admitted,
            aggregate_tree=aggregate, admitted_root=admitted.root, aggregate_root=aggregate.root,
            observed_state=observed_state,
        )

    def verify_inclusion_proofs_onchain(self, client_index: int) -> None:
        if self.current_trees is None:
            raise RuntimeError("state trees are unavailable")
        client_id = self.data.client_ids[client_index]
        _, admitted, aggregate = self.current_trees
        calls = []
        for tree in (admitted, aggregate):
            proof = tree.prove(client_id)
            calls.append(
                self.evidence_contract.functions.verifySparseProofOrRevert(
                    client_id, proof.value, proof.exists, list(proof.siblings), tree.root
                )
            )
        self.sender.send_many(calls, self.keys["resolver"], "verify_evidence")

    def aggregate_evidence(self, states: Sequence[int], claimed_checkpoint: bytes) -> AdapterResult:
        if self.current_trees is None:
            raise RuntimeError("state trees are unavailable")
        aggregate_root = self.current_trees[2].root
        return AggregateAdapter.verify(
            updates=self.data.updates, states=states, claimed_checkpoint=claimed_checkpoint,
            aggregate_root=aggregate_root,
        )

    def publish_replacement(self, states: Sequence[int], checkpoint: bytes | None = None, phase: str = "replacement") -> None:
        roots = self.data.roots(states)
        checkpoint_hash = checkpoint or self.data.checkpoint(states)
        self.sender.send_one(
            self.contract.functions.publishCoordinatorReplacement(self.round_id, *roots, checkpoint_hash),
            self.keys["coordinator"],
            phase,
        )
        self.current_states = list(states)
        self.current_trees = self.data.trees(states)
        self.current_checkpoint = checkpoint_hash

    def publish_fallback(self, states: Sequence[int], checkpoint: bytes | None = None) -> None:
        roots = self.data.roots(states)
        checkpoint_hash = checkpoint or self.data.checkpoint(states)
        self.sender.send_one(
            self.contract.functions.publishResolverFallback(self.round_id, *roots, checkpoint_hash),
            self.keys["resolver"],
            "fallback",
        )
        self.current_states = list(states)
        self.current_trees = self.data.trees(states)
        self.current_checkpoint = checkpoint_hash

    def finalize(self) -> None:
        self.sender.send_one(
            self.contract.functions.finalize(self.round_id),
            self.keys["coordinator"],
            "finalize",
        )

    def expire_challenge(self, challenge_id: int) -> None:
        self.sender.send_one(
            self.contract.functions.expireChallenge(challenge_id),
            self.keys["challenger0"],
            "expire",
        )

    def abort(self, reason: str) -> None:
        self.sender.send_one(
            self.contract.functions.abortRound(self.round_id, sha256(reason.encode())),
            self.keys["resolver"],
            "abort",
        )


def scenario_logging_only(ctx: Context) -> tuple[str, bytes]:
    states = [3] * ctx.clients
    roots = ctx.data.roots(states)
    checkpoint = ctx.data.checkpoint(states)
    contract = ctx.logging_contract
    ctx.sender.send_one(contract.functions.openRound(ctx.round_id, ctx.clients), ctx.keys["coordinator"], "open")
    calls = [
        contract.functions.submit(ctx.round_id, client_id, update_hash)
        for client_id, update_hash in zip(ctx.data.client_ids, ctx.data.update_hashes)
    ]
    ctx.sender.send_many(calls, ctx.keys["submitter"], "submit", gas_hint=180_000)
    ctx.sender.send_one(contract.functions.publishState(ctx.round_id, *roots, checkpoint), ctx.keys["coordinator"], "publish_state")
    ctx.sender.send_one(contract.functions.finalize(ctx.round_id), ctx.keys["coordinator"], "finalize")
    return "FINALIZED", checkpoint


def scenario_nominal(ctx: Context) -> tuple[str, bytes]:
    states = [3] * ctx.clients
    expected = ctx.data.checkpoint(states)
    ctx.open_contract_round(states)
    ctx.wait_challenge_window()
    ctx.finalize()
    return "FINALIZED", expected


def _require_adapter(result: AdapterResult, expected_verdict: str) -> None:
    if result.verdict != expected_verdict:
        raise RuntimeError(
            f"adapter {result.adapter} returned {result.verdict}, expected {expected_verdict}: {result.detail}"
        )


def scenario_bad_admission(ctx: Context) -> tuple[str, bytes]:
    faulty = [3] * ctx.clients
    faulty[0] = 1
    corrected = [3] * ctx.clients
    expected = ctx.data.checkpoint(corrected)
    ctx.open_contract_round(faulty)
    evidence = ctx.admission_evidence(0, observed_state=1, policy_state=3)
    challenge = ctx.open_challenge(
        "ADMIT", ctx.data.client_ids[0], 3, "valid_receipt_rejected", evidence_hash=evidence.evidence_hash
    )
    ctx.record_adapter(challenge, evidence)
    _require_adapter(evidence, "REVISED")
    ctx.resolve(challenge, evidence.verdict, evidence.corrected_state, certificate_hash=evidence.certificate_hash)
    ctx.publish_replacement(corrected)
    ctx.wait_challenge_window()
    ctx.finalize()
    return "FINALIZED", expected


def scenario_bad_omission(ctx: Context) -> tuple[str, bytes]:
    faulty = [3] * ctx.clients
    faulty[0] = 2
    corrected = [3] * ctx.clients
    expected = ctx.data.checkpoint(corrected)
    ctx.open_contract_round(faulty)
    evidence = ctx.inclusion_evidence(0, observed_state=2)
    challenge = ctx.open_challenge(
        "INCLUDE", ctx.data.client_ids[0], 3, "admitted_update_omitted", evidence_hash=evidence.evidence_hash
    )
    ctx.verify_inclusion_proofs_onchain(0)
    ctx.record_adapter(challenge, evidence)
    _require_adapter(evidence, "REVISED")
    ctx.resolve(challenge, evidence.verdict, evidence.corrected_state, certificate_hash=evidence.certificate_hash)
    ctx.publish_replacement(corrected)
    ctx.wait_challenge_window()
    ctx.finalize()
    return "FINALIZED", expected


def scenario_bad_injection(ctx: Context) -> tuple[str, bytes]:
    # The decision says the last client is rejected, but the aggregate-input root
    # maliciously includes it. This exercises a non-membership proof in the
    # admitted map and a membership proof in the aggregate map.
    policy_states = [3] * ctx.clients
    policy_states[-1] = 1
    injected_states = [3] * ctx.clients
    expected = ctx.data.checkpoint(policy_states)
    faulty_checkpoint = ctx.data.checkpoint(injected_states)
    admitted_indices = set(range(ctx.clients - 1))
    included_indices = set(range(ctx.clients))
    faulty_trees = ctx.data.custom_trees(
        admitted_indices=admitted_indices, included_indices=included_indices
    )
    ctx.open_contract_round(policy_states, faulty_checkpoint, trees_override=faulty_trees)
    evidence = ctx.inclusion_evidence(ctx.clients - 1, observed_state=1)
    challenge = ctx.open_challenge(
        "INCLUDE", ctx.data.client_ids[-1], 1, "rejected_update_injected", evidence_hash=evidence.evidence_hash
    )
    ctx.verify_inclusion_proofs_onchain(ctx.clients - 1)
    ctx.record_adapter(challenge, evidence)
    _require_adapter(evidence, "REVISED")
    ctx.resolve(challenge, evidence.verdict, evidence.corrected_state, certificate_hash=evidence.certificate_hash)
    ctx.publish_replacement(policy_states, expected)
    ctx.wait_challenge_window()
    ctx.finalize()
    return "FINALIZED", expected


def scenario_bad_aggregate(ctx: Context) -> tuple[str, bytes]:
    states = [3] * ctx.clients
    expected = ctx.data.checkpoint(states)
    faulty_checkpoint = sha256(expected + b":bad-aggregate")
    ctx.open_contract_round(states, faulty_checkpoint)
    evidence = ctx.aggregate_evidence(states, faulty_checkpoint)
    challenge = ctx.open_challenge("AGGREGATE", reason="checkpoint_mismatch", evidence_hash=evidence.evidence_hash)
    ctx.record_adapter(challenge, evidence)
    _require_adapter(evidence, "REVISED")
    ctx.resolve(challenge, evidence.verdict, certificate_hash=evidence.certificate_hash)
    ctx.publish_replacement(states, expected)
    ctx.wait_challenge_window()
    ctx.finalize()
    return "FINALIZED", expected


def scenario_resolver_fallback(ctx: Context) -> tuple[str, bytes]:
    states = [3] * ctx.clients
    expected = ctx.data.checkpoint(states)
    faulty_checkpoint = sha256(expected + b":fallback-required")
    ctx.open_contract_round(states, faulty_checkpoint)
    evidence = ctx.aggregate_evidence(states, faulty_checkpoint)
    challenge = ctx.open_challenge(
        "AGGREGATE", reason="resolver_replay_mismatch", evidence_hash=evidence.evidence_hash
    )
    ctx.record_adapter(challenge, evidence)
    _require_adapter(evidence, "REVISED")
    ctx.resolve(challenge, evidence.verdict, certificate_hash=evidence.certificate_hash)
    ctx.publish_fallback(states, expected)
    ctx.finalize()
    return "FINALIZED", expected


def scenario_correction_laundering(ctx: Context) -> tuple[str, bytes]:
    faulty = [3] * ctx.clients
    faulty[0] = 1
    corrected = [3] * ctx.clients
    expected = ctx.data.checkpoint(corrected)
    ctx.open_contract_round(faulty)
    admission_evidence = ctx.admission_evidence(0, observed_state=1, policy_state=3)
    challenge = ctx.open_challenge(
        "ADMIT", ctx.data.client_ids[0], 3, "engineered_admission_fault",
        evidence_hash=admission_evidence.evidence_hash,
    )
    ctx.record_adapter(challenge, admission_evidence)
    _require_adapter(admission_evidence, "REVISED")
    ctx.resolve(
        challenge, admission_evidence.verdict, admission_evidence.corrected_state,
        certificate_hash=admission_evidence.certificate_hash,
    )
    laundered = sha256(expected + b":laundered-replacement")
    ctx.publish_replacement(corrected, laundered, phase="laundered_replacement")
    aggregate_evidence = ctx.aggregate_evidence(corrected, laundered)
    second = ctx.open_challenge(
        "AGGREGATE", reason="laundered_checkpoint", evidence_hash=aggregate_evidence.evidence_hash
    )
    ctx.record_adapter(second, aggregate_evidence)
    _require_adapter(aggregate_evidence, "REVISED")
    ctx.resolve(second, aggregate_evidence.verdict, certificate_hash=aggregate_evidence.certificate_hash)
    ctx.publish_fallback(corrected, expected)
    ctx.finalize()
    return "FINALIZED", expected


def scenario_concurrent_moot(ctx: Context) -> tuple[str, bytes]:
    faulty = [3] * ctx.clients
    faulty[0] = 1
    corrected = [3] * ctx.clients
    expected = ctx.data.checkpoint(corrected)
    descendant_fault = sha256(expected + b":descendant-fault")
    ctx.open_contract_round(faulty, descendant_fault)

    admission_evidence = ctx.admission_evidence(0, observed_state=1, policy_state=3)
    aggregate_evidence = ctx.aggregate_evidence(faulty, descendant_fault)
    start_id = int(ctx.contract.functions.nextChallengeId().call())
    calls = [
        ctx.contract.functions.openChallenge(
            ctx.round_id, KIND["ADMIT"], ctx.data.client_ids[0], 3,
            sha256(b"ancestor_admission_fault"), admission_evidence.evidence_hash,
        ),
        ctx.contract.functions.openChallenge(
            ctx.round_id, KIND["AGGREGATE"], ZERO32, 0,
            sha256(b"descendant_checkpoint_fault"), aggregate_evidence.evidence_hash,
        ),
    ]
    ctx.sender.send_many(calls, ctx.keys["challenger0"], "challenge")
    ctx.challenge_count += 2
    admission, aggregate = start_id, start_id + 1
    ctx.record_adapter(admission, admission_evidence)
    # The descendant evidence is generated but deliberately not resolved: the
    # accepted ancestor revision makes it MOOT under snapshot semantics.
    ctx.record_adapter(aggregate, aggregate_evidence)
    _require_adapter(admission_evidence, "REVISED")
    ctx.resolve(
        admission, admission_evidence.verdict, admission_evidence.corrected_state,
        moot_ids=[aggregate], certificate_hash=admission_evidence.certificate_hash,
    )
    ctx.publish_replacement(corrected, expected)
    ctx.wait_challenge_window()
    ctx.finalize()
    return "FINALIZED", expected


def scenario_challenge_flooding(ctx: Context) -> tuple[str, bytes]:
    states = [3] * ctx.clients
    expected = ctx.data.checkpoint(states)
    count = min(ctx.flood_count, ctx.clients)
    parallelism = max(1, ctx.flood_parallelism)

    # Challenge admission and challenge resolution are distinct resources.
    # Keep a dedicated, fixed minimum admission window for the flooding sweep,
    # and size the response deadline from the number of resolver batches.
    ctx.challenge_blocks = max(ctx.challenge_blocks, ctx.flood_challenge_blocks)
    ctx.response_blocks = max(ctx.response_blocks, 12, 2 * math.ceil(count / parallelism) + 8)
    ctx.open_contract_round(states)
    challenge_ids = ctx.open_false_challenges_batch(count)

    # Generate evidence and resolve in bounded chunks. The runner
    # generated all evidence before submitting the first resolution batch.
    # With large floods, the chain continued producing blocks during that
    # off-chain work and the earliest challenges could reach their response
    # deadline before the last batch was mined.  Chunking starts resolution
    # promptly while preserving the configured resolver parallelism.
    for start in range(0, len(challenge_ids), parallelism):
        chunk_ids = challenge_ids[start : start + parallelism]
        chunk_results = []
        for offset, challenge_id in enumerate(chunk_ids):
            index = start + offset
            result = ctx.admission_evidence(index, observed_state=3, policy_state=3)
            ctx.record_adapter(challenge_id, result)
            _require_adapter(result, "UPHELD")
            chunk_results.append(result)
        ctx.resolve_many_results(chunk_ids, chunk_results)

    ctx.wait_challenge_window()
    ctx.finalize()
    return "FINALIZED", expected


def scenario_affected_decisions(ctx: Context) -> tuple[str, bytes]:
    # k independently incorrect admission decisions jointly invalidate the
    # aggregate.  This measures scaling with the amount of client-level state
    # that must be revised; it does not introduce a synthetic deeper FL DAG.
    count = min(max(1, ctx.affected_decisions), ctx.clients)
    parallelism = max(1, ctx.flood_parallelism)
    ctx.challenge_blocks = max(ctx.challenge_blocks, 20)
    ctx.response_blocks = max(ctx.response_blocks, 12, 2 * math.ceil(count / parallelism) + 8)

    faulty = [3] * ctx.clients
    for index in range(count):
        faulty[index] = 1
    corrected = [3] * ctx.clients
    expected = ctx.data.checkpoint(corrected)
    ctx.open_contract_round(faulty)

    indices = list(range(count))
    results = [
        ctx.admission_evidence(index, observed_state=1, policy_state=3)
        for index in indices
    ]
    challenge_ids = ctx.open_admission_challenges_batch(indices, results)
    for challenge_id, result in zip(challenge_ids, results):
        ctx.record_adapter(challenge_id, result)
        _require_adapter(result, "REVISED")
    ctx.resolve_many_results(challenge_ids, results)
    ctx.publish_replacement(corrected, expected, phase="replacement_correct")
    ctx.wait_challenge_window()
    ctx.finalize()
    return "FINALIZED", expected


def scenario_faulty_replacement_chain(ctx: Context) -> tuple[str, bytes]:
    # The initial aggregate is faulty.  The coordinator may then publish d
    # additional faulty replacements.  Each is challenged again.  When d
    # reaches the retry budget, the resolver installs a terminal fallback.
    depth = max(0, ctx.faulty_replacements)
    if depth > ctx.retry_budget:
        raise ValueError("faulty_replacements cannot exceed retry_budget")

    states = [3] * ctx.clients
    expected = ctx.data.checkpoint(states)
    initial_faulty = sha256(expected + b":replacement-chain:initial")
    ctx.open_contract_round(states, initial_faulty)

    def challenge_current(label: str) -> None:
        evidence = ctx.aggregate_evidence(states, ctx.current_checkpoint)
        challenge_id = ctx.open_challenge(
            "AGGREGATE", reason=label, evidence_hash=evidence.evidence_hash
        )
        ctx.record_adapter(challenge_id, evidence)
        _require_adapter(evidence, "REVISED")
        ctx.resolve(
            challenge_id, evidence.verdict, certificate_hash=evidence.certificate_hash
        )

    challenge_current("replacement_chain_initial")
    for replacement_index in range(depth):
        faulty_checkpoint = sha256(
            expected
            + b":replacement-chain:faulty:"
            + replacement_index.to_bytes(4, "big")
        )
        ctx.publish_replacement(
            states, faulty_checkpoint,
            phase=f"replacement_faulty_{replacement_index + 1}",
        )
        challenge_current(f"replacement_chain_{replacement_index + 1}")

    if depth == ctx.retry_budget:
        ctx.publish_fallback(states, expected)
    else:
        ctx.publish_replacement(states, expected, phase="replacement_correct")
        ctx.wait_challenge_window()
    ctx.finalize()
    return "FINALIZED", expected


def scenario_resolver_timeout_abort(ctx: Context) -> tuple[str, bytes]:
    states = [3] * ctx.clients
    expected = ctx.data.checkpoint(states)
    faulty_checkpoint = sha256(expected + b":resolver-timeout")
    ctx.open_contract_round(states, faulty_checkpoint)
    evidence = ctx.aggregate_evidence(states, faulty_checkpoint)
    challenge = ctx.open_challenge(
        "AGGREGATE", reason="resolver_timeout", evidence_hash=evidence.evidence_hash
    )
    ctx.record_adapter(challenge, evidence)
    ctx.wait_response_deadline(challenge)
    ctx.expire_challenge(challenge)
    return "ABORTED", ZERO32


def scenario_artifact_unavailable_abort(ctx: Context) -> tuple[str, bytes]:
    states = [3] * ctx.clients
    expected = ctx.data.checkpoint(states)
    ctx.open_contract_round(states, sha256(expected + b":unavailable-artifact"))
    ctx.open_challenge("AGGREGATE", reason="required_update_unavailable")
    ctx.abort("neutral_artifact_unavailability")
    return "ABORTED", ZERO32


SCENARIOS: dict[str, Callable[[Context], tuple[str, bytes]]] = {
    "logging_only": scenario_logging_only,
    "nominal": scenario_nominal,
    "bad_admission": scenario_bad_admission,
    "bad_omission": scenario_bad_omission,
    "bad_injection": scenario_bad_injection,
    "bad_aggregate": scenario_bad_aggregate,
    "resolver_fallback": scenario_resolver_fallback,
    "correction_laundering": scenario_correction_laundering,
    "concurrent_moot": scenario_concurrent_moot,
    "challenge_flooding": scenario_challenge_flooding,
    "affected_decisions": scenario_affected_decisions,
    "faulty_replacement_chain": scenario_faulty_replacement_chain,
    "resolver_timeout_abort": scenario_resolver_timeout_abort,
    "artifact_unavailable_abort": scenario_artifact_unavailable_abort,
}


def load_contracts(w3: Web3) -> tuple[Any, Any, Any, dict[str, Any]]:
    artifact = json.loads((ROOT / "network" / "contracts.json").read_text(encoding="utf-8"))
    contest = artifact["contracts"]["ContestFLExperiment"]
    logging = artifact["contracts"]["LoggingOnly"]
    evidence = artifact["contracts"]["EvidenceVerifier"]
    return (
        w3.eth.contract(address=contest["address"], abi=contest["abi"]),
        w3.eth.contract(address=logging["address"], abi=logging["abi"]),
        w3.eth.contract(address=evidence["address"], abi=evidence["abi"]),
        artifact,
    )


def round_terminal(ctx: Context, scenario: str) -> tuple[str, int, int, bytes]:
    if scenario == "logging_only":
        values = ctx.logging_contract.functions.rounds(ctx.round_id).call()
        return ("FINALIZED" if bool(values[3]) else "INCOMPLETE", 0, 0, bytes(values[7]))
    status = ctx.contract.functions.getRoundStatus(ctx.round_id).call()
    phase = int(status[0])
    terminal = "FINALIZED" if phase == PHASE["FINALIZED"] else "ABORTED" if phase == PHASE["ABORTED"] else f"PHASE_{phase}"
    return terminal, int(status[2]), int(status[1]), bytes(status[9])


def metric_from_context(
    ctx: Context,
    expected_terminal: str,
    expected_checkpoint: bytes,
    total_ms: float,
    error: str = "",
) -> RoundMetric:
    try:
        actual_terminal, retries, epoch, checkpoint = round_terminal(ctx, ctx.scenario)
    except Exception:
        actual_terminal, retries, epoch, checkpoint = "UNKNOWN", -1, -1, ZERO32
    txs = ctx.sender.metrics
    blocks = [metric.block_number for metric in txs]
    challenge_blocks_seen = [metric.block_number for metric in txs if metric.phase == "challenge"]
    resolution_blocks_seen = [metric.block_number for metric in txs if metric.phase == "resolve"]
    finalization_blocks_seen = [metric.block_number for metric in txs if metric.phase == "finalize"]
    last_challenge_block = max(challenge_blocks_seen) if challenge_blocks_seen else -1
    first_resolution_block = min(resolution_blocks_seen) if resolution_blocks_seen else -1
    last_resolution_block = max(resolution_blocks_seen) if resolution_blocks_seen else -1
    finalization_block = max(finalization_blocks_seen) if finalization_blocks_seen else -1
    resolution_block_span = (
        finalization_block - last_challenge_block + 1
        if finalization_block >= 0 and last_challenge_block >= 0
        else 0
    )
    invariant_ok = actual_terminal == expected_terminal
    if expected_terminal == "FINALIZED":
        invariant_ok = invariant_ok and checkpoint == expected_checkpoint
    return RoundMetric(
        campaign_tag=ctx.campaign_tag,
        scenario=ctx.scenario,
        validators=ctx.validators,
        clients=ctx.clients,
        repetition=ctx.repetition,
        round_id=ctx.round_id,
        expected_terminal=expected_terminal,
        actual_terminal=actual_terminal,
        invariant_ok=invariant_ok and not error,
        corrected=ctx.corrected,
        retries_used=retries,
        epoch=epoch,
        challenge_count=ctx.challenge_count,
        total_ms=total_ms,
        challenge_wait_ms=ctx.challenge_wait_ms,
        tx_count=len(txs),
        gas_total=sum(metric.gas_used for metric in txs),
        calldata_bytes=sum(metric.calldata_bytes for metric in txs),
        first_block=min(blocks) if blocks else -1,
        last_block=max(blocks) if blocks else -1,
        block_span=(max(blocks) - min(blocks) + 1) if blocks else 0,
        update_dim=ctx.data.updates[0].size,
        batch_size=ctx.batch_size,
        challenge_blocks=ctx.challenge_blocks,
        response_blocks=ctx.response_blocks,
        retry_budget=ctx.retry_budget,
        flood_count=ctx.flood_count,
        flood_parallelism=ctx.flood_parallelism,
        network_rtt_ms=ctx.network_rtt_ms,
        affected_decisions=ctx.affected_decisions,
        faulty_replacements=ctx.faulty_replacements,
        last_challenge_block=last_challenge_block,
        first_resolution_block=first_resolution_block,
        last_resolution_block=last_resolution_block,
        finalization_block=finalization_block,
        resolution_block_span=resolution_block_span,
        error=error,
    )


def write_csv(path: Path, rows: Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    records = [vars(row) for row in rows]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all ContestFL blockchain scenarios")
    parser.add_argument("--validators", type=int, required=True)
    parser.add_argument("--clients", default="10,50")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("BATCH_SIZE", "50")))
    parser.add_argument("--challenge-blocks", type=int, default=int(os.getenv("CHALLENGE_BLOCKS", "1")))
    parser.add_argument("--response-blocks", type=int, default=int(os.getenv("RESPONSE_BLOCKS", "2")))
    parser.add_argument("--retry-budget", type=int, default=int(os.getenv("RETRY_BUDGET", "1")))
    parser.add_argument("--update-dim", type=int, default=int(os.getenv("UPDATE_DIM", "1024")))
    parser.add_argument("--smt-depth", type=int, default=32)
    parser.add_argument("--flood-count", type=int, default=int(os.getenv("FLOOD_COUNT", "20")))
    parser.add_argument("--flood-parallelism", type=int, default=int(os.getenv("FLOOD_PARALLELISM", "20")))
    parser.add_argument("--flood-challenge-blocks", type=int, default=int(os.getenv("FLOOD_CHALLENGE_BLOCKS", "10")))
    parser.add_argument("--affected-decisions", type=int, default=int(os.getenv("AFFECTED_DECISIONS", "1")))
    parser.add_argument("--faulty-replacements", type=int, default=int(os.getenv("FAULTY_REPLACEMENTS", "0")))
    parser.add_argument("--tag", default=os.getenv("CAMPAIGN_TAG", "core"))
    parser.add_argument("--network-rtt-ms", type=int, default=int(os.getenv("NETWORK_RTT_MS", "0")))
    parser.add_argument("--rpc", default=os.getenv("RPC_URL", "http://node1:8545"))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=20260803)
    args = parser.parse_args()

    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        raise RuntimeError(f"RPC unavailable: {args.rpc}")
    contract, logging_contract, evidence_contract, deployment = load_contracts(w3)
    addresses = json.loads((ROOT / "network" / "secrets" / "addresses.json").read_text(encoding="utf-8"))
    keys = {name: private_key(name) for name in addresses}

    client_counts = [int(value) for value in args.clients.split(",") if value]
    scenario_names = [value for value in args.scenarios.split(",") if value]
    unknown = set(scenario_names) - set(SCENARIOS)
    if unknown:
        raise ValueError(f"unknown scenarios: {sorted(unknown)}")

    round_rows: list[RoundMetric] = []
    transaction_rows: list[TxMetric] = []
    adapter_rows: list[AdapterMetric] = []
    tag_component = int.from_bytes(sha256(args.tag.encode())[:4], "big")
    round_id = int(time.time_ns() // 1_000_000) * 1_000_000 + args.validators * 10_000 + tag_component

    for clients in client_counts:
        for repetition in range(-args.warmup, args.rounds):
            order = list(scenario_names)
            random.Random(args.seed + clients * 1000 + repetition).shuffle(order)
            for scenario_name in order:
                round_id += 1
                data = RoundData.generate(
                    clients=clients,
                    update_dim=args.update_dim,
                    seed=args.seed + round_id,
                    smt_depth=args.smt_depth,
                )
                context = Context(
                    w3=w3,
                    contract=contract,
                    logging_contract=logging_contract,
                    evidence_contract=evidence_contract,
                    validators=args.validators,
                    clients=clients,
                    repetition=repetition,
                    scenario=scenario_name,
                    round_id=round_id,
                    data=data,
                    batch_size=args.batch_size,
                    challenge_blocks=args.challenge_blocks,
                    response_blocks=args.response_blocks,
                    retry_budget=args.retry_budget,
                    flood_count=args.flood_count,
                    flood_parallelism=args.flood_parallelism,
                    flood_challenge_blocks=args.flood_challenge_blocks,
                    affected_decisions=args.affected_decisions,
                    faulty_replacements=args.faulty_replacements,
                    campaign_tag=args.tag,
                    network_rtt_ms=args.network_rtt_ms,
                    keys=keys,
                )
                expected_terminal = (
                    "ABORTED"
                    if scenario_name in {"artifact_unavailable_abort", "resolver_timeout_abort"}
                    else "FINALIZED"
                )
                expected_checkpoint = ZERO32
                started = time.perf_counter_ns()
                error = ""
                try:
                    expected_terminal, expected_checkpoint = SCENARIOS[scenario_name](context)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                    print(f"ERROR scenario={scenario_name} clients={clients} rep={repetition}: {exc}", flush=True)
                total_ms = (time.perf_counter_ns() - started) / 1e6
                if repetition >= 0:
                    round_rows.append(metric_from_context(context, expected_terminal, expected_checkpoint, total_ms, error))
                    transaction_rows.extend(context.sender.metrics)
                    adapter_rows.extend(context.adapter_metrics)
                print(
                    json.dumps(
                        {
                            "tag": args.tag,
                            "validators": args.validators,
                            "clients": clients,
                            "repetition": repetition,
                            "scenario": scenario_name,
                            "total_ms": round(total_ms, 3),
                            "tx": len(context.sender.metrics),
                            "error": bool(error),
                        }
                    ),
                    flush=True,
                )

    output_dir = ROOT / args.output_dir
    safe_tag = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in args.tag)
    write_csv(output_dir / f"rounds_{safe_tag}_v{args.validators}.csv", round_rows)
    write_csv(output_dir / f"transactions_{safe_tag}_v{args.validators}.csv", transaction_rows)
    write_csv(output_dir / f"adapters_{safe_tag}_v{args.validators}.csv", adapter_rows)
    metadata = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tag": args.tag,
        "validators": args.validators,
        "clients": client_counts,
        "rounds": args.rounds,
        "warmup": args.warmup,
        "scenarios": scenario_names,
        "batchSize": args.batch_size,
        "challengeBlocks": args.challenge_blocks,
        "responseBlocks": args.response_blocks,
        "retryBudget": args.retry_budget,
        "updateDim": args.update_dim,
        "smtDepth": args.smt_depth,
        "floodCount": args.flood_count,
        "floodParallelism": args.flood_parallelism,
        "floodChallengeBlocks": args.flood_challenge_blocks,
        "affectedDecisions": args.affected_decisions,
        "faultyReplacements": args.faulty_replacements,
        "networkRttMs": args.network_rtt_ms,
        "chainId": w3.eth.chain_id,
        "clientVersion": w3.client_version,
        "deployment": deployment,
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    (output_dir / f"metadata_{safe_tag}_v{args.validators}.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    failures = [row for row in round_rows if not row.invariant_ok]
    print(json.dumps({"output": str(output_dir), "rounds": len(round_rows), "failures": len(failures)}, indent=2))
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
