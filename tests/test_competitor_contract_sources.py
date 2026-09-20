from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CompetitorContractSourceTests(unittest.TestCase):
    def test_eager_requires_certificate_before_finalization(self) -> None:
        source = (ROOT / "contracts" / "EagerVerification.sol").read_text(encoding="utf-8")
        self.assertIn("installVerifiedState", source)
        self.assertIn("!r.verified", source)
        self.assertIn("expireVerification", source)

    def test_single_shot_has_terminal_replacement_without_rechallenge(self) -> None:
        source = (ROOT / "contracts" / "SingleShotOptimistic.sol").read_text(encoding="utf-8")
        self.assertIn("publishTerminalReplacement", source)
        self.assertNotIn("retryBudget", source)
        self.assertNotIn("publishResolverFallback", source)


if __name__ == "__main__":
    unittest.main()
