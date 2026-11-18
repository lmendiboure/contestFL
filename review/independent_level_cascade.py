"""Independent *off-chain* level-cascade auditor for the fixed-schema benchmark.

This is not a second on-chain protocol. It deliberately shares the Besu ledger,
its challenge rules, deadlines, and resolver trust boundary with ContestFL so
that only the revision/audit policy changes. It does not call the ContestFL
causal-chain evaluator or reuse RoundData.trees/checkpoint to decide validity.

At each *actually published* candidate snapshot, inspect every admission key,
then every inclusion key, and finally replay the canonical aggregate. No future
snapshot is inspected. Audit full levels after a revision, rather than following
only the challenged key's causal descendants.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from typing import Sequence

import numpy as np
from bench.smt import SparseMerkleMap


def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


@dataclass(frozen=True)
class Finding:
    kind: str
    client_id: bytes
    corrected_state: int


@dataclass(frozen=True)
class Audit:
    finding: Finding | None
    verified_keys: int
    admission_checks: int
    inclusion_checks: int
    aggregate_checks: int
    reconstructed_roots: tuple[bytes, bytes, bytes]
    reconstructed_checkpoint: bytes
    cpu_ms: float
    wall_ms: float


class LevelCascadeAuditor:
    """Stateless re-audit per level with independent root/aggregate construction.

    Benchmark workload defines all submitted client updates as admissible and
    includable. Correctness is not generalized to arbitrary FL policies.
    """

    def __init__(self, client_ids: Sequence[bytes], updates: Sequence[np.ndarray],
                 update_hashes: Sequence[bytes], smt_depth: int) -> None:
        self.ids = tuple(client_ids)
        self.updates = tuple(updates)
        self.hashes = tuple(update_hashes)
        self.depth = smt_depth
        if not self.ids or len(self.ids) != len(self.updates) or len(self.ids) != len(self.hashes):
            raise ValueError('invalid client/update dimensions')
        if len(set(self.ids)) != len(self.ids):
            raise ValueError('non-unique client IDs')
        for u, h in zip(self.updates, self.hashes):
            if sha256(u.tobytes(order='C')) != h:
                raise ValueError('update bytes do not match submitted commitment')

    def audit(self, states: Sequence[int], roots: Sequence[bytes], checkpoint: bytes) -> Audit:
        if len(states) != len(self.ids) or len(roots) != 3:
            raise ValueError('invalid snapshot dimensions')
        start_wall = time.perf_counter_ns()
        start_cpu = time.process_time_ns()
        submission = SparseMerkleMap(self.depth)
        admission = SparseMerkleMap(self.depth)
        inclusion = SparseMerkleMap(self.depth)
        first_bad_admit: bytes | None = None
        first_bad_include: bytes | None = None
        # Rebuild commitments without invoking the ContestFL experiment's root helpers.
        for cid, commit, state in zip(self.ids, self.hashes, states):
            if state not in (1, 2, 3):
                raise ValueError('illegal decision state')
            submission.set(cid, commit)
            if state in (2, 3):
                admission.set(cid, b'\x01')
            else:
                first_bad_admit = first_bad_admit or cid
            if state == 3:
                inclusion.set(cid, b'\x01')
            elif state == 2:
                first_bad_include = first_bad_include or cid
        expected_roots = (submission.root, admission.root, inclusion.root)
        if tuple(roots) != expected_roots:
            raise ValueError('published roots do not bind observed decisions')
        selected = [u for u, s in zip(self.updates, states) if s == 3]
        if selected:
            accumulator = np.sum(np.stack(selected), axis=0, dtype=np.int64)
            expected_cp = sha256(b'ContestFL:canonical-aggregate'
                                 + len(selected).to_bytes(8, 'big')
                                 + accumulator.tobytes(order='C'))
        else:
            expected_cp = sha256(b'ContestFL:empty-checkpoint')
        if first_bad_admit is not None:
            finding = Finding('ADMIT', first_bad_admit, 2)
        elif first_bad_include is not None:
            finding = Finding('INCLUDE', first_bad_include, 3)
        elif checkpoint != expected_cp:
            finding = Finding('AGGREGATE', bytes(32), 0)
        else:
            finding = None
        return Audit(
            finding=finding, verified_keys=2*len(self.ids)+1,
            admission_checks=len(self.ids), inclusion_checks=len(self.ids),
            aggregate_checks=1, reconstructed_roots=expected_roots,
            reconstructed_checkpoint=expected_cp,
            cpu_ms=(time.process_time_ns()-start_cpu)/1e6,
            wall_ms=(time.perf_counter_ns()-start_wall)/1e6,
        )
