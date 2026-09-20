# Watcher pipeline report

This experiment measures the full local verification pipeline used to satisfy challenge coverage. It does not treat `q * replay` as the watcher cost: an always-on watcher inspects every round, while `q` applies only to dispute handling after detection.

| Clients | Cache mode | Update body/client | Total artifacts | Local verification median | Bootstrap CI | p95 | Local throughput |
|---:|:---|---:|---:|---:|---:|---:|---:|
| 100 | fadvise | 1024 KiB | 100.0 MiB | 166.99 ms | [158.00, 170.04] ms | 179.29 ms | 595.3 MiB/s |
| 100 | fadvise | 10240 KiB | 1000.0 MiB | 1843.91 ms | [1835.28, 1858.94] ms | 1901.49 ms | 541.1 MiB/s |
| 100 | warm | 1024 KiB | 100.0 MiB | 105.55 ms | [95.88, 107.43] ms | 119.60 ms | 939.7 MiB/s |
| 100 | warm | 10240 KiB | 1000.0 MiB | 1186.17 ms | [1151.25, 1308.15] ms | 1362.02 ms | 841.0 MiB/s |

## Median phase decomposition

| Artifacts | Cache | Read | SHA-256 binding | Parse | Accumulate | Checkpoint | Challenge package | CPU / wall |
|---:|:---|---:|---:|---:|---:|---:|---:|---:|
| 100.0 MiB | fadvise | 73.49 ms | 65.09 ms | 12.00 ms | 12.10 ms | 1.48 ms | 0.017 ms | 0.79 |
| 1000.0 MiB | fadvise | 697.48 ms | 683.86 ms | 206.66 ms | 238.65 ms | 18.40 ms | 0.022 ms | 0.88 |
| 100.0 MiB | warm | 12.93 ms | 64.94 ms | 12.30 ms | 12.29 ms | 1.57 ms | 0.018 ms | 1.00 |
| 1000.0 MiB | warm | 134.91 ms | 639.43 ms | 180.30 ms | 216.04 ms | 17.33 ms | 0.021 ms | 1.00 |

Interpretation boundary: wide-area/object-store transfer is not measured. `watcher_cost_projection.csv` adds ideal line-rate projections in nominal decimal Mbit/s; it must not be described as a measured network result.
