"""Pure block-window sampling for the on-chain challenge-load probe.

Never request a future block, and never count a post-deadline block in the
challenge-window saturation metric. No Docker or Web3 dependency.
"""
from __future__ import annotations


def sampled_challenge_blocks(first_target: int, deadline: int, latest_mined_block: int) -> range:
    if min(first_target, deadline, latest_mined_block) < 0:
        raise ValueError("block numbers must be nonnegative")
    return range(first_target, min(deadline, latest_mined_block) + 1)
