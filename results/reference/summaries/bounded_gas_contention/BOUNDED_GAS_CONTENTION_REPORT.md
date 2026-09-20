# Bounded block-gas contention

A valid finalization transaction for an independent clean round is submitted after a burst of unsupported aggregate challenges has entered the transaction pool. All transactions use the same gas price. The reported delay is therefore an application-level inclusion-contention measurement under the configured Besu/QBFT block gas limit, not a proof of denial-of-service resistance.

| Block gas limit | Flood | Runs | Success | Honest latency median | p95 | Honest block offset | Honest-block gas use | Flood span |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5,000,000 | 0 | 5 | 100% | 947.1 ms | 956.8 ms | 1.0 | 0.7% | 0.0 |
| 5,000,000 | 10 | 5 | 100% | 840.5 ms | 937.7 ms | 1.0 | 40.6% | 1.0 |
| 5,000,000 | 25 | 5 | 100% | 832.1 ms | 840.3 ms | 1.0 | 96.5% | 2.0 |
| 5,000,000 | 50 | 5 | 100% | 830.3 ms | 840.7 ms | 1.0 | 96.5% | 3.0 |
| 5,000,000 | 100 | 5 | 100% | 726.8 ms | 738.6 ms | 1.0 | 96.5% | 5.0 |
| 10,000,000 | 0 | 5 | 100% | 847.7 ms | 852.0 ms | 1.0 | 0.3% | 0.0 |
| 10,000,000 | 10 | 5 | 100% | 846.7 ms | 929.3 ms | 1.0 | 20.3% | 1.0 |
| 10,000,000 | 25 | 5 | 100% | 837.6 ms | 842.3 ms | 1.0 | 50.2% | 1.0 |
| 10,000,000 | 50 | 5 | 100% | 834.2 ms | 840.3 ms | 1.0 | 98.1% | 2.0 |
| 10,000,000 | 100 | 5 | 100% | 732.0 ms | 735.1 ms | 1.0 | 98.1% | 3.0 |
| 30,000,000 | 0 | 5 | 100% | 844.5 ms | 854.2 ms | 1.0 | 0.1% | 0.0 |
| 30,000,000 | 10 | 5 | 100% | 837.2 ms | 847.1 ms | 1.0 | 6.8% | 1.0 |
| 30,000,000 | 25 | 5 | 100% | 842.0 ms | 843.3 ms | 1.0 | 16.7% | 1.0 |
| 30,000,000 | 50 | 5 | 100% | 840.6 ms | 842.4 ms | 1.0 | 33.4% | 1.0 |
| 30,000,000 | 100 | 5 | 100% | 734.8 ms | 743.0 ms | 1.0 | 66.6% | 1.0 |

Interpretation boundary: the experiment uses a permissioned single-host testbed and does not model malicious validators, network saturation, transaction censorship, or monetary bonds. It isolates whether admitted challenge transactions consume enough bounded block capacity to delay a simultaneously valid protocol transaction.
