import tempfile
import unittest
from pathlib import Path

import numpy as np

from ml.multiround_state import model_digest, read_model, schedule, write_model, metrics_summary
from review.analyze_flower_multiround import summarize


class ModelHandoff(unittest.TestCase):
    def test_handoff_roundtrip(self):
        model=[np.array([0.2,0.3],dtype=np.float32),np.zeros((2,2),dtype=np.float32)]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'accepted.npz'
            write_model(p,model)
            restored=read_model(p,model)
            self.assertEqual(model_digest(model),model_digest(restored))
            self.assertTrue(np.array_equal(model[0],restored[0]))

    def test_wrong_dtype_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'model.npz'
            write_model(p,[np.zeros(2,dtype=np.float64)])
            with self.assertRaises(ValueError):
                read_model(p,[np.zeros(2,dtype=np.float32)])

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            write_model(Path('not-written.npz'), [np.array([float('nan')])])

    def test_schedule_fixed_fault_plan(self):
        plan=schedule(20261201,20,[6,13,19])
        self.assertEqual([k+1 for k,(_,w) in enumerate(plan) if w=='bad_aggregate'],[6,13,19])
        self.assertEqual(plan[1][0],20261202)

    def test_duplicate_faults_fail(self):
        with self.assertRaises(ValueError): schedule(3,20,[6,6])

    def test_metrics_not_averaged_over_rounds(self):
        rows=[dict(correct_checkpoint_finalized=True,error='',full_round_wall_ms=1000),
              dict(correct_checkpoint_finalized=True,error='',full_round_wall_ms=2000)]
        self.assertEqual(metrics_summary(rows)['completed_rounds_per_hour'],2400)

class ReviewerRequirements(unittest.TestCase):
    def test_no_shared_one_round_artefacts(self):
        source=Path(__file__).resolve().parents[1]/'review/multiround_flower.py'
        content=source.read_text()
        self.assertIn('"--initial-params"',content)
        self.assertIn('if row["error"] or not row["correct_checkpoint_finalized"]:',content)
        self.assertIn('compare_policy(',content)

if __name__ == '__main__': unittest.main()
