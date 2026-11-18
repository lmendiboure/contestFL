"""Local checks for safe, narrowly scoped recovery after Netem preflight failure."""
import csv
import tempfile
import unittest
from pathlib import Path
from review.netem_resume_state import validate

ROOT = Path(__file__).resolve().parents[1]


def make_run(base: Path) -> Path:
    out = base / 'v4ext_full_v4_extended_run'
    out.mkdir()
    stages = [('causal_n25_d4096_r8', 'PASS'), ('flower_policies_20261111', 'FAIL_1'),
              ('resume_network_and_contracts','PASS'),
              ('flower_policies_20261111', 'PASS'),
              ('flower_policies_20261212','PASS'),('flower_policies_20261313','PASS'),
              ('netem_preflight','FAIL_2')]
    with (out/'STAGE_STATUS.tsv').open('w', newline='') as f:
        w=csv.writer(f,delimiter='\t'); w.writerow(['stage','status','unix_utc'])
        for a,b in stages: w.writerow([a,b,'1'])
    p=out/'scale/n25_d4096_r8/causal_chain_raw.csv';p.parent.mkdir(parents=True);p.write_text('ok\n')
    p=out/'timeouts/late_challenge_raw.csv';p.parent.mkdir(parents=True);p.write_text('ok\n')
    for seed in [20261111,20261212,20261313]:
        d=out/'flower'/f'seed_{seed}';d.mkdir(parents=True)
        (d/'FLOWER_ARTIFACT_REPORT.json').write_text('{}\n')
        (d/'paired_flower_policies.csv').write_text('ok\n')
    return out


class NetemResumeTests(unittest.TestCase):
    def test_original_failure_and_successful_flower_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(validate(make_run(Path(t)))['flower_repetitions'],3)
    def test_cannot_restart_from_other_stage(self):
        with tempfile.TemporaryDirectory() as t:
            out=make_run(Path(t))
            with (out/'STAGE_STATUS.tsv').open('a') as f:f.write('netem_apply\tFAIL_1\t2\n')
            with self.assertRaisesRegex(ValueError,'netem_preflight'):validate(out)
    def test_no_overwrite_of_finished_or_partial_netem(self):
        with tempfile.TemporaryDirectory() as t:
            out=make_run(Path(t))
            (out/'REVIEW_RUN_MANIFEST.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'manifest'):validate(out)
            (out/'REVIEW_RUN_MANIFEST.json').unlink()
            d=out/'netem';d.mkdir()
            (d/'network_probe.csv').write_text('existing')
            with self.assertRaisesRegex(ValueError,'partial Netem'):validate(out)
    def test_missing_flower_observation_refused(self):
        with tempfile.TemporaryDirectory() as t:
            out=make_run(Path(t))
            (out/'flower/seed_20261212/paired_flower_policies.csv').unlink()
            with self.assertRaisesRegex(ValueError,'missing Flower'):validate(out)
    def test_launcher_uses_explicit_bash_for_netem(self):
        for name in ('review/run_v4_extended.sh', 'review/resume_v4_extended_flower.sh', 'review/resume_v4_extended_netem.sh'):
            script=(ROOT/name).read_text()
            self.assertNotIn('step netem_apply tools/netem.sh',script)
            self.assertIn('bash tools/netem.sh apply',script)
        makefile=(ROOT/'Makefile').read_text()
        self.assertIn('@bash tools/netem.sh preflight',makefile)

if __name__ == '__main__': unittest.main()
