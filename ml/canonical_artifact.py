from __future__ import annotations

import json
import struct
from typing import Any, Sequence

import numpy as np

MAGIC = b"CFLUPD1\x00"


def canonicalize_delta(
    names: Sequence[str],
    initial: Sequence[np.ndarray],
    trained: Sequence[np.ndarray],
    scale: int,
) -> tuple[bytes, np.ndarray, dict[str, Any]]:
    """Encode a model delta as a deterministic little-endian int32 artifact."""
    if scale <= 0:
        raise ValueError("scale must be positive")
    if not (len(names) == len(initial) == len(trained)):
        raise ValueError("name/parameter length mismatch")
    chunks: list[np.ndarray] = []
    tensors: list[dict[str, Any]] = []
    offset = 0
    for name, before, after in zip(names, initial, trained):
        before64 = np.asarray(before, dtype=np.float64)
        after64 = np.asarray(after, dtype=np.float64)
        if before64.shape != after64.shape:
            raise ValueError(f"shape mismatch for {name}")
        quantized64 = np.rint((after64 - before64) * scale)
        if np.any(quantized64 > np.iinfo(np.int32).max) or np.any(quantized64 < np.iinfo(np.int32).min):
            raise OverflowError(f"fixed-point overflow for {name}")
        quantized = quantized64.astype("<i4", copy=False).reshape(-1)
        chunks.append(quantized)
        tensors.append(
            {
                "name": str(name),
                "shape": list(before64.shape),
                "offset": offset,
                "length": int(quantized.size),
            }
        )
        offset += int(quantized.size)
    flat = np.concatenate(chunks).astype("<i4", copy=False) if chunks else np.empty(0, dtype="<i4")
    header = {
        "format": "ContestFL-fixed-point-update-v1",
        "scale": int(scale),
        "integerDtype": "int32-le",
        "tensorOrder": "state_dict-insertion-order",
        "values": int(flat.size),
        "tensors": tensors,
    }
    encoded_header = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    artifact = MAGIC + struct.pack(">I", len(encoded_header)) + encoded_header + flat.tobytes(order="C")
    return artifact, flat, header


def parse_artifact(payload: bytes) -> tuple[np.ndarray, dict[str, Any]]:
    """Parse and validate a canonical fixed-point update artifact."""
    if not payload.startswith(MAGIC):
        raise ValueError("invalid artifact magic")
    cursor = len(MAGIC)
    if len(payload) < cursor + 4:
        raise ValueError("truncated artifact header length")
    header_length = struct.unpack(">I", payload[cursor : cursor + 4])[0]
    cursor += 4
    if len(payload) < cursor + header_length:
        raise ValueError("truncated artifact header")
    header = json.loads(payload[cursor : cursor + header_length].decode("utf-8"))
    cursor += header_length
    body = payload[cursor:]
    if len(body) % 4 != 0:
        raise ValueError("misaligned int32 artifact body")
    values = np.frombuffer(body, dtype="<i4").copy()
    if header.get("format") != "ContestFL-fixed-point-update-v1":
        raise ValueError("unsupported artifact format")
    if header.get("integerDtype") != "int32-le":
        raise ValueError("unsupported integer encoding")
    if int(header["values"]) != int(values.size):
        raise ValueError("artifact length mismatch")
    expected_offset = 0
    for tensor in header.get("tensors", []):
        if int(tensor["offset"]) != expected_offset:
            raise ValueError("non-contiguous tensor offsets")
        expected_offset += int(tensor["length"])
    if expected_offset != values.size:
        raise ValueError("tensor schema does not cover artifact body")
    return values, header


def reconstruct_delta(values: np.ndarray, header: dict[str, Any]) -> dict[str, np.ndarray]:
    """Reconstruct named floating-point tensors from a parsed artifact."""
    scale = int(header["scale"])
    if scale <= 0:
        raise ValueError("invalid fixed-point scale")
    result: dict[str, np.ndarray] = {}
    for tensor in header["tensors"]:
        offset = int(tensor["offset"])
        length = int(tensor["length"])
        shape = tuple(int(item) for item in tensor["shape"])
        result[str(tensor["name"])] = (
            values[offset : offset + length].astype(np.float64) / scale
        ).reshape(shape)
    return result
