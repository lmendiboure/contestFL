# ContestFL targeted experimental extension

- Baseline rounds: **54**
- ContestFL rounds: **105**
- Baseline transactions: **8739**
- ContestFL transactions: **15576**
- Detected failures: **0**

## Generated summaries

- `targeted_clean_scaling_summary.csv`
- `affected_decisions_summary.csv`
- `faulty_replacement_chain_summary.csv`
- `targeted_flooding_summary.csv`
- `targeted_phase_summary.csv`
- `targeted_replay_summary.csv` when replay data are present

## Interpretation constraints

- The affected-decisions experiment varies the number of incorrect client-level admission decisions that jointly invalidate the aggregate; it does not create an artificial deeper FL dependency graph.
- The replacement-chain experiment counts faulty coordinator replacements after the initially faulty state. At the retry budget, the resolver installs the terminal fallback.
- Flooding resolution span is measured from the block containing the last opened challenge through finalization.
- Gas and calldata are deterministic for identical calls. Block spans are discrete and host/ledger-configuration dependent.
- Replay measures the in-memory deterministic aggregation kernel and excludes artifact retrieval, transfer, decryption, and deserialization.
