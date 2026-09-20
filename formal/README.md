# ContestFL finite-state model

`ContestFL.tla` abstracts the recovery loop at the level needed for the paper's
claims: a current checkpoint version, a challenge window, successful revision,
provisional replacement, bounded retries, certified fallback, abort, and final
checkpoint installation.

Two finite configurations are checked:

- `MC_Coverage.cfg`: an honest challenge is guaranteed for every invalid current
  version; policy-valid finalization is checked.
- `MC_Structural.cfg`: challenge coverage is not assumed; structural properties
  remain checked, while invalid-but-unchallenged finalization is deliberately
  permitted.

Run:

```bash
./formal/run_tlc.sh
```

The script downloads the official pinned `tla2tools.jar`, checks its published
SHA-1, runs TLC, retains raw output, and extracts generated/distinct-state counts.
The finite model is supporting validation. The parameterized claims rely on the
mathematical proofs in `supplementary/contestfl_formal_supplement.tex`.

## Reproducibility output

`run_tlc.sh` pins `tla2tools.jar` v1.7.4 and verifies its SHA-1 before execution. It emits raw console output, version information, JSON/Markdown summaries, and a LaTeX table containing generated states, distinct states, graph depth, and success. The state counts must come from the retained run; they are never prefilled in the source.

## Auxiliary retained checks

`feature_ablation_check.py` executes the property-specific finite transition
systems used to demonstrate necessity of snapshotting, dependency propagation,
renewed windows, bounded retries, and fallback/safe abort.

`retained/dependency_dag/` contains the aggregate output of the separate
three-key exhaustive model. Its original generator was not found in the supplied
source archives. `validate_retained_dag.py` validates the retained table's schema
and reported invariants but deliberately does not claim to reconstruct the
missing state graph.
