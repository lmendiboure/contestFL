"""Host-only tests of reviewer scripts, data integrity, and declared scope."""
import tempfile
import unittest
from pathlib import Path

from review.analyze_policies import bootstrap_ci, summarize
from review.window_sensitivity import choose_rows, compute_window

ROOT = Path(__file__).resolve().parents[1]


class WindowModelTests(unittest.TestCase):
    def test_positive_and_monotone(self):
        x = compute_window(180, 100_000_000, 100, 50, 1, 1.0, 2)
        self.assertGreater(x, 2)
        self.assertGreater(compute_window(180, 100_000_000, 20, 50, 1, 1.0, 2), x)
        self.assertGreater(compute_window(180, 100_000_000, 100, 200, 100, 1.0, 2), x)

    def test_reject_missing_observations(self):
        summary = ROOT / 'results/reference/summaries/watcher_extension/watcher_pipeline_summary.csv'
        self.assertTrue(choose_rows(summary, 100, 'fadvise'))
        with self.assertRaises(ValueError):
            choose_rows(summary, 9999, 'fadvise')

    def test_reject_bad_inputs(self):
        for param in ((0, 100, 0, 0, 1, 1, 1), (1, 100, -20, 0, 1, 1, 1)):
            with self.assertRaises(ValueError):
                compute_window(*param)


class AnalysisTests(unittest.TestCase):
    def row(self, design, rep, gas, ms, ok=True, workload="bad_admission"):
        return dict(design=design, workload=workload, client_count=10, repetition=rep, seed=101 + rep,
                    gas_total=float(gas), wall_ms=float(ms), tx_count=2.0,
                    verification_cpu_ms=3.0, ok=ok)

    def test_paired_deltas_are_not_unpaired_medians(self):
        rows = [self.row('contestfl', 0, 100, 50), self.row('contestfl', 1, 300, 30),
                self.row('abort_restart', 0, 250, 100), self.row('abort_restart', 1, 320, 50)]
        groups, effects = summarize(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]['gas_total_paired_median_delta'], 85.0)
        self.assertEqual(effects[0]['wall_ms_paired_median_delta'], 35.0)

    def test_failed_runs_remain_denominator(self):
        rows = [self.row('contestfl', 0, 10, 10), self.row('contestfl', 1, 20, 20),
                self.row('eager_full', 0, 30, 30), self.row('eager_full', 1, 5, 5, False)]
        groups, effects = summarize(rows)
        eager = next(r for r in groups if r['design'] == 'eager_full')
        self.assertEqual(eager['attempts'], 2)
        self.assertEqual(eager['success_rate'], .5)
        self.assertEqual(effects[0]['matched_successful'], 1)
        self.assertEqual(effects[0]['excluded_failure_pairs'], 1)

    def test_exact_pair_required(self):
        rows = [self.row('contestfl', 0, 10, 10), self.row('eager_full', 1, 5, 5)]
        _, effects = summarize(rows)
        self.assertEqual(effects[0]['matched_total'], 0)
        self.assertEqual(effects[0]['missing_pair_count'], 2)

    def test_clean_and_fault_workloads_never_mix(self):
        rows = [self.row('contestfl', 0, 100, 40, workload='clean'),
                self.row('eager_full', 0, 150, 50, workload='clean'),
                self.row('contestfl', 0, 200, 80, workload='bad_admission'),
                self.row('eager_full', 0, 260, 95, workload='bad_admission')]
        groups, effects = summarize(rows)
        self.assertEqual(len(groups), 4)
        self.assertEqual(len(effects), 2)
        self.assertEqual({r['workload'] for r in effects}, {'clean', 'bad_admission'})
        self.assertEqual(sorted(r['gas_total_paired_median_delta'] for r in effects), [50.0, 60.0])

    def test_bootstrap_reproducible(self):
        self.assertEqual(bootstrap_ci([1, 2, 3], seed=10, samples=100),
                         bootstrap_ci([1, 2, 3], seed=10, samples=100))


class ContractAndRunnerTests(unittest.TestCase):
    def test_quota_off_by_default_and_identity_epoch_binding(self):
        source = (ROOT / 'contracts/ContestFLExperiment.sol').read_text()
        self.assertIn('uint32 public maxChallengesPerIdentity;', source)
        self.assertIn('maxChallengesPerIdentity != 0', source)
        self.assertIn('abi.encode(roundId, r.epoch, msg.sender)', source)
        self.assertIn('error ChallengeQuotaExceeded();', source)

    def test_causal_moot_guard_retained(self):
        source = (ROOT / 'contracts/ContestFLExperiment.sol').read_text()
        self.assertIn('error InvalidMootDescendant();', source)
        self.assertIn('if (!isDescendant) revert InvalidMootDescendant();', source)

    def test_env_example_and_launchers(self):
        example = (ROOT / '.env.example')
        self.assertTrue(example.exists())
        self.assertIn('BESU_IMAGE=', example.read_text())
        launcher = (ROOT / 'review/run_review_suite.sh').read_text()
        self.assertIn('late_challenge_flood', launcher)
        self.assertIn('paired_policies', launcher)
        self.assertIn('original_paper_full', launcher)


if __name__ == '__main__':
    unittest.main()
