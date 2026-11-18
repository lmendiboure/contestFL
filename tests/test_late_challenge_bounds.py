"""Regression tests for block sampling after an honest transaction receipt."""
import unittest
from review.block_bounds import sampled_challenge_blocks


class ChallengeBlockWindowTests(unittest.TestCase):
    def test_deadline_in_future_does_not_query_unmined_blocks(self):
        self.assertEqual(list(sampled_challenge_blocks(30, 40, 38)), list(range(30, 39)))

    def test_chain_head_past_deadline_excludes_post_window_blocks(self):
        self.assertEqual(list(sampled_challenge_blocks(30, 40, 45)), list(range(30, 41)))

    def test_chain_head_before_measurement_start_is_empty(self):
        self.assertEqual(list(sampled_challenge_blocks(30, 40, 29)), [])

    def test_negative_block_rejected(self):
        with self.assertRaises(ValueError):
            sampled_challenge_blocks(-1, 40, 38)


if __name__ == '__main__':
    unittest.main()
