import hashlib
import unittest

from bench.smt import SparseMerkleMap


class SparseMerkleMapTest(unittest.TestCase):
    def test_membership_and_non_membership(self):
        tree = SparseMerkleMap(depth=16)
        key_a = hashlib.sha256(b"a").digest()
        key_b = hashlib.sha256(b"b").digest()
        tree.set(key_a, b"value-a")
        root = tree.root
        self.assertTrue(tree.verify(key_a, tree.prove(key_a), root))
        self.assertTrue(tree.verify(key_b, tree.prove(key_b), root))
        self.assertFalse(tree.prove(key_b).exists)

    def test_root_changes(self):
        tree = SparseMerkleMap(depth=16)
        key = hashlib.sha256(b"key").digest()
        before = tree.root
        tree.set(key, b"value")
        self.assertNotEqual(before, tree.root)

    def test_truncated_path_collision_is_rejected(self):
        tree = SparseMerkleMap(depth=8)
        key_a = bytes.fromhex("aa" + "00" * 31)
        key_b = bytes.fromhex("aa" + "ff" * 31)
        tree.set(key_a, b"value-a")
        with self.assertRaisesRegex(ValueError, "path collision"):
            tree.set(key_b, b"value-b")

    def test_removal_releases_truncated_path(self):
        tree = SparseMerkleMap(depth=8)
        key_a = bytes.fromhex("aa" + "00" * 31)
        key_b = bytes.fromhex("aa" + "ff" * 31)
        tree.set(key_a, b"value-a")
        tree.set(key_a, b"")
        tree.set(key_b, b"value-b")
        self.assertTrue(tree.verify(key_b, tree.prove(key_b), tree.root))


if __name__ == "__main__":
    unittest.main()
