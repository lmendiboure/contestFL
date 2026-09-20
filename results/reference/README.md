# Retained reference results

`archives/` contains the complete retained bundles available when this release
was assembled. `summaries/` exposes the reports and processed tables needed to
inspect the paper values without unpacking the raw archives. `MANIFEST.csv`
records archive sizes and SHA-256 hashes.

## Campaigns

- `stable_core`: original protocol campaign and fault scenarios;
- `competitor_extension`: audit-only, eager, single-shot, and ContestFL comparison;
- `targeted_extension`: clean scaling, affected decisions, repeated replacements, flooding, and replay;
- `root_only_ablation`: materialized versus authenticated-state paths;
- `root_depth_sensitivity`: Merkle depth 32/64/128/256;
- `flower_mnist`: end-to-end Flower/PyTorch aggregate revision;
- `network_smoke`: 4/7 validators and controlled RTT sensitivity;
- `smt_offchain`: off-chain sparse-Merkle operations;
- `watcher_extension`: 30-run 100/1,000-MiB watcher measurements and C1 projections;
- `bounded_gas_contention`: 5/10/30-Mgas bounded-capacity challenge bursts;
- `dependency_dag_retained`: aggregate results of the bounded three-key DAG check;
- `feature_ablation_retained`: property-specific ablation outputs.

Run `python3 tools/verify_reference_results.py` to test archive readability and
the principal numerical/semantic claims. The dependency-DAG archive is retained
output: the original generator source was not recovered from the supplied
materials, as documented in the repository README.
