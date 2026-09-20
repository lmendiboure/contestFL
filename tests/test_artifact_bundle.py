from pathlib import Path
import unittest

from tools.build_artifact_bundle import include_source


class ArtifactBundleExclusionTest(unittest.TestCase):
    def test_generated_secrets_and_local_env_are_excluded(self) -> None:
        root = Path('/tmp/contestfl')
        self.assertFalse(include_source(root / '.env', root))
        self.assertFalse(include_source(root / 'network' / 'secrets' / 'admin.key', root))
        self.assertFalse(include_source(root / 'network' / 'runtime' / 'node1' / 'key', root))
        self.assertFalse(include_source(root / 'results' / 'runs' / 'run.csv', root))

    def test_source_files_are_included(self) -> None:
        root = Path('/tmp/contestfl')
        self.assertTrue(include_source(root / 'contracts' / 'RootOnlyContestFL.sol', root))
        self.assertTrue(include_source(root / 'formal' / 'ContestFL.tla', root))


if __name__ == '__main__':
    unittest.main()
