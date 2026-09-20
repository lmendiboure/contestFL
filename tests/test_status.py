from __future__ import annotations

import unittest

try:
    from tools.status import peer_ipv4
    _IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # Host-only checks may omit Docker dependencies.
    peer_ipv4 = None
    _IMPORT_ERROR = str(exc)


@unittest.skipIf(_IMPORT_ERROR is not None, f"optional experiment dependencies unavailable: {_IMPORT_ERROR}")
class StatusParserTests(unittest.TestCase):
    def test_extracts_peer_ipv4(self) -> None:
        assert peer_ipv4 is not None
        self.assertEqual(peer_ipv4("/172.31.0.12:30303"), "172.31.0.12")

    def test_returns_none_without_ipv4(self) -> None:
        assert peer_ipv4 is not None
        self.assertIsNone(peer_ipv4("peer-without-address"))


if __name__ == "__main__":
    unittest.main()
