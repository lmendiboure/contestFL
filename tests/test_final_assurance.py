"""Offline tests for final paired analysis and cascade runner wiring."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class FinalAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name)
        folder=self.out/'cascade'/'n10_r2_chain'
        folder.mkdir(parents=True)
        self.csv=folder/'cascade_compare_raw.csv'
        l=self.out/'liveness';l.mkdir()
        (l/'liveness_probe.json').write_text(json.dumps({
            'status':'PASS',
            'paired_gas':{'nominal':{'legacy_gas':100,'liveness_gas':105,'delta_gas':5,'delta_pct':5}},
            'liveness_cases':{'submission':{'status':'PASS'},'replacement':{'status':'PASS'}}}))
        self.rows=[]
        for rep in range(2):
            for policy in ('contestfl','independent_level_cascade'):
                self.rows.append({'client_count':10,'seed':99+rep,'repetition':rep,
                    'design':policy,'correct_checkpoint_finalized':'True','error':'',
                    'gas_total':1000 if policy=='contestfl' else 1001,
                    'wall_ms':500 if policy=='contestfl' else 510,
                    'verification_cpu_ms':5 if policy=='contestfl' else 15,
                    'full_level_audit_cpu_ms':0 if policy=='contestfl' else 10,
                    'audited_keys':0 if policy=='contestfl' else 63})
        self.dump()

    def dump(self):
        with self.csv.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(self.rows[0]));w.writeheader();w.writerows(self.rows)

    def run_analyzer(self):
        return subprocess.run([sys.executable,str(ROOT/'review/analyze_final_assurance.py'),
                               '--result-dir',str(self.out)],capture_output=True,text=True)

    def test_paired_descriptive_report(self):
        result=self.run_analyzer();self.assertEqual(result.returncode,0,result.stderr)
        content=(self.out/'analysis/FINAL_AUDIT.md').read_text()
        self.assertIn('Independent full-level',content)
        self.assertIn('delta +5 gas',content)
        with (self.out/'analysis/paired_summary.csv').open() as f:rows=list(csv.DictReader(f))
        delta=[x for x in rows if x['metric']=='gas_delta_cascade_minus_contestfl'][0]
        self.assertEqual(float(delta['mean']),1)

    def test_refuse_failed_runs(self):
        self.rows[0]['correct_checkpoint_finalized']='False';self.dump()
        self.assertNotEqual(self.run_analyzer().returncode,0)

    def test_refuse_incomplete_pair(self):
        self.rows.pop();self.dump()
        self.assertNotEqual(self.run_analyzer().returncode,0)

    def test_refuse_duplicate_seed(self):
        self.rows.append(dict(self.rows[0]));self.dump()
        self.assertNotEqual(self.run_analyzer().returncode,0)

    def test_refuse_liveness_failure(self):
        (self.out/'liveness/liveness_probe.json').write_text(json.dumps({'status':'FAIL'}))
        self.assertNotEqual(self.run_analyzer().returncode,0)

class HarnessStaticTests(unittest.TestCase):
    def test_independent_audit_reads_onchain_publication(self):
        code=(ROOT/'review/cascade_runtime.py').read_text()
        self.assertIn('StatePublished().process_receipt',code)
        self.assertIn('published_checkpoint!=checkpoint',code)

    def test_one_besu_network_and_prior_results_unmodified(self):
        script=(ROOT/'review/run_final_assurance.sh').read_text()
        self.assertIn('start_clean_besu',script)
        self.assertIn('liveness_probe',script)
        self.assertIn('compare_${spec}',script)
        self.assertNotIn('run_v4_extended.sh run',script)
        self.assertNotIn('run_flower_multiround.sh run',script)

if __name__=='__main__':unittest.main()
