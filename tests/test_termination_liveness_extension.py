"""Source/packaging checks; Besu transition tests run in the separate probe."""
from __future__ import annotations
import hashlib
import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOL=ROOT/'contracts/ContestFLExperiment.sol'
LEGACY=ROOT/'review/fixtures/ContestFLExperiment_v4_pre_liveness.sol'
BASELINE_SHA='9b0e7adc7639627be32ea94b61098be3d64b754a1007d7612a5e81bedb526a3a'


class LivenessExtensionSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code=SOL.read_text()

    def test_exact_legacy_fixture_is_preserved(self):
        self.assertEqual(hashlib.sha256(LEGACY.read_bytes()).hexdigest(), BASELINE_SHA)
        self.assertNotIn('expireReplacement(', LEGACY.read_text())

    def test_old_open_round_signature_unchanged(self):
        original=LEGACY.read_text()
        pattern=r'function openRound\(\s*uint256 roundId,\s*uint32 expectedSubmissions,\s*uint32 challengeBlocks,\s*uint32 responseBlocks,\s*uint8 retryBudget\s*\) external onlyCoordinator'
        self.assertRegex(self.code,pattern)
        self.assertRegex(original,pattern)

    def test_deadlines_not_optional_in_new_entry_point(self):
        self.assertIn('function openRoundWithTimeouts(',self.code)
        self.assertRegex(self.code,r'if \(expectedSubmissions == 0[\s\S]*?submissionBlocks == 0 \|\| replacementBlocks == 0\) revert InvalidArgument\(\);')
        self.assertIn('r.submissionDeadline = _deadline(submissionBlocks);',self.code)

    def test_all_submit_and_replacement_publication_gated(self):
        for function, gate in [('submit', 'SubmissionDeadlineExpired'),
                               ('publishDecisions','SubmissionDeadlineExpired'),
                               ('publishInitialState','SubmissionDeadlineExpired'),
                               ('publishCoordinatorReplacement','ReplacementDeadlineExpired'),
                               ('publishResolverFallback','ReplacementDeadlineExpired')]:
            start=self.code.index('function '+function+'(')
            end=self.code.index('\n    function ',start+1) if '\n    function ' in self.code[start+1:] else len(self.code)
            self.assertIn('revert '+gate, self.code[start:end], function)

    def test_expiries_are_permissionless_and_terminal(self):
        for function in ['expireSubmission', 'expireReplacement']:
            self.assertRegex(self.code,r'function '+function+r'\(uint256 roundId\) external \{')
            start=self.code.index('function '+function+'(')
            end=self.code.index('\n    function ',start+1) if '\n    function ' in self.code[start+1:] else len(self.code)
            snippet=self.code[start:end]
            self.assertIn('r.phase = Phase.ABORTED;',snippet)
            self.assertIn('emit RoundAborted(',snippet)

    def test_replacement_deadline_only_after_last_pending_challenge(self):
        self.assertIn('r.needsReplacement && r.openChallenges == 0 && r.replacementDeadline == 0',self.code)
        self.assertIn('r.replacementDeadline = _deadline(r.replacementBlocks);',self.code)
        self.assertGreater(self.code.index('r.replacementDeadline = _deadline(r.replacementBlocks);'),
                           self.code.index('emit DescendantChallengeMoot(mootChallengeIds[i]);'))

    def test_new_windows_do_not_change_status_abi(self):
        pattern=r'function getRoundStatus\(uint256 roundId\) external view returns \((.*?)\) \{'
        before=re.search(pattern, LEGACY.read_text(), re.S).group(1)
        after=re.search(pattern, self.code, re.S).group(1)
        self.assertEqual(before, after)

    def test_checked_deadline_cast(self):
        self.assertRegex(self.code,r'function _deadline\(uint256 blocksAhead\) internal view returns \(uint64\)')
        self.assertIn('if (end > type(uint64).max) revert InvalidArgument();', self.code)

if __name__ == '__main__': unittest.main()
