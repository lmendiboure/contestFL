"""Pure plan + analysis regression checks; never claim to replace Besu receipts."""
import csv
import tempfile
import unittest
from pathlib import Path

from review import analyze_causal_chain as stats


class CausalChainAnalysisTests(unittest.TestCase):
    def make_row(self, policy, rep, success=True, gas=10, time_ms=20, seed=None):
        return {"design": policy, "workload": "chain", "client_count": 10,
                "repetition": rep, "seed": 100 + rep if seed is None else seed,
                "correct_checkpoint_finalized": "True" if success else "False",
                "error": "" if success else "injected failure", "gas_total": gas,
                "wall_ms": time_ms, "tx_count": 10, "verification_cpu_ms": 1.0}

    def test_paired_medians_not_median_of_independent_groups(self):
        rows = [self.make_row('contestfl', 0, gas=1), self.make_row('contestfl', 1, gas=100),
                self.make_row('abort_restart', 0, gas=3), self.make_row('abort_restart', 1, gas=101)]
        for row in rows:
            row['ok'] = True
        _, effects = stats.summarize(rows)
        self.assertEqual(effects[0]['gas_total_paired_median_delta'], 1.5)

    def test_failed_runs_counted(self):
        rows = [self.make_row('contestfl', 0), self.make_row('contestfl', 1, success=False),
                self.make_row('abort_restart', 0), self.make_row('abort_restart', 1)]
        for r in rows:
            r['ok'] = r['correct_checkpoint_finalized'] == 'True' and not r['error']
        groups, effects = stats.summarize(rows)
        self.assertEqual(next(g for g in groups if g['policy'] == 'contestfl')['successes'], 1)
        self.assertEqual(effects[0]['pairs_both_successful'], 1)
        self.assertEqual(effects[0]['failed_pairs'], 1)

    def test_duplicate_pair_rejected(self):
        r = self.make_row('contestfl', 0)
        r['ok'] = True
        with self.assertRaises(ValueError):
            stats.summarize([r, dict(r)])

    def test_missing_pairs_not_silently_deleted(self):
        a = self.make_row('contestfl', 0); a['ok'] = True
        b = self.make_row('abort_restart', 1); b['ok'] = True
        _, effects = stats.summarize([a, b])
        self.assertEqual(effects[0]['pairs_total'], 0)
        self.assertEqual(effects[0]['missing_pairs'], 2)

    def test_csv_reader_refuses_warmup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'rows.csv'
            row = self.make_row('contestfl', -1)
            with path.open('w', newline='') as f:
                writer=csv.DictWriter(f, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
            with self.assertRaises(ValueError):
                stats.read_rows(path)

    def test_bootstrap_deterministic(self):
        self.assertEqual(stats.bootstrap_median_ci([2, 5, 6], 20),
                         stats.bootstrap_median_ci([2, 5, 6], 20))

    def test_plan_is_three_successive_correlations(self):
        from review.causal_chain_plan import chain_plan
        plan = chain_plan()
        self.assertEqual([step.kind for step in plan], ['ADMIT', 'INCLUDE', 'AGGREGATE'])
        self.assertEqual([step.prior_epoch for step in plan], [0, 1, 2])
        self.assertEqual([(x.observed_state, x.corrected_state) for x in plan[:2]],
                         [(1, 2), (2, 3)])

    def test_generated_candidates_activate_inclusion_then_correct_aggregate(self):
        from review.causal_chain_plan import candidate, verify_plan
        from bench.smt import SparseMerkleMap
        import hashlib

        class MerkleData:
            client_ids = [hashlib.sha256(b"a").digest(), hashlib.sha256(b"b").digest()]

            def roots(self, states):
                trees = [SparseMerkleMap(32) for _ in range(3)]
                for index, (cid, state) in enumerate(zip(self.client_ids, states)):
                    trees[0].set(cid, hashlib.sha256(bytes([index])).digest())
                    if state >= 2:
                        trees[1].set(cid, b"\x01")
                    if state == 3:
                        trees[2].set(cid, b"\x01")
                return tuple(t.root for t in trees)

            def checkpoint(self, states):
                # Like RoundData.checkpoint, this depends *only* on included
                # (state==3) updates, not on admission-only changes.
                return hashlib.sha256(b"aggregate:" +
                                      bytes(i for i, state in enumerate(states) if state == 3)).digest()

        d = MerkleData()
        verify_plan(d)
        stages = [candidate([3, 3], i, d) for i in range(4)]
        self.assertEqual([r[0][0] for r in stages], [1, 2, 3, 3])
        # This equality is legitimate and previously caused every v4 run to fail.
        self.assertEqual(stages[0][1], stages[1][1])
        self.assertNotEqual(d.roots(stages[0][0])[1], d.roots(stages[1][0])[1])
        self.assertEqual(d.roots(stages[0][0])[2], d.roots(stages[1][0])[2])
        self.assertNotEqual(stages[1][1], stages[2][1])
        self.assertNotEqual(stages[2][1], stages[3][1])

        class BrokenRoots(MerkleData):
            def roots(self, states):
                # Mask an ADMIT change: validation must reject it.
                forged = list(states)
                if forged[0] == 2:
                    forged[0] = 1
                return super().roots(forged)

        with self.assertRaisesRegex(AssertionError, "ADMIT transition"):
            verify_plan(BrokenRoots())

    def test_plan_with_real_rounddata_when_web3_is_installed(self):
        try:
            from bench.run_scenarios import RoundData
        except ImportError as exc:
            self.skipTest(f"Real RoundData requires Web3 dependencies: {exc}")
        from review.causal_chain_plan import candidate, verify_plan
        data = RoundData.generate(10, 1024, 20261111, 32)
        verify_plan(data)
        initial = [3] * 10
        self.assertEqual(candidate(initial, 0, data)[1], candidate(initial, 1, data)[1])
        self.assertNotEqual(data.roots(candidate(initial, 0, data)[0]),
                            data.roots(candidate(initial, 1, data)[0]))

    def test_plan_requires_retry_budget_at_least_three(self):
        s = Path(__file__).resolve().parents[1].joinpath('review/causal_chain.py').read_text()
        self.assertIn('args.retry_budget < 3', s)
        self.assertIn('stage < 2', s)


if __name__ == '__main__':
    unittest.main()
