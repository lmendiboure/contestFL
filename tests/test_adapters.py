import unittest
from types import SimpleNamespace

import numpy as np

from bench.adapters import AdmissionAdapter, AggregateAdapter, InclusionAdapter
from bench.smt import SparseMerkleMap


class _Call:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


class _Functions:
    def __init__(self, value):
        self.value = value

    def submissionHash(self, *_args):
        return _Call(self.value)


class _Eth:
    def __init__(self, receipt):
        self.receipt = receipt

    def get_transaction_receipt(self, _tx_hash):
        return self.receipt


class AdapterTest(unittest.TestCase):
    def test_admission_receipt_revises_wrong_rejection(self):
        update_hash = b"u" * 32
        w3 = SimpleNamespace(eth=_Eth(SimpleNamespace(status=1, blockNumber=7)))
        contract = SimpleNamespace(functions=_Functions(update_hash))
        result = AdmissionAdapter.verify(
            w3=w3,
            contract=contract,
            round_id=1,
            client_id=b"c" * 32,
            update_hash=update_hash,
            submission_tx_hash="0x01",
            initial_state_block=8,
            observed_state=1,
            policy_state=3,
        )
        self.assertEqual(result.verdict, "REVISED")
        self.assertEqual(result.corrected_state, 3)
        self.assertTrue(result.valid_evidence)

    def test_inclusion_proves_omission(self):
        key = b"k" * 32
        admitted = SparseMerkleMap(16)
        aggregate = SparseMerkleMap(16)
        admitted.set(key, b"\x01")
        result = InclusionAdapter.verify(
            client_id=key,
            admitted_tree=admitted,
            aggregate_tree=aggregate,
            admitted_root=admitted.root,
            aggregate_root=aggregate.root,
            observed_state=2,
        )
        self.assertEqual(result.verdict, "REVISED")
        self.assertEqual(result.corrected_state, 3)

    def test_inclusion_proves_injection(self):
        key = b"k" * 32
        admitted = SparseMerkleMap(16)
        aggregate = SparseMerkleMap(16)
        aggregate.set(key, b"\x01")
        result = InclusionAdapter.verify(
            client_id=key,
            admitted_tree=admitted,
            aggregate_tree=aggregate,
            admitted_root=admitted.root,
            aggregate_root=aggregate.root,
            observed_state=1,
        )
        self.assertEqual(result.verdict, "REVISED")
        self.assertEqual(result.corrected_state, 1)

    def test_aggregate_replay_detects_false_checkpoint(self):
        updates = [np.array([1, 2], dtype=np.int32), np.array([3, 4], dtype=np.int32)]
        result = AggregateAdapter.verify(
            updates=updates,
            states=[3, 3],
            claimed_checkpoint=b"x" * 32,
            aggregate_root=b"r" * 32,
        )
        self.assertEqual(result.verdict, "REVISED")
        self.assertEqual(result.artifact_bytes, 16)


if __name__ == "__main__":
    unittest.main()
