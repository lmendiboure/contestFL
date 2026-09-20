# Targeted experimental campaigns

## Capacity and decision batching

Purpose: locate transaction/block-capacity thresholds rather than extrapolate
from only 10, 25, 50, and 100 clients.

Default parameters:

- clients: 10, 25, 50, 75, 100, 150, 200, 300, 500;
- batch size: 10, 25, 50, 100;
- scenarios: `logging_only`, `nominal`;
- 4 validators.

Outputs: `capacity_summary.csv`, `capacity_blocks.*`, and `capacity_gas.*`.

## Challenge-window sensitivity

Purpose: separate the implementation cost from the deployment policy.

Default challenge windows: 1, 2, 5, and 10 blocks. Outputs include latency and
block span as a function of the configured window.

## Challenge flooding

Purpose: validate that false challenges consume transactions, gas, and resolver
CPU but do not create correction epochs.

Default sweep:

- false challenges: 1, 5, 10, 20, 50, 100;
- batches resolved concurrently: 1, 5, 10, 20.

The runner derives every `UPHELD` result through the admission receipt adapter.

## Optimistic replay regime

The local microbenchmark measures hashing and deterministic replay for update
sizes 4 KiB, 256 KiB, 1 MiB, and 10 MiB. It reports eager verification CPU for
every round and expected optimistic CPU for challenge rates from 0 to 1.

These results quantify computation saved by on-demand replay. They do not claim
that the blocking challenge window disappears.

## Network sensitivity

`tc/netem` applies half the requested RTT as egress delay to each validator P2P interface. The
campaign measures 0, 10, 25, and 50 ms approximate RTT for 4 and 7 validators.
Set `SKIP_NETWORK_SWEEP=1` where Docker-socket network emulation is unavailable.

A final paper may complement this controlled campaign with one physical
multi-host configuration; it is not necessary to repeat every fault scenario
on multiple hosts.

## Randomized invariant testing

The model-based fuzzer generates legal combinations of challenges, revisions,
`MOOT` descendants, coordinator retries, fallbacks, aborts, and premature
finalization attempts. It checks at every step that:

- retry use never exceeds the budget;
- an open or unresolved transition cannot finalize;
- `READY` contains a terminal published checkpoint;
- `FINALIZED` has no open challenge and no pending replacement;
- every sequence ends in `FINALIZED` or `ABORTED`.
