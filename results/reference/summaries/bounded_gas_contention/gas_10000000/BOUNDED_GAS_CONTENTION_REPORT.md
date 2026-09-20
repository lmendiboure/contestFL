# Bounded block-gas contention

A valid finalization transaction for an independent clean round is submitted after a burst of unsupported aggregate challenges has entered the transaction pool. All transactions use the same gas price. The reported delay is therefore an application-level inclusion-contention measurement under the configured Besu/QBFT block gas limit, not a proof of denial-of-service resistance.

| Block gas limit | Flood | Runs | Success | Honest latency median | p95 | Honest block offset | Honest-block gas use | Flood span |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10,000,000 | 0 | 5 | 100% | 847.7 ms | 852.0 ms | 1.0 | 0.3% | 0.0 |
| 10,000,000 | 10 | 5 | 100% | 846.7 ms | 929.3 ms | 1.0 | 20.3% | 1.0 |
| 10,000,000 | 25 | 5 | 100% | 837.6 ms | 842.3 ms | 1.0 | 50.2% | 1.0 |
| 10,000,000 | 50 | 5 | 100% | 834.2 ms | 840.3 ms | 1.0 | 98.1% | 2.0 |
| 10,000,000 | 100 | 5 | 100% | 732.0 ms | 735.1 ms | 1.0 | 98.1% | 3.0 |

Interpretation boundary: the experiment uses a permissioned single-host testbed and does not model malicious validators, network saturation, transaction censorship, or monetary bonds. It isolates whether admitted challenge transactions consume enough bounded block capacity to delay a simultaneously valid protocol transaction.
