from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import tools.network as network
    _IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # Host-only checks may omit Docker dependencies.
    network = None
    _IMPORT_ERROR = str(exc)


@unittest.skipIf(_IMPORT_ERROR is not None, f"optional experiment dependencies unavailable: {_IMPORT_ERROR}")
class NetworkComposeTests(unittest.TestCase):
    def test_compose_separates_control_and_p2p_networks(self) -> None:
        assert network is not None
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "compose.yml"
            with patch.object(network, "COMPOSE", output):
                network.generate_compose(4)
            text = output.read_text(encoding="utf-8")
        self.assertIn("name: contestfl-control-net", text)
        self.assertIn("name: contestfl-p2p-net", text)
        self.assertIn("networks: [control]", text)
        self.assertIn("ipv4_address: 172.31.0.11", text)
        self.assertIn("ipv4_address: 172.32.0.11", text)
        self.assertNotIn("PUMBA", text.upper())


if __name__ == "__main__":
    unittest.main()
