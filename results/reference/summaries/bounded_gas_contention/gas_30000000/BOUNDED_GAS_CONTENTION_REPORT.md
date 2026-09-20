# Bounded block-gas contention

A valid finalization transaction for an independent clean round is submitted after a burst of unsupported aggregate challenges has entered the transaction pool. All transactions use the same gas price. The reported delay is therefore an application-level inclusion-contention measurement under the configured Besu/QBFT block gas limit, not a proof of denial-of-service resistance.

| Block gas limit | Flood | Runs | Success | Honest latency median | p95 | Honest block offset | Honest-block gas use | Flood span |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30,000,000 | 0 | 5 | 100% | 844.5 ms | 854.2 ms | 1.0 | 0.1% | 0.0 |
| 30,000,000 | 10 | 5 | 100% | 837.2 ms | 847.1 ms | 1.0 | 6.8% | 1.0 |
| 30,000,000 | 25 | 5 | 100% | 842.0 ms | 843.3 ms | 1.0 | 16.7% | 1.0 |
| 30,000,000 | 50 | 5 | 100% | 840.6 ms | 842.4 ms | 1.0 | 33.4% | 1.0 |
| 30,000,000 | 100 | 5 | 100% | 734.8 ms | 743.0 ms | 1.0 | 66.6% | 1.0 |

Interpretation boundary: the experiment uses a permissioned single-host testbed and does not model malicious validators, network saturation, transaction censorship, or monetary bonds. It isolates whether admitted challenge transactions consume enough bounded block capacity to delay a simultaneously valid protocol transaction.
