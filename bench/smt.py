from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


@dataclass(frozen=True)
class SparseProof:
    siblings: Tuple[bytes, ...]
    exists: bool
    value: bytes


class SparseMerkleMap:
    """Small deterministic sparse-Merkle map used by the benchmark.

    Keys are bytes32. Values are arbitrary bytes and are domain-separated.
    The implementation is intentionally dependency-free and supports both
    membership and non-membership proofs. A depth smaller than 256 truncates the
    key-derived path. The map therefore rejects path collisions explicitly
    instead of silently overwriting a leaf. The 32-bit depth is an evaluated
    benchmark configuration, not a collision-free production recommendation.
    """

    def __init__(self, depth: int = 32) -> None:
        if depth < 8 or depth > 256:
            raise ValueError("depth must be in [8, 256]")
        self.depth = depth
        self._values: Dict[bytes, bytes] = {}
        self._path_owner: Dict[int, bytes] = {}
        self._zero = [sha256(b"ContestFL:empty-leaf")]
        for _ in range(depth):
            z = self._zero[-1]
            self._zero.append(sha256(b"ContestFL:node" + z + z))

    @staticmethod
    def _leaf(key: bytes, value: bytes) -> bytes:
        return sha256(b"ContestFL:leaf" + key + sha256(value))

    def _index(self, key: bytes) -> int:
        if len(key) != 32:
            raise ValueError("keys must be bytes32")
        return int.from_bytes(key, "big") >> (256 - self.depth)

    def set(self, key: bytes, value: bytes) -> None:
        index = self._index(key)
        owner = self._path_owner.get(index)
        if value:
            if owner is not None and owner != key:
                raise ValueError(
                    f"sparse-Merkle path collision at depth {self.depth}: "
                    f"{owner.hex()} and {key.hex()} map to index {index}"
                )
            self._path_owner[index] = key
            self._values[key] = value
        else:
            self._values.pop(key, None)
            if owner == key:
                self._path_owner.pop(index, None)

    def update(self, entries: Iterable[Tuple[bytes, bytes]]) -> None:
        for key, value in entries:
            self.set(key, value)

    def _levels(self) -> list[Dict[int, bytes]]:
        current: Dict[int, bytes] = {
            self._index(key): self._leaf(key, value)
            for key, value in self._values.items()
        }
        levels = [current]
        for height in range(self.depth):
            parent: Dict[int, bytes] = {}
            for idx in {i >> 1 for i in current}:
                left = current.get(idx << 1, self._zero[height])
                right = current.get((idx << 1) | 1, self._zero[height])
                parent[idx] = sha256(b"ContestFL:node" + left + right)
            current = parent
            levels.append(current)
        return levels

    @property
    def root(self) -> bytes:
        levels = self._levels()
        return levels[-1].get(0, self._zero[self.depth])

    def prove(self, key: bytes) -> SparseProof:
        levels = self._levels()
        idx = self._index(key)
        siblings = []
        for height in range(self.depth):
            siblings.append(levels[height].get(idx ^ 1, self._zero[height]))
            idx >>= 1
        value = self._values.get(key, b"")
        return SparseProof(tuple(siblings), key in self._values, value)

    def verify(self, key: bytes, proof: SparseProof, root: bytes) -> bool:
        idx = self._index(key)
        node = self._leaf(key, proof.value) if proof.exists else self._zero[0]
        for sibling in proof.siblings:
            if idx & 1:
                node = sha256(b"ContestFL:node" + sibling + node)
            else:
                node = sha256(b"ContestFL:node" + node + sibling)
            idx >>= 1
        return node == root
