#!/usr/bin/env python3
"""One-round Flower/MNIST -> fixed-point artifact -> ContestFL replay demo.

This is an applicability experiment, not a performance benchmark. Flower
clients train the same small MNIST network on disjoint, equal-sized partitions.
Each client exports its model delta through a deterministic fixed-point codec.
The script deliberately publishes a faulty aggregate checkpoint, obtains a
REVISED verdict from deterministic replay, installs the corrected replacement,
and checks that only the replayed checkpoint is finalized.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import socket
import time
import traceback
from pathlib import Path
from typing import Any, Sequence

import flwr as fl
import numpy as np
import torch
from flwr.common import ndarrays_to_parameters, parameters_to_ndarrays
from torch import nn
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms
from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from bench.adapters import AggregateAdapter  # noqa: E402
from bench.run_scenarios import TxSender, private_key, sha256  # noqa: E402
from bench.smt import SparseMerkleMap  # noqa: E402


def seed_everything(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)


class MnistNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Flatten(),
            nn.Linear(28 * 28, 32),
            nn.ReLU(),
            nn.Linear(32, 10),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)


def model_ndarrays(model: nn.Module) -> list[np.ndarray]:
    return [tensor.detach().cpu().numpy().copy() for tensor in model.state_dict().values()]


def set_model_ndarrays(model: nn.Module, arrays: Sequence[np.ndarray]) -> None:
    state = model.state_dict()
    if len(state) != len(arrays):
        raise ValueError("parameter count mismatch")
    rebuilt = {
        name: torch.from_numpy(np.asarray(array)).to(dtype=tensor.dtype)
        for (name, tensor), array in zip(state.items(), arrays)
    }
    model.load_state_dict(rebuilt, strict=True)


from ml.canonical_artifact import canonicalize_delta, parse_artifact  # noqa: E402

def load_partition(data_dir: str, client_id: int, clients: int, samples_per_client: int) -> Subset:
    dataset = datasets.MNIST(
        data_dir,
        train=True,
        download=False,
        transform=transforms.ToTensor(),
    )
    start = client_id * samples_per_client
    stop = start + samples_per_client
    if stop > len(dataset):
        raise ValueError("requested partition exceeds MNIST train split")
    return Subset(dataset, list(range(start, stop)))


def train_model(model: nn.Module, loader: DataLoader, epochs: int, lr: float) -> tuple[float, float]:
    model.train()
    optimizer = torch.optim.SGD(model.parameters(), lr=lr)
    criterion = nn.CrossEntropyLoss()
    total_loss = 0.0
    correct = 0
    total = 0
    for _ in range(epochs):
        for images, labels in loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * int(labels.size(0))
            correct += int((logits.argmax(dim=1) == labels).sum().item())
            total += int(labels.size(0))
    return total_loss / max(total, 1), correct / max(total, 1)


class ArtifactClient(fl.client.NumPyClient):
    def __init__(
        self, client_id: int, clients: int, samples_per_client: int, data_dir: str,
        output_dir: str, scale: int, seed: int, local_epochs: int, learning_rate: float,
    ) -> None:
        self.client_id = client_id
        self.clients = clients
        self.samples_per_client = samples_per_client
        self.data_dir = data_dir
        self.output_dir = Path(output_dir)
        self.scale = scale
        self.seed = seed
        self.local_epochs = local_epochs
        self.learning_rate = learning_rate
        seed_everything(seed + client_id)
        self.model = MnistNet()
        self.names = list(self.model.state_dict().keys())

    def get_parameters(self, config: dict[str, Any]) -> list[np.ndarray]:
        return model_ndarrays(self.model)

    def fit(self, parameters: list[np.ndarray], config: dict[str, Any]):
        seed_everything(self.seed + self.client_id)
        set_model_ndarrays(self.model, parameters)
        initial = [np.asarray(item).copy() for item in parameters]
        partition = load_partition(
            self.data_dir, self.client_id, self.clients, self.samples_per_client
        )
        loader = DataLoader(partition, batch_size=64, shuffle=False, num_workers=0)
        loss, accuracy = train_model(
            self.model, loader, self.local_epochs, self.learning_rate
        )
        trained = model_ndarrays(self.model)
        artifact, flat, header = canonicalize_delta(
            self.names, initial, trained, self.scale
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = self.output_dir / f"client_{self.client_id}.cflupd"
        artifact_path.write_bytes(artifact)
        metadata = {
            "clientId": self.client_id,
            "samples": len(partition),
            "loss": loss,
            "accuracy": accuracy,
            "artifactBytes": len(artifact),
            "artifactSha256": hashlib.sha256(artifact).hexdigest(),
            "fixedPointValues": int(flat.size),
            "scale": self.scale,
            "header": header,
        }
        (self.output_dir / f"client_{self.client_id}.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        return trained, len(partition), {
            "train_loss": float(loss),
            "train_accuracy": float(accuracy),
            "artifact_sha256": metadata["artifactSha256"],
        }

    def evaluate(self, parameters: list[np.ndarray], config: dict[str, Any]):
        return 0.0, 0, {}


class CaptureFedAvg(fl.server.strategy.FedAvg):
    def __init__(self, output_dir: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.output_dir = Path(output_dir)

    def aggregate_fit(self, server_round, results, failures):
        aggregated = super().aggregate_fit(server_round, results, failures)
        if aggregated is not None:
            parameters, metrics = aggregated
            arrays = parameters_to_ndarrays(parameters)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            np.savez(self.output_dir / "flower_aggregate.npz", *arrays)
            (self.output_dir / "flower_metrics.json").write_text(
                json.dumps({"serverRound": server_round, "metrics": metrics}, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        return aggregated


def server_process(address: str, clients: int, output_dir: str, seed: int) -> None:
    seed_everything(seed)
    initial_model = MnistNet()
    initial = model_ndarrays(initial_model)
    strategy = CaptureFedAvg(
        output_dir,
        fraction_fit=1.0,
        fraction_evaluate=0.0,
        min_evaluate_clients=0,
        min_fit_clients=clients,
        min_available_clients=clients,
        initial_parameters=ndarrays_to_parameters(initial),
    )
    fl.server.start_server(
        server_address=address,
        config=fl.server.ServerConfig(num_rounds=1, round_timeout=300.0),
        strategy=strategy,
    )


def client_process(
    address: str, client_id: int, clients: int, samples_per_client: int,
    data_dir: str, output_dir: str, scale: int, seed: int, local_epochs: int,
    learning_rate: float,
) -> None:
    client = ArtifactClient(
        client_id, clients, samples_per_client, data_dir, output_dir,
        scale, seed, local_epochs, learning_rate,
    )
    fl.client.start_client(
        server_address=address,
        client=client.to_client(),
        insecure=True,
        max_retries=20,
        max_wait_time=60.0,
    )


def wait_until_block(w3: Web3, target_exclusive: int, timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    while int(w3.eth.block_number) <= target_exclusive:
        if time.monotonic() > deadline:
            raise TimeoutError("challenge window did not close")
        time.sleep(0.2)


def commit_to_contestfl(
    rpc: str, client_updates: Sequence[np.ndarray], artifact_hashes: Sequence[bytes],
    checkpoint: bytes, smt_depth: int, challenge_blocks: int,
) -> dict[str, Any]:
    """Commit a faulty aggregate claim, obtain REVISED, and finalize its replacement.

    The clean replay above establishes the expected checkpoint. This function then
    deliberately publishes a different checkpoint, opens an aggregate challenge
    backed by deterministic replay evidence, resolves it as REVISED, publishes the
    corrected checkpoint, reopens the bounded challenge window, and finalizes only
    after that replacement window closes.
    """
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        raise RuntimeError(f"ContestFL RPC unavailable: {rpc}")
    deployment = json.loads((ROOT / "network" / "contracts.json").read_text(encoding="utf-8"))
    entry = deployment["contracts"]["ContestFLExperiment"]
    contract = w3.eth.contract(address=entry["address"], abi=entry["abi"])
    clients = len(client_updates)
    client_ids = [sha256(b"ContestFL:flower-client" + i.to_bytes(8, "big")) for i in range(clients)]
    states = [3] * clients

    submission = SparseMerkleMap(smt_depth)
    admitted = SparseMerkleMap(smt_depth)
    included = SparseMerkleMap(smt_depth)
    for client_id, artifact_hash in zip(client_ids, artifact_hashes):
        submission.set(client_id, artifact_hash)
        admitted.set(client_id, b"\x01")
        included.set(client_id, b"\x01")

    faulty_checkpoint = sha256(checkpoint + b":flower:bad-aggregate")
    revision_evidence = AggregateAdapter.verify(
        updates=client_updates,
        states=states,
        claimed_checkpoint=faulty_checkpoint,
        aggregate_root=included.root,
    )
    if revision_evidence.verdict != "REVISED" or not revision_evidence.valid_evidence:
        raise RuntimeError(f"expected REVISED aggregate evidence: {revision_evidence.detail}")

    round_id = int(time.time_ns() // 1_000_000) * 1_000_000 + 4242
    sender = TxSender(w3, 4, clients, 0, "flower_mnist_revised", round_id, "flower_mnist_e2e")
    coordinator = private_key("coordinator")
    submitter = private_key("submitter")
    challenger = private_key("challenger0")
    resolver = private_key("resolver")

    sender.send_one(
        contract.functions.openRound(round_id, clients, challenge_blocks, 4, 1),
        coordinator,
        "open_round",
    )
    sender.send_many(
        [
            contract.functions.submit(round_id, client_id, artifact_hash)
            for client_id, artifact_hash in zip(client_ids, artifact_hashes)
        ],
        submitter,
        "submit_artifacts",
    )
    sender.send_one(
        contract.functions.publishDecisions(round_id, client_ids, states),
        coordinator,
        "publish_decisions",
    )
    sender.send_one(
        contract.functions.publishInitialState(
            round_id, submission.root, admitted.root, included.root, faulty_checkpoint
        ),
        coordinator,
        "publish_faulty_state",
    )

    challenge_id = int(contract.functions.nextChallengeId().call())
    sender.send_one(
        contract.functions.openChallenge(
            round_id,
            2,  # DecisionKind.AGGREGATE
            b"\x00" * 32,
            0,
            sha256(b"flower-checkpoint-mismatch"),
            revision_evidence.evidence_hash,
        ),
        challenger,
        "open_aggregate_challenge",
    )
    sender.send_one(
        contract.functions.resolveChallenge(
            challenge_id,
            2,  # ChallengeOutcome.REVISED
            0,
            revision_evidence.certificate_hash,
            [],
        ),
        resolver,
        "resolve_revised",
    )
    sender.send_one(
        contract.functions.publishCoordinatorReplacement(
            round_id, submission.root, admitted.root, included.root, checkpoint
        ),
        coordinator,
        "publish_corrected_replacement",
    )
    state = contract.functions.rounds(round_id).call()
    wait_until_block(w3, int(state[9]))
    sender.send_one(contract.functions.finalize(round_id), coordinator, "finalize")

    final_state = contract.functions.rounds(round_id).call()
    final_checkpoint = bytes(final_state[17])
    challenge_state = contract.functions.challenges(challenge_id).call()
    blocks = [metric.block_number for metric in sender.metrics]
    return {
        "roundId": round_id,
        "txCount": len(sender.metrics),
        "gasTotal": sum(metric.gas_used for metric in sender.metrics),
        "calldataBytes": sum(metric.calldata_bytes for metric in sender.metrics),
        "blockSpan": max(blocks) - min(blocks) + 1,
        "faultyCheckpoint": faulty_checkpoint.hex(),
        "correctedCheckpoint": checkpoint.hex(),
        "finalCheckpoint": final_checkpoint.hex(),
        "checkpointMatches": final_checkpoint == checkpoint,
        "submissionRoot": submission.root.hex(),
        "aggregateInputRoot": included.root.hex(),
        "challengeId": challenge_id,
        "challengeOutcome": "REVISED" if int(challenge_state[-1]) == 2 else str(int(challenge_state[-1])),
        "revisionEvidence": {
            "adapter": revision_evidence.adapter,
            "verdict": revision_evidence.verdict,
            "validEvidence": revision_evidence.valid_evidence,
            "verificationMs": revision_evidence.verification_ms,
            "proofBytes": revision_evidence.proof_bytes,
            "artifactBytes": revision_evidence.artifact_bytes,
            "detail": revision_evidence.detail,
        },
        "transactions": [
            {
                "phase": metric.phase,
                "gasUsed": metric.gas_used,
                "calldataBytes": metric.calldata_bytes,
                "blockNumber": metric.block_number,
                "status": metric.status,
                "txHash": metric.tx_hash,
            }
            for metric in sender.metrics
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", type=int, default=2)
    parser.add_argument("--samples-per-client", type=int, default=512)
    parser.add_argument("--local-epochs", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--scale", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=20260806)
    parser.add_argument("--port", type=int, default=8087)
    parser.add_argument("--data-dir", default="/data")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--rpc", default=os.getenv("RPC_URL", "http://node1:8545"))
    parser.add_argument("--smt-depth", type=int, default=32)
    parser.add_argument("--challenge-blocks", type=int, default=1)
    args = parser.parse_args()
    if args.clients < 2:
        raise ValueError("at least two Flower clients are required")

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    seed_everything(args.seed)
    # Download once before processes start, avoiding concurrent dataset writes.
    datasets.MNIST(args.data_dir, train=True, download=True, transform=transforms.ToTensor())

    initial_model = MnistNet()
    initial_arrays = model_ndarrays(initial_model)
    address = f"127.0.0.1:{args.port}"
    context = mp.get_context("spawn")
    server = context.Process(target=server_process, args=(address, args.clients, str(output), args.seed))
    server.start()
    time.sleep(2.0)
    clients = [
        context.Process(
            target=client_process,
            args=(
                address, client_id, args.clients, args.samples_per_client,
                args.data_dir, str(output), args.scale, args.seed,
                args.local_epochs, args.learning_rate,
            ),
        )
        for client_id in range(args.clients)
    ]
    for process in clients:
        process.start()
    for process in clients:
        process.join(timeout=420)
        if process.exitcode != 0:
            raise RuntimeError(f"Flower client failed with exit code {process.exitcode}")
    server.join(timeout=420)
    if server.exitcode != 0:
        raise RuntimeError(f"Flower server failed with exit code {server.exitcode}")

    artifacts = [(output / f"client_{i}.cflupd").read_bytes() for i in range(args.clients)]
    parsed = [parse_artifact(payload) for payload in artifacts]
    updates = [values for values, _ in parsed]
    schemas = [header for _, header in parsed]
    if any(schema != schemas[0] for schema in schemas[1:]):
        raise RuntimeError("client artifacts do not share one canonical schema")
    artifact_hashes = [hashlib.sha256(payload).digest() for payload in artifacts]

    accumulator = np.zeros_like(updates[0], dtype=np.int64)
    for update in updates:
        accumulator += update.astype(np.int64, copy=False)
    checkpoint = sha256(
        b"ContestFL:canonical-aggregate"
        + len(updates).to_bytes(8, "big")
        + accumulator.tobytes(order="C")
    )
    aggregate_root_tree = SparseMerkleMap(args.smt_depth)
    for index, artifact_hash in enumerate(artifact_hashes):
        aggregate_root_tree.set(
            sha256(b"ContestFL:flower-client" + index.to_bytes(8, "big")), b"\x01"
        )
    replay = AggregateAdapter.verify(
        updates=updates,
        states=[3] * args.clients,
        claimed_checkpoint=checkpoint,
        aggregate_root=aggregate_root_tree.root,
    )
    if replay.verdict != "UPHELD" or not replay.valid_evidence:
        raise RuntimeError(f"deterministic replay failed: {replay.detail}")

    flower_aggregate_file = np.load(output / "flower_aggregate.npz")
    flower_aggregate = [flower_aggregate_file[key] for key in flower_aggregate_file.files]
    dequantized_mean = accumulator.astype(np.float64) / (args.scale * args.clients)
    cursor = 0
    max_abs_error = 0.0
    for initial, aggregated in zip(initial_arrays, flower_aggregate):
        count = int(np.prod(initial.shape))
        reconstructed = np.asarray(initial, dtype=np.float64) + dequantized_mean[cursor : cursor + count].reshape(initial.shape)
        max_abs_error = max(max_abs_error, float(np.max(np.abs(reconstructed - np.asarray(aggregated, dtype=np.float64)))))
        cursor += count

    chain = commit_to_contestfl(
        args.rpc, updates, artifact_hashes, checkpoint, args.smt_depth, args.challenge_blocks
    )
    report = {
        "timestampUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": socket.gethostname(),
        "flowerVersion": fl.__version__,
        "torchVersion": torch.__version__,
        "dataset": "MNIST train split",
        "model": "784-32-10 MLP",
        "clients": args.clients,
        "samplesPerClient": args.samples_per_client,
        "localEpochs": args.local_epochs,
        "fixedPointScale": args.scale,
        "valuesPerUpdate": int(updates[0].size),
        "artifactBytesPerClient": [len(payload) for payload in artifacts],
        "artifactHashes": [item.hex() for item in artifact_hashes],
        "checkpoint": checkpoint.hex(),
        "replay": {
            "verdict": replay.verdict,
            "validEvidence": replay.valid_evidence,
            "verificationMs": replay.verification_ms,
            "artifactBytes": replay.artifact_bytes,
        },
        "flowerAggregateMaxAbsErrorAfterFixedPointReconstruction": max_abs_error,
        "chain": chain,
        "success": bool(
            chain["checkpointMatches"]
            and chain["challengeOutcome"] == "REVISED"
            and replay.valid_evidence
            and max_abs_error <= (2.0 / args.scale)
        ),
    }
    (output / "FLOWER_MNIST_E2E_REPORT.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (output / "FLOWER_MNIST_E2E_REPORT.md").write_text(
        "\n".join([
            "# Flower/MNIST end-to-end ContestFL integration",
            "",
            f"- Flower clients: **{args.clients}**",
            f"- MNIST samples per client: **{args.samples_per_client}**",
            f"- Fixed-point values per update: **{updates[0].size}**",
            f"- Clean replay verdict: **{replay.verdict}**",
            f"- Disputed aggregate verdict: **{chain['challengeOutcome']}**",
            f"- Maximum reconstruction error: **{max_abs_error:.3e}**",
            f"- Faulty checkpoint differs from replay: **{chain['faultyCheckpoint'] != chain['correctedCheckpoint']}**",
            f"- Finalized checkpoint matches corrected replay: **{chain['checkpointMatches']}**",
            f"- Ledger gas: **{chain['gasTotal']}** over **{chain['txCount']}** transactions",
            "",
            "This run demonstrates the interface Flower training -> deterministic fixed-point artifact -> authenticated commitment -> faulty aggregate publication -> REVISED replay verdict -> corrected replacement -> ContestFL finalization. It is an applicability check, not a model-accuracy or throughput benchmark.",
        ]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    if not report["success"]:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
