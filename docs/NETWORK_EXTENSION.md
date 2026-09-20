# Controlled network-delay extension

## Research question

How sensitive are ContestFL's nominal and corrective finalization paths to
inter-validator latency, and does the effect differ between four and seven QBFT
validators?

## Default matrix

| Validators | Requested RTTs | Clients | Scenarios | Measured runs | Warm-up |
|---:|---|---:|---|---:|---:|
| 4 | 0, 10, 25, 50 ms | 100 | nominal, correction_laundering | 5 | 1 |
| 7 | 0, 25 ms | 100 | nominal, correction_laundering | 5 | 1 |

## Isolation of P2P delay

The generated Compose network has two bridges. Besu static enodes use the P2P
subnet, while the benchmark runner reaches RPC endpoints over the control subnet.
The helper locates the interface carrying each validator's P2P IP and applies:

```text
tc qdisc replace dev <p2p-interface> root netem delay <RTT/2>ms
```

No delay is applied to the control interface.

## Calibration and safety

Before long experiments, `tools/netem.sh preflight`:

1. measures the baseline validator-to-validator ping RTT;
2. applies a 20 ms requested RTT;
3. verifies that the observed RTT increases materially;
4. removes the qdisc;
5. verifies that the RTT recovers.

Every measured configuration records a fresh probe in `network_probe.csv`.
The campaign clears all qdiscs before changing RTT, before shutting down a
network, and in the global exit trap.

## Metrics

- requested and observed P2P RTT;
- end-to-end round latency;
- block span;
- gas and calldata as consistency checks;
- transaction receipts and reverts;
- final invariant outcome.

## Scope limitation

This is controlled delay emulation on one host. It characterizes protocol
sensitivity to P2P latency but not bandwidth contention, independent host
failures, routing asymmetry, clock behavior, or geographically distributed QBFT.
