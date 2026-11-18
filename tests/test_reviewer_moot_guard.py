"""Source-level smoke check; not a substitute for EVM execution."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MootGuardSourceCheck(unittest.TestCase):
    def test_guard_is_present_in_reference_contract(self):
        source = (ROOT / 'contracts' / 'ContestFLExperiment.sol').read_text()
        self.assertIn('error InvalidMootDescendant();', source)
        self.assertIn('mootChallengeIds.length != 0 && outcome != ChallengeOutcome.REVISED', source)
        self.assertIn('descendant.kind == DecisionKind.INCLUDE && descendant.clientId == c.clientId', source)
        self.assertIn('descendant.kind == DecisionKind.AGGREGATE', source)
        self.assertIn('if (!isDescendant) revert InvalidMootDescendant();', source)
        self.assertIn('if (decisionState[c.roundId][c.clientId] == correctedState) revert InvalidArgument();', source)

    def test_besu_scenario_registered(self):
        source = (ROOT / 'bench' / 'run_scenarios.py').read_text()
        self.assertIn('"adversarial_moot_guard": scenario_adversarial_moot_guard', source)
        self.assertIn('unprotected bypass:', source)


if __name__ == '__main__':
    unittest.main()
