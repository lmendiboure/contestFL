from pathlib import Path
import json
import subprocess
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
        # A release must not *ship* generated blockchain state. However, a
        # normal smoke run creates this state, so checking Path.exists() in
        # a live checkout makes all subsequent smoke runs fail spuriously.
        root = Path(__file__).resolve().parents[1]
        generated = [
            'last',
            'network/runtime',
            'network/secrets',
            'network/work',
            'network/docker-compose.generated.yml',
            'network/contracts.json',
        ]
        # The public source manifest lists the distributed files. Runtime state must
        # not be shipped, even though tests may generate it in a working tree.
        manifest = json.loads((root / 'provenance' / 'source_files.json').read_text(encoding='utf-8'))
        release_paths = list(manifest['files'])
        for rel in generated:
            self.assertFalse(
                any(path == rel or path.startswith(rel + '/') for path in release_paths),
                f'Generated artifact listed in release manifest: {rel}',
            )
        # For a Git checkout, verify that none of these paths is tracked.
        # The ZIP distribution has no .git directory and uses the manifest.
        if (root / '.git').exists():
            result = subprocess.run(
                ['git', '-C', str(root), 'ls-files', '--', *generated],
                check=True, capture_output=True, text=True,
            )
            self.assertFalse(result.stdout.strip(),
                             f'Generated artifacts tracked by Git: {result.stdout}')
if __name__=='__main__': unittest.main()
