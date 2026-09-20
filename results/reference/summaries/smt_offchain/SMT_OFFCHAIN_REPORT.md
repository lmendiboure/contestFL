# Off-chain sparse-Merkle microbenchmark

- Depth: **32**
- Retained repetitions per point: **30**
- Client populations: **10, 100, 500**
- Correctness failures: **0**

## 500-client result

| Operation | Median wall time (ms) | p95 wall time (ms) | Proof bytes |
|---|---:|---:|---:|
| build_and_root | 12.334 | 14.015 | 0 |
| proof_generation | 11.725 | 14.018 | 1057 |
| proof_verification | 0.028 | 0.048 | 1057 |
| single_update_and_root | 11.825 | 13.083 | 0 |

These measurements cover tree construction, one leaf update followed by root recomputation, proof generation, and proof verification in the dependency-free Python reference implementation. They exclude artifact hashing, disk I/O, network transfer, and EVM verification. The implementation recomputes populated levels rather than maintaining an optimized incremental cache, so the result is a conservative engineering measurement rather than a lower bound.
