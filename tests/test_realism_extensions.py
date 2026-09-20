from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from ml.canonical_artifact import canonicalize_delta, parse_artifact, reconstruct_delta

ROOT = Path(__file__).resolve().parents[1]


class CanonicalArtifactTests(unittest.TestCase):
    def test_round_trip_is_deterministic(self) -> None:
        names = ["w", "b"]
        initial = [np.zeros((2, 2), dtype=np.float32), np.zeros((2,), dtype=np.float32)]
        trained = [
            np.asarray([[0.125, -0.5], [1.25, 0.0]], dtype=np.float32),
            np.asarray([0.25, -0.25], dtype=np.float32),
        ]
        payload1, values1, header1 = canonicalize_delta(names, initial, trained, 1_000_000)
        payload2, values2, header2 = canonicalize_delta(names, initial, trained, 1_000_000)
        self.assertEqual(payload1, payload2)
        np.testing.assert_array_equal(values1, values2)
        self.assertEqual(header1, header2)
        parsed, header = parse_artifact(payload1)
        np.testing.assert_array_equal(parsed, values1)
        rebuilt = reconstruct_delta(parsed, header)
        np.testing.assert_allclose(rebuilt["w"], trained[0], atol=5e-7)
        np.testing.assert_allclose(rebuilt["b"], trained[1], atol=5e-7)

    def test_rejects_corrupted_body(self) -> None:
        payload, _, _ = canonicalize_delta(
            ["w"], [np.zeros(1, dtype=np.float32)], [np.ones(1, dtype=np.float32)], 100
        )
        with self.assertRaises(ValueError):
            parse_artifact(payload[:-1])


class RootOnlyContractSourceTests(unittest.TestCase):
    def test_root_only_contract_has_no_per_client_mapping(self) -> None:
        source = (ROOT / "contracts" / "RootOnlyContestFL.sol").read_text(encoding="utf-8")
        self.assertIn("bytes32 decisionRoot", source)
        self.assertIn("openDecisionChallenge", source)
        self.assertIn("openAggregateChallenge", source)
        self.assertIn("mapping(uint256 => bool) public aggregateChallenge", source)
        self.assertIn("nextDecisionRoot != r.decisionRoot", source)
        self.assertIn("verifySparseProof", source)
        self.assertIn("if (!verifySparseProof", source)
        self.assertNotIn("mapping(uint256 => mapping(bytes32 => uint8))", source)
        self.assertNotIn("mapping(uint256 => mapping(bytes32 => bytes32)) public submission", source)

    def test_deployer_includes_root_only_contract(self) -> None:
        source = (ROOT / "tools" / "deploy.py").read_text(encoding="utf-8")
        self.assertIn('"RootOnlyContestFL": [coordinator, resolver]', source)


class NetemSourceTests(unittest.TestCase):
    def test_integer_microseconds_avoid_locale_decimal(self) -> None:
        shell = (ROOT / "tools" / "netem.sh").read_text(encoding="utf-8")
        helper = (ROOT / "tools" / "netem_namespace.py").read_text(encoding="utf-8")
        self.assertIn("export LC_ALL=C", shell)
        self.assertIn("--delay-us", shell)
        self.assertNotIn('printf "%.3f"', shell)
        self.assertIn('f"{delay_us}us"', helper)
        self.assertIn('env["LC_ALL"] = "C"', helper)


if __name__ == "__main__":
    unittest.main()
