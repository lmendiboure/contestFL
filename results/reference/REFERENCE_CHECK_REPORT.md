# Reference result check

- Checks: **36**
- Passed: **36**
- Failed: **0**

| Status | Check | Observed | Expected |
|---|---|---:|---:|
| PASS | archive readable: bounded_gas_contention.zip | `None` | `None` |
| PASS | archive readable: competitor_extension.zip | `None` | `None` |
| PASS | archive readable: dependency_dag_retained.zip | `None` | `None` |
| PASS | archive readable: feature_ablation_retained.zip | `None` | `None` |
| PASS | archive readable: flower_mnist.zip | `None` | `None` |
| PASS | archive readable: network_smoke.zip | `None` | `None` |
| PASS | archive readable: root_depth_sensitivity.zip | `None` | `None` |
| PASS | archive readable: root_only_ablation.zip | `None` | `None` |
| PASS | archive readable: smt_offchain.zip | `None` | `None` |
| PASS | archive readable: stable_core.zip | `None` | `None` |
| PASS | archive readable: targeted_extension.zip | `None` | `None` |
| PASS | archive readable: watcher_extension.zip | `None` | `None` |
| PASS | root-only clean gas at 500 | `204140.0` | `204140` |
| PASS | materialized clean gas at 500 | `52944390.0` | `52944390` |
| PASS | root-only admission dispute gas at 500 | `561493.0` | `561493` |
| PASS | Flower total gas | `790759` | `790759` |
| PASS | Flower transaction count | `9` | `9` |
| PASS | Flower checkpoint equality | `True` | `True` |
| PASS | watcher 100 MiB inspection median | `166.98566050000002` | `166.9856605` |
| PASS | watcher 1000 MiB inspection median | `1843.9146874999997` | `1843.9146875` |
| PASS | contention flood span 5000000 | `5.0` | `5` |
| PASS | honest offset 5000000 | `1.0` | `1` |
| PASS | contention flood span 10000000 | `3.0` | `3` |
| PASS | honest offset 10000000 | `1.0` | `1` |
| PASS | contention flood span 30000000 | `1.0` | `1` |
| PASS | honest offset 30000000 | `1.0` | `1` |
| PASS | depth-32 challenge gas | `270941.0` | `270941` |
| PASS | depth-256 challenge gas | `616871.0` | `616871` |
| PASS | DAG rows | `12` | `12` |
| PASS | DAG invalid finalized under coverage | `0` | `0` |
| PASS | DAG nonterminal cycles under coverage | `0` | `0` |
| PASS | ablation frozen_snapshot | `['ORDER_SENSITIVE_ADJUDICATION']` | `['ORDER_SENSITIVE_ADJUDICATION']` |
| PASS | ablation dependency_propagation | `['DEADLOCK_PARENT_MISMATCH']` | `['DEADLOCK_PARENT_MISMATCH']` |
| PASS | ablation fresh_replacement_window | `['INVALID_FINALIZED']` | `['INVALID_FINALIZED']` |
| PASS | ablation bounded_retries | `['NONTERMINAL_CYCLE']` | `['NONTERMINAL_CYCLE']` |
| PASS | ablation fallback_or_abort | `['DEADLOCK_AT_TIMEOUT']` | `['DEADLOCK_AT_TIMEOUT']` |
