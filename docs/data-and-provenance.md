# Data and provenance

## Files included with the repository

- `results/reference/archives/`: retained raw benchmark archives for the reference evaluation.
- `results/reference/summaries/`: corresponding reports and processed CSV/JSON tables.
- `figures/reference/`: reference plots and their LaTeX insertion snippets.
- `evidence/revision_2026_11/`: compact extracts from the paired causal-recovery and multi-round Flower campaigns.
- `formal/retained/`: retained bounded verification and ablation outputs.

The source contract used for the additional November on-chain and Flower campaigns is `contracts/ContestFLExperiment.sol`. The SHA-256 of that source file is:

```text
a0f9c03ba39e3ce92ce505e3b3b17c7f6a3c7c7e42da18efa5ee8339d42f567b
```

The larger archive with EVM receipts, complete model checkpoints, and raw traces is **not committed in the Git repository**. The corresponding archived evidence bundle is identified in `provenance/experiment_sources.json`. Make that archive available as a versioned release asset or DOI-backed dataset when publishing the artifact; the source repo alone does not contain every large raw file.

## Validation

```bash
./scripts/check_repository.sh
python3 tools/verify_reference_results.py
sha256sum -c SHA256SUMS
```

`SHA256SUMS` records published repository files (not generated runtime state). The file under `provenance/experiment_sources.json` records the underlying measured-source hashes and the separate evidence-bundle hash. It provides traceability without distributing author correspondence or intermediary working notes.

The reference and additional measurement groups use different configurations. The individual result tables and commands, rather than the repository packaging date, establish the interpretation of each result.
