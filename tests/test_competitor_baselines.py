from __future__ import annotations

import unittest

try:
    from bench.run_competitor_baselines import expected_outcome, state_for_workload
    _IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # Host-only checks may omit Docker dependencies.
    expected_outcome = None
    state_for_workload = None
    _IMPORT_ERROR = str(exc)


@unittest.skipIf(_IMPORT_ERROR is not None, f"optional experiment dependencies unavailable: {_IMPORT_ERROR}")
class CompetitorSemanticsTests(unittest.TestCase):
    def test_expected_outcome_matrix(self) -> None:
        assert expected_outcome is not None
        self.assertEqual(expected_outcome("ledger_audit", "bad_aggregate"), "DETECTED_ONLY")
        self.assertEqual(expected_outcome("eager_full", "bad_aggregate"), "PREVENTED")
        self.assertEqual(expected_outcome("single_shot", "bad_aggregate"), "CORRECTED")
        self.assertEqual(expected_outcome("single_shot", "dependent_fault"), "FAULTY_FINALIZED")
        self.assertEqual(expected_outcome("single_shot", "correction_laundering"), "FAULTY_FINALIZED")
        self.assertEqual(expected_outcome("single_shot", "resolver_unavailable"), "STUCK")
        self.assertEqual(expected_outcome("eager_full", "resolver_unavailable"), "SAFE_ABORT")

    def test_fault_workloads_are_noncanonical(self) -> None:
        assert state_for_workload is not None
        states, modifier = state_for_workload("bad_admission", 10)
        self.assertEqual(states[0], 1)
        self.assertIsNone(modifier)

        states, modifier = state_for_workload("bad_omission", 10)
        self.assertEqual(states[0], 2)
        self.assertIsNone(modifier)

        states, modifier = state_for_workload("resolver_unavailable", 10)
        self.assertEqual(states, [3] * 10)
        self.assertIsNotNone(modifier)


if __name__ == "__main__":
    unittest.main()
