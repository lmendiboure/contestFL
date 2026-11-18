"""Canonical model handoff for sequential, ledger-gated Flower rounds.

This module intentionally depends only on NumPy and stdlib so that model
handoff and audit invariants can be unit-tested without Docker, Besu or Flower.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Sequence

import numpy as np


def read_model(path: Path, reference: Sequence[np.ndarray]) -> list[np.ndarray]:
    """Read a checkpoint using strict param order, dtype, shape and finite checks."""
    with np.load(path, allow_pickle=False) as z:
        expected = [f"arr_{i}" for i in range(len(reference))]
        if sorted(z.files) != sorted(expected):
            raise ValueError("checkpoint tensor keys mismatch")
        arrays = [np.asarray(z[k]) for k in expected]
    for i, (v, ref) in enumerate(zip(arrays, reference)):
        if v.shape != ref.shape or v.dtype != ref.dtype or not np.all(np.isfinite(v)):
            raise ValueError(f"invalid checkpoint tensor {i}")
    return [v.copy() for v in arrays]


def write_model(path: Path, arrays: Sequence[np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for v in arrays:
        if not np.all(np.isfinite(v)):
            raise ValueError("non-finite checkpoint tensor")
    with path.open("wb") as f:
        np.savez(f, *arrays)


def model_digest(arrays: Sequence[np.ndarray]) -> str:
    """Digest includes dtype, shape and raw little-endian values."""
    h = hashlib.sha256(b"ContestFL:multiround-model:v1")
    for a in arrays:
        v = np.asarray(a)
        h.update(v.dtype.str.encode("ascii"))
        h.update(len(v.shape).to_bytes(4, "big"))
        for dim in v.shape:
            h.update(int(dim).to_bytes(8, "big"))
        h.update(v.tobytes(order="C"))
    return h.hexdigest()


def schedule(seed: int, rounds: int, faulty_rounds: Sequence[int]) -> tuple[tuple[int, str], ...]:
    if rounds < 1 or seed < 0:
        raise ValueError("positive rounds and nonnegative seed required")
    faults = set(faulty_rounds)
    if len(faults) != len(faulty_rounds) or any(x < 1 or x > rounds for x in faults):
        raise ValueError("invalid/duplicate fault rounds")
    return tuple((seed + k - 1, "bad_aggregate" if k in faults else "clean") for k in range(1, rounds + 1))


def metrics_summary(rows: list[dict]) -> dict:
    """Per-trajectory throughput; never pool rounds as independent replicates."""
    successful = [r for r in rows if r["correct_checkpoint_finalized"] and not r["error"]]
    elapsed_ms = sum(float(r["full_round_wall_ms"]) for r in rows)
    if elapsed_ms <= 0:
        return {"completed_rounds": len(successful), "elapsed_ms": elapsed_ms,
                "completed_rounds_per_hour": 0.0}
    return {"completed_rounds": len(successful), "elapsed_ms": elapsed_ms,
            "completed_rounds_per_hour": len(successful) * 3600000.0 / elapsed_ms}
