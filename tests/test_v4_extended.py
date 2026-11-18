"""Host-only tests; do not require Docker, Web3, Flower or Besu."""
from __future__ import annotations
import csv
import tempfile
import unittest
from pathlib import Path

from review.timeout_semantics import classify
from review.consolidate_v4_extended import summarize_scale, summarize_flower, summarize_timeouts


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fd:
        w = csv.DictWriter(fd, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


class TimeoutSemanticsTests(unittest.TestCase):
    def test_missed_challenge_is_coverage_loss_not_abort(self):
        self.assertEqual(classify(included_before_deadline=False, response_timed_out=False,
                                  aborted_onchain=False), "coverage_miss_C1")
    def test_confirmed_timeout_is_onchain_abort(self):
        self.assertEqual(classify(included_before_deadline=True, response_timed_out=True,
                                  aborted_onchain=True), "resolver_timeout_abort_onchain")
    def test_reject_fabricated_abort(self):
        for accepted, timed_out, aborted in [(True,True,False),(False,True,True),(True,False,True)]:
            with self.assertRaises(ValueError):
                classify(included_before_deadline=accepted, response_timed_out=timed_out,
                         aborted_onchain=aborted)


class ConsolidationTests(unittest.TestCase):
    def test_scaling_keeps_failed_runs_and_separates_configurations(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fields = []
            for policy in ["contestfl", "abort_restart", "aggregate_reaudit"]:
                for i in (0, 1):
                    fields.append({"design": policy, "workload": "chain", "client_count": 25,
                                   "repetition": i, "seed": i + 99, "error": "" if i == 0 else "observed_failure",
                                   "correct_checkpoint_finalized": "True" if i == 0 else "False",
                                   "gas_total": 100+i, "wall_ms": 1000+i,
                                   "verification_cpu_ms": 2, "tx_count": 3})
            write_csv(out / "scale/n25_d4096_r2/causal_chain_raw.csv", fields)
            groups, pairs = summarize_scale(out)
            self.assertEqual(len(groups), 3)
            self.assertEqual(len(pairs), 2)
            self.assertTrue(all(g["attempts"] == 2 and g["successes"] == 1 for g in groups))
            self.assertTrue(all(p["pairs_both_successful"] == 1 and p["failed_pairs"] == 1 for p in pairs))

    def test_flower_share_one_training_measurement_and_pair_by_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for idx, seed in enumerate((101, 202)):
                rows=[]
                for policy, t in (("contestfl", 100), ("eager_full", 60)):
                    rows.append({"seed": seed, "design": policy, "workload": "clean",
                                 "correct_checkpoint_finalized": "True", "error": "",
                                 "end_to_end_sequential_ms": 1000+t,
                                 "gas_total": 200 if policy == "contestfl" else 250,
                                 "artifact_bytes_measured": 1024})
                write_csv(out / f"flower/seed_{seed}/paired_flower_policies.csv", rows)
            groups, pairs=summarize_flower(out)
            self.assertEqual(len(groups),2)
            self.assertEqual(pairs[0]["both_correct"],2)
            self.assertEqual(pairs[0]["eager_minus_contestfl_e2e_delta_median_ms"], -40)

    def test_timeout_injected_outcomes_accounted_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_csv(out / "timeouts/late_challenge_raw.csv", [
                {"flood_count":360,"quota_per_identity":0,"honest_success":"False", "resolver_timeout_abort":"False",
                 "terminal_outcome":"coverage_miss_C1", "error":"", "measured_blocks":3,"max_observed_block_gas_utilization":0.97},
                {"flood_count":360,"quota_per_identity":0,"honest_success":"True", "resolver_timeout_abort":"True",
                 "terminal_outcome":"resolver_timeout_abort_onchain", "error":"", "measured_blocks":3,"max_observed_block_gas_utilization":0.97},
            ])
            [r]=summarize_timeouts(out)
            self.assertEqual(r["C1_coverage_misses"], 1)
            self.assertEqual(r["injected_unresolved_resolver_aborts_onchain"], 1)

    def test_launcher_preserves_v3_and_is_explicit_about_scale(self):
        script=(Path(__file__).resolve().parents[1]/"review/run_v4_extended.sh").read_text()
        self.assertIn('n500_d4096_r6', script)
        self.assertIn('EXT_HEAVY_500MB', script)
        self.assertIn('resolver-timeout-probe', script)
        self.assertNotIn('run_focused_v3.sh focused', script)


if __name__ == "__main__": unittest.main()
