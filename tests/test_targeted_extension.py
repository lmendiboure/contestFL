from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TargetedExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = (ROOT / "bench" / "run_scenarios.py").read_text(encoding="utf-8")
        cls.analysis = (ROOT / "bench" / "analyze_targeted_extension.py").read_text(encoding="utf-8")
        cls.shell = (ROOT / "run_targeted_extension.sh").read_text(encoding="utf-8")

    def test_scenarios_registered(self) -> None:
        self.assertIn('"affected_decisions": scenario_affected_decisions', self.runner)
        self.assertIn('"faulty_replacement_chain": scenario_faulty_replacement_chain', self.runner)

    def test_phase_mapping_is_stable(self) -> None:
        for phase_class in (
            'return "Coordination"',
            'return "Challenge"',
            'return "Resolution"',
            'return "Replacement"',
            'return "Fallback/abort"',
            'return "Finalization"',
        ):
            self.assertIn(phase_class, self.analysis)

    def test_targeted_runner_avoids_network_emulation(self) -> None:
        self.assertNotIn("netem", self.shell.lower())
        self.assertNotIn("pumba", self.shell.lower())
        self.assertIn("preflight_flood_100_p5", self.shell)
        self.assertIn("preflight_eager_500", self.shell)

    def test_replacement_chain_uses_terminal_fallback_at_budget(self) -> None:
        self.assertIn("if depth == ctx.retry_budget:", self.runner)
        self.assertIn("ctx.publish_fallback(states, expected)", self.runner)


if __name__ == "__main__":
    unittest.main()
