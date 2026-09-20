from pathlib import Path
import unittest, zipfile
class ReferenceReleaseTest(unittest.TestCase):
    def test_required_archives_exist_and_are_readable(self):
        root=Path(__file__).resolve().parents[1]
        required={'stable_core','competitor_extension','targeted_extension','root_only_ablation','root_depth_sensitivity','network_smoke','flower_mnist','smt_offchain','watcher_extension','bounded_gas_contention','dependency_dag_retained','feature_ablation_retained'}
        archives=root/'results'/'reference'/'archives'
        self.assertTrue(required <= {p.stem for p in archives.glob('*.zip')})
        for p in archives.glob('*.zip'):
            with zipfile.ZipFile(p) as z: self.assertIsNone(z.testzip(),p.name)
    def test_generated_runtime_is_not_in_release(self):
        root=Path(__file__).resolve().parents[1]
        for rel in ['last','network/runtime','network/secrets','network/work','network/docker-compose.generated.yml','network/contracts.json']:
            self.assertFalse((root/rel).exists(),rel)
if __name__=='__main__': unittest.main()
