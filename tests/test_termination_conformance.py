import unittest
from pathlib import Path
from review.check_termination_conformance import inspect_contract

class TerminationConformanceAudit(unittest.TestCase):
    def test_source_counterexample(self):
        p=Path(__file__).resolve().parents[1]/'review/fixtures/ContestFLExperiment_v4_pre_liveness.sol'
        record=inspect_contract(p.read_text())
        self.assertEqual(record['status'],'COUNTEREXAMPLE_TO_UNCONDITIONAL_ONCHAIN_LIVENESS')
        self.assertTrue(any('RESOLVING' in step for step in record['trace']))

    def test_corrected_source_contains_timeout_paths(self):
        p=Path(__file__).resolve().parents[1]/'contracts/ContestFLExperiment.sol'
        record=inspect_contract(p.read_text())
        self.assertEqual(record['status'],'STATIC_TIMEOUT_EXIT_PATHS_PRESENT_NOT_EVM_VERIFIED')

if __name__=='__main__':unittest.main()
