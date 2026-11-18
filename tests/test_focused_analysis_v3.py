"""Host-only methodological gates: no misleading averages or fabricated results."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from review.consolidate_focused_v3 import read_rows, summarize, wilson, boot_ci, write_latex, write_report


def record(policy, rep, *, window="sized", passed=True, latency=1000.0, clients=100):
    return {
        "window_label": window, "workload": "bad_admission", "client_count": str(clients),
        "repetition": str(rep), "seed": str(800 + rep), "design": policy,
        "correct_checkpoint_finalized": "True" if passed else "False",
        "error": "" if passed else "challenge expired",
        "wall_ms": str(latency), "gas_total": str(1000000 if policy == "contestfl" else 1200000),
        "verification_cpu_ms": "10", "challenge_wait_wall_ms": "500",
    }


class V3FocusedAnalysisTests(unittest.TestCase):
    def test_positive_deltas_and_pairing(self):
        data = []
        for r in range(8):
            for design in ("contestfl", "eager_full", "abort_restart", "level_cascade"):
                data.append(record(design, r, latency=1000 if design == "contestfl" else 1200))
        _, effects = summarize(read_fake(data))
        eager = next(r for r in effects if r["alternative"] == "eager_full")
        self.assertEqual(eager["matched_both_success"], 8)
        self.assertAlmostEqual(eager["wall_ms_delta_median"], 200)
        self.assertAlmostEqual(eager["gas_total_delta_median"], 200000)

    def test_failed_not_in_conditioned_medial_but_counted(self):
        data = []
        for r in range(5):
            for design in ("contestfl", "eager_full", "abort_restart", "level_cascade"):
                data.append(record(design, r, passed=not (design == "eager_full" and r == 1), latency=1200 if design == "eager_full" else 1000))
        summary, effects = summarize(read_fake(data))
        eager = next(x for x in summary if x["policy"] == "eager_full")
        self.assertEqual(eager["failures"], 1)
        self.assertEqual(eager["successes"], 4)
        pair = next(x for x in effects if x["alternative"] == "eager_full")
        self.assertEqual(pair["matched_both_success"], 4)
        self.assertEqual(pair["failed_pairs"], 1)

    def test_short_and_sized_are_never_pooled(self):
        data = []
        for window in ("sized", "short"):
            for policy in ("contestfl", "eager_full", "abort_restart", "level_cascade"):
                data.append(record(policy, 1, window=window))
        summary, effects = summarize(read_fake(data))
        self.assertEqual(len(summary), 8)
        self.assertEqual(len(effects), 6)

    def test_duplicates_are_rejected(self):
        r = record("contestfl", 1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            summarize(read_fake([r, r]))

    def test_wilson_and_bootstrap_determinism(self):
        self.assertEqual(wilson(0, 5)[0], 0.0)
        self.assertEqual(wilson(5, 5)[1], 1.0)
        self.assertEqual(boot_ci([1., 2., 3.], seed=11, draws=200), boot_ci([1., 2., 3.], seed=11, draws=200))

    def test_real_csv_roundtrip_and_latex(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "data.csv"
            rows = [record(policy, rep) for rep in (0, 1) for policy in ("contestfl", "eager_full", "abort_restart", "level_cascade")]
            with p.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader();writer.writerows(rows)
            normalized = read_rows([p])
            summary, effects = summarize(normalized)
            write_latex(Path(tmp)/'table.tex', summary)
            write_report(Path(tmp)/'summary.md', summary, effects)
            self.assertIn("Success", (Path(tmp)/'table.tex').read_text())
            self.assertIn("correctly finalized", (Path(tmp)/'summary.md').read_text())


def read_fake(rows):
    """Use CSV reader contract rather than manually faking internal typing."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "rows.csv"
        with p.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        return read_rows([p])


if __name__ == '__main__':
    unittest.main()
