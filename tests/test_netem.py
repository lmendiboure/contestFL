from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from tools.netem_namespace import clear_delay, parse_ping_average


class NetemHelperTests(unittest.TestCase):
    def test_parse_linux_ping_average(self) -> None:
        output = """\n--- 172.31.0.12 ping statistics ---\n5 packets transmitted, 5 received, 0% packet loss, time 4004ms\nrtt min/avg/max/mdev = 24.912/25.143/25.331/0.143 ms\n"""
        self.assertAlmostEqual(parse_ping_average(output), 25.143)

    def test_rejects_unrecognized_ping_output(self) -> None:
        with self.assertRaises(RuntimeError):
            parse_ping_average("no statistics")

    @patch("tools.netem_namespace.run")
    def test_clear_is_noop_for_implicit_noqueue(self, mocked_run) -> None:
        mocked_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="qdisc noqueue 0: root refcnt 2", stderr=""
        )
        clear_delay("eth1")
        self.assertEqual(mocked_run.call_count, 1)

    @patch("tools.netem_namespace.run")
    def test_clear_deletes_active_netem(self, mocked_run) -> None:
        mocked_run.side_effect = [
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="qdisc netem 8001: root refcnt 2 limit 1000 delay 10ms", stderr=""
            ),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]
        clear_delay("eth1")
        self.assertEqual(mocked_run.call_count, 2)
        delete_command = mocked_run.call_args_list[1].args[0]
        self.assertEqual(delete_command, ["tc", "qdisc", "del", "dev", "eth1", "root"])


if __name__ == "__main__":
    unittest.main()
