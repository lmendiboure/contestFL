"""Pure, dependency-free plan for the multi-epoch reviewer causal-chain test."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

WRONG_AGGREGATE_DOMAIN = b"ContestFL:chain:wrong-aggregate:v4"

@dataclass(frozen=True)
class Step:
    kind: str
    observed_state: int
    corrected_state: int
    prior_epoch: int
    activated: str


def chain_plan() -> tuple[Step, ...]:
    """Pure protocol plan. Only compressed experimental state is claimed."""
    return (
        Step("ADMIT", 1, 2, 0, "inclusion_available"),
        Step("INCLUDE", 2, 3, 1, "aggregate_input_changed"),
        Step("AGGREGATE", 0, 0, 2, "checkpoint_corrected"),
    )


def candidate(states: list[int], stage: int, data: Any) -> tuple[list[int], bytes]:
    """Stage 0: wrong admission; 1: wrong inclusion; 2: wrong aggregate; 3: correct."""
    if stage not in range(4):
        raise ValueError("stage must be 0..3")
    s = list(states)
    s[0] = (1, 2, 3, 3)[stage]
    hash_value = data.checkpoint(s)
    if stage == 2:
        hash_value = hashlib.sha256(hash_value + WRONG_AGGREGATE_DOMAIN).digest()
    return s, hash_value


def verify_plan(data: Any) -> None:
    """Validate distinct *published states*, not distinct aggregate hashes.

    The canonical aggregate only commits to included clients (state 3).
    ADMIT 1 -> 2 changes the admission Merkle root, but it must NOT change
    the aggregate hash: both states exclude the client from aggregation.
    Publication identity therefore includes all three roots and the checkpoint.
    """
    if len(data.client_ids) < 2:
        raise ValueError("chain requires at least two clients")
    correct = [3] * len(data.client_ids)
    publications = []
    for stage in range(4):
        states, checkpoint = candidate(correct, stage, data)
        roots = tuple(data.roots(states))
        if len(roots) != 3 or any(len(x) != 32 for x in (*roots, checkpoint)):
            raise AssertionError("invalid commitment lengths")
        if any(x == bytes(32) for x in (*roots, checkpoint)):
            raise AssertionError("zero publication commitment")
        publications.append((states, roots, checkpoint))
    # ADMIT: a rejected client becomes admitted, but still excluded.  Only the
    # admission root changes; requiring a different checkpoint was a v4 bug.
    a, b, c, final = publications
    if not (a[2] == b[2] and a[1][0] == b[1][0]
            and a[1][1] != b[1][1] and a[1][2] == b[1][2]):
        raise AssertionError("ADMIT transition changed the wrong commitments")
    # INCLUDE: the admitted client enters the aggregation input.
    if not (b[1][0] == c[1][0] and b[1][1] == c[1][1]
            and b[1][2] != c[1][2] and b[2] != data.checkpoint(c[0])):
        raise AssertionError("INCLUDE transition has inconsistent commitments")
    # AGGREGATE: the published inclusion set remains identical; only its
    # intentionally incorrect aggregate checkpoint is corrected.
    if not (c[1] == final[1] and c[2] != final[2]
            and final[2] == data.checkpoint(correct)):
        raise AssertionError("AGGREGATE transition has inconsistent commitments")
    if any(
        (*publications[i][1], publications[i][2]) ==
        (*publications[i + 1][1], publications[i + 1][2])
        for i in range(3)
    ):
        raise AssertionError("successive published commitments must differ")
