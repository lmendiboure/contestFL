from __future__ import annotations

import unittest

from bench.watcher_pipeline import bootstrap_median_ci, percentile

try:
    from bench.bounded_gas_contention import failure_row, parse_ints, rpc_read, summarize
    from tools.network import parse_quantity
    OPTIONAL_IMPORT_ERROR: Exception | None = None
except ImportError as exc:  # host-only source checks may omit Web3 dependencies
    OPTIONAL_IMPORT_ERROR = exc


class WatcherStatisticsTests(unittest.TestCase):
    def test_bootstrap_interval_is_deterministic_and_contains_median(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        first = bootstrap_median_ci(values, samples=2_000, confidence=0.95, seed=7)
        second = bootstrap_median_ci(values, samples=2_000, confidence=0.95, seed=7)
        self.assertEqual(first, second)
        self.assertLessEqual(first[0], 3.0)
        self.assertGreaterEqual(first[1], 3.0)
        self.assertEqual(percentile(values, 0.95), 4.8)


@unittest.skipIf(OPTIONAL_IMPORT_ERROR is not None, f"optional experiment dependencies unavailable: {OPTIONAL_IMPORT_ERROR}")
class NetworkQuantityTests(unittest.TestCase):
    def test_decimal_and_hex_gas_limits(self) -> None:
        self.assertEqual(parse_quantity("30000000", name="BLOCK_GAS_LIMIT"), 30_000_000)  # type: ignore[name-defined]
        self.assertEqual(parse_quantity("0x1c9c380", name="BLOCK_GAS_LIMIT"), 30_000_000)  # type: ignore[name-defined]
        with self.assertRaises(ValueError):
            parse_quantity("0", name="BLOCK_GAS_LIMIT")  # type: ignore[name-defined]


@unittest.skipIf(OPTIONAL_IMPORT_ERROR is not None, f"optional experiment dependencies unavailable: {OPTIONAL_IMPORT_ERROR}")
class ContentionSummaryTests(unittest.TestCase):
    def test_parse_and_summary(self) -> None:
        self.assertEqual(parse_ints("0,10,0x19"), [0, 10, 25])  # type: ignore[name-defined]
        rows = [
            {
                "block_gas_limit": 30_000_000,
                "flood_count": 10,
                "invariant_ok": True,
                "honest_latency_ms": 100.0,
                "honest_block_offset": 1,
                "honest_blocks_after_first_flood": 0,
                "flood_block_span": 1,
                "flood_gas_total": 1_000_000,
                "flood_in_honest_block": 10,
                "honest_block_utilization": 0.5,
                "flood_broadcast_ms": 25.0,
            },
            {
                "block_gas_limit": 30_000_000,
                "flood_count": 10,
                "invariant_ok": True,
                "honest_latency_ms": 200.0,
                "honest_block_offset": 2,
                "honest_blocks_after_first_flood": 1,
                "flood_block_span": 2,
                "flood_gas_total": 1_100_000,
                "flood_in_honest_block": 4,
                "honest_block_utilization": 0.75,
                "flood_broadcast_ms": 30.0,
            },
        ]
        result = summarize(rows)  # type: ignore[name-defined]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["runs"], 2)
        self.assertEqual(result[0]["success_rate"], 1.0)
        self.assertEqual(result[0]["honest_latency_ms_median"], 150.0)

    def test_rpc_read_retries_transient_failure(self) -> None:
        state = {"calls": 0}

        def operation() -> int:
            state["calls"] += 1
            if state["calls"] < 3:
                raise ConnectionError("transient")
            return 42

        self.assertEqual(
            rpc_read(operation, label="test", attempts=3, initial_delay_s=0),  # type: ignore[name-defined]
            42,
        )
        self.assertEqual(state["calls"], 3)

    def test_failure_row_does_not_require_rpc(self) -> None:
        import argparse

        args = argparse.Namespace(
            tag="test", validators=4, resolver_parallelism=20, gas_price=0,
            honest_delay_ms=100.0, alignment_delay_ms=50.0, broadcast_parallelism=64,
        )
        try:
            raise ConnectionError("rpc down")
        except ConnectionError as exc:
            row = failure_row(  # type: ignore[name-defined]
                args=args, repetition=0, flood_count=10,
                block_gas_limit=30_000_000, exc=exc,
            )
        self.assertEqual(row["block_gas_limit"], 30_000_000)
        self.assertFalse(row["invariant_ok"])
        self.assertIn("rpc down", row["error"])


if __name__ == "__main__":
    unittest.main()
