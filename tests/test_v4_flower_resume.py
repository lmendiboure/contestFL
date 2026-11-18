"""Tests for Flower diagnostic logging and auditable v4-extended resumption.

The Flower replay depends on Web3, so extract the small pure helper without
importing the blockchain-dependent module. This test runs on the host.
"""
from __future__ import annotations

import ast
import csv
import tempfile
import unittest
from pathlib import Path

from review.package_results import build_manifest

ROOT = Path(__file__).resolve().parents[1]


class FlowerPrintingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        code = (ROOT / 'review/flower_policy_replay.py').read_text()
        tree = ast.parse(code)
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'first_error_line')
        module = ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[]))
        namespace = {}
        exec(compile(module, 'flower_policy_replay.py', 'exec'), {'__builtins__': __builtins__}, namespace)
        cls.first_error_line = staticmethod(namespace['first_error_line'])

    def test_empty_error_does_not_crash(self):
        self.assertEqual(self.first_error_line(''), '')
        self.assertEqual(self.first_error_line(None), '')

    def test_first_line_of_real_error(self):
        self.assertEqual(self.first_error_line('ValueError: failed\ntraceback details'), 'ValueError: failed')

    def test_first_line_of_newline_only(self):
        self.assertEqual(self.first_error_line('\n'), '')


class AuditTrailTests(unittest.TestCase):
    def test_previous_failure_then_success_is_complete_but_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / 'review_outputs' / 'resumed_v4_extended_run'
            out.mkdir(parents=True)
            with (out / 'STAGE_STATUS.tsv').open('w', newline='') as f:
                writer = csv.writer(f, delimiter='\t')
                writer.writerow(['stage', 'status', 'unix_utc'])
                writer.writerow(['causal_n25_d4096_r8', 'PASS', '1'])
                writer.writerow(['flower_policies_20261111', 'FAIL_1', '2'])
                writer.writerow(['resume_network_and_contracts', 'PASS', '3'])
                writer.writerow(['flower_policies_20261111', 'PASS', '4'])
                writer.writerow(['finalize_manifest', 'PASS', '5'])
            manifest = build_manifest(root, out, 'extended')
            self.assertTrue(manifest['completed_all_stages'])
            self.assertEqual(manifest['prior_failed_attempts_retained'], 1)
            self.assertEqual(manifest['latest_stage_status']['flower_policies_20261111'], 'PASS')
            self.assertEqual(len(manifest['stages']), 5)

    def test_unresolved_failure_is_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            out=root/'review_outputs'/'failed_v4_extended_run'
            out.mkdir(parents=True)
            (out/'STAGE_STATUS.tsv').write_text('stage\tstatus\tunix_utc\nflower_policies_20261111\tFAIL_1\t2\n')
            manifest=build_manifest(root,out,'extended')
            self.assertFalse(manifest['completed_all_stages'])

    def test_resume_launcher_refuses_overwriting_prior_results(self):
        text = (ROOT / 'review/resume_v4_extended_flower.sh').read_text()
        self.assertIn('Refusing to overwrite existing Flower policy CSV', text)
        self.assertIn('REUSE previously measured Flower training', text)
        self.assertIn('resume_network_and_contracts', text)


if __name__ == '__main__': unittest.main()
