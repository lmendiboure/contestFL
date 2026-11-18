"""Disjoint protocol outcomes for challenges near the optimistic deadline.

A challenge that never entered the chain cannot invoke expireChallenge. A
challenge admitted on time but not resolved can enter the explicit timeout
abort path. This classification avoids reporting cleanup aborts as timeouts.
"""
def classify(*, included_before_deadline: bool, response_timed_out: bool, aborted_onchain: bool):
    if not included_before_deadline:
        if response_timed_out or aborted_onchain:
            raise ValueError("missed challenge cannot itself trigger resolver expiry")
        return "coverage_miss_C1"
    if response_timed_out:
        if not aborted_onchain:
            raise ValueError("resolver timeout without an on-chain abort is not confirmed")
        return "resolver_timeout_abort_onchain"
    if aborted_onchain:
        raise ValueError("abort cannot be attributed to resolver timeout")
    return "accepted_unresolved_or_resolved"
