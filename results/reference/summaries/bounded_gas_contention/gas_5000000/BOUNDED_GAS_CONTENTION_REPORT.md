# Bounded block-gas contention

A valid finalization transaction for an independent clean round is submitted after a burst of unsupported aggregate challenges has entered the transaction pool. All transactions use the same gas price. The reported delay is therefore an application-level inclusion-contention measurement under the configured Besu/QBFT block gas limit, not a proof of denial-of-service resistance.

| Block gas limit | Flood | Runs | Success | Honest latency median | p95 | Honest block offset | Honest-block gas use | Flood span |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5,000,000 | 0 | 5 | 100% | 947.1 ms | 956.8 ms | 1.0 | 0.7% | 0.0 |
| 5,000,000 | 10 | 5 | 100% | 840.5 ms | 937.7 ms | 1.0 | 40.6% | 1.0 |
| 5,000,000 | 25 | 5 | 100% | 832.1 ms | 840.3 ms | 1.0 | 96.5% | 2.0 |
| 5,000,000 | 50 | 5 | 100% | 830.3 ms | 840.7 ms | 1.0 | 96.5% | 3.0 |
| 5,000,000 | 100 | 5 | 100% | 726.8 ms | 738.6 ms | 1.0 | 96.5% | 5.0 |

Interpretation boundary: the experiment uses a permissioned single-host testbed and does not model malicious validators, network saturation, transaction censorship, or monetary bonds. It isolates whether admitted challenge transactions consume enough bounded block capacity to delay a simultaneously valid protocol transaction.
