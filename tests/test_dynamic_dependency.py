"""Host-side tests for bounded two-client dynamic-key abstraction.

These are not on-chain contract tests. The Besu check is
`SCENARIOS=adversarial_moot_guard,concurrent_moot make benchmark ...`.
"""
import unittest

from formal.dynamic_dependency_check import (
    Truth, active, certified_fallback, challenge_batches, explore,
    initial_states, invalid, published_binding_consistent, republish,
    resolve_snapshot,
)
from dataclasses import replace


class DynamicDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = explore('shared', shared_budget=1, level_budgets=(1, 1, 1))
        cls.levels = explore('levels', shared_budget=1, level_budgets=(1, 1, 1))
        cls.uncovered = explore('shared', shared_budget=0, level_budgets=(0, 0, 0), coverage=False)

    def test_both_retry_accounting_modes_explore_activation(self):
        for report in (self.shared, self.levels):
            self.assertGreater(report['observations']['dynamic_activation'], 0)
            self.assertGreater(report['observations']['dynamic_deactivation'], 0)
            self.assertGreater(report['observations']['concurrent_ancestor_descendant'], 0)
            self.assertGreater(report['observations']['finalized_after_fallback'], 0)

    def test_c1_is_necessary_for_policy_valid_finalization(self):
        self.assertGreater(self.uncovered['observations']['uncovered_invalid_finalized'], 0)

    def test_frozen_snapshot_detects_reject_to_admit_and_moots_aggregate(self):
        original = next(s for s in initial_states()
                        if s.admission == (False, True) and s.inclusion == (None, True) and s.aggregate_correct is False)
        truth = Truth((True, True), (True, True))
        batch = ('A0', 'G')
        self.assertTrue(set(invalid(original, truth)).issubset(set(batch)))
        challenged = replace(original, phase='SNAPSHOT', challenge_batch=batch)
        result = resolve_snapshot(challenged, truth)
        self.assertEqual(result.phase, 'REPLACE')
        self.assertTrue(result.admission[0])
        self.assertFalse(result.aggregate_correct)
        self.assertTrue(result.concurrent_seen)
        self.assertEqual(result.pending_levels, (0,))  # ancestor makes G moot
        successors = republish(result, 'shared', truth, 1, (1, 1, 1))
        self.assertTrue(successors)
        self.assertTrue(all(published_binding_consistent(s) for s in successors))
        self.assertTrue(all(s.activated == 1 for s in successors))
        self.assertTrue(all('I0' in active(s) for s in successors))

    def test_admit_to_reject_deactivates_key(self):
        original = next(s for s in initial_states()
                        if s.admission == (True, True) and s.aggregate_correct is True)
        truth = Truth((False, True), (False, True))
        revised = resolve_snapshot(replace(original, phase='SNAPSHOT', challenge_batch=('A0',)), truth)
        successors = republish(revised, 'shared', truth, 1, (1, 1, 1))
        self.assertTrue(successors)
        self.assertTrue(all('I0' not in active(s) for s in successors))
        self.assertTrue(all(s.inclusion[0] is None for s in successors))

    def test_fallback_is_terminal_and_does_not_open_new_window(self):
        original = next(s for s in initial_states() if s.admission == (False, False))
        truth = Truth((True, True), (True, True))
        revised = resolve_snapshot(replace(original, phase='SNAPSHOT', challenge_batch=('A0','A1')), truth)
        terminal = certified_fallback(revised, truth)
        self.assertEqual(terminal.phase, 'READY')
        self.assertEqual(terminal.windows, original.windows)
        self.assertFalse(invalid(terminal, truth))
        self.assertTrue(published_binding_consistent(terminal))


if __name__ == '__main__':
    unittest.main()
