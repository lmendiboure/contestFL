# ContestFL — November 2026 source and evidence release

## Scope of the public source

This repository is the updated source tree of the major-revision evaluation. It keeps the original evaluation scripts, reference data, figures and comparison contracts; it adds the causal-recovery, timeout/termination, multi-round Flower, congestion and validation code used in the revision.

The deployed evaluation-contract source corresponding to the November paired Besu and 200-round Flower data is `contracts/ContestFLExperiment.sol`:

```text
SHA-256: a0f9c03ba39e3ce92ce505e3b3b17c7f6a3c7c7e42da18efa5ee8339d42f567b
```

See `REVISION_2026_11_MANIFEST.json` for the original-source snapshot and the exact frozen source archive hash.

## Results included with the Git repository

`evidence/revision_2026_11/` contains **unaltered** extracted tables and analyses from recorded November results:

- `CAUSAL_RESULTS.json` — 25/100/500-client paired causal-recovery table and per-pair values;
- `PAIRED_POLICIES_RAW.csv` — raw policy comparison values from the same run;
- `CAUSAL_TABLE.tex`, `FLOWER_EAGER_TABLE.tex` — table material from the same source run;
- `MULTIROUND_PAIRED.csv`, `MULTIROUND_ANALYSIS.json` — analysis of five paired 20-round trajectories per policy.

No values in these files were recomputed or edited for the GitHub release. Their SHA-256 values are in the manifest.

## Full experimental data (separate archive)

The complete November evidence is supplied in a separate ZIP, `ContestFL_Supplementary_Existing_Code_Data_20261117.zip`, including:

- frozen exact source archive;
- paired causal-recovery Besu receipts and logs;
- all Flower trajectories, model files, restart/failure provenance and checksums;
- sustained-challenge-flood trials;
- causal TLC configurations and execution logs.

That ZIP is **not** committed to the Git repository. Its SHA-256 appears in `REVISION_2026_11_MANIFEST.json`. Upload the unchanged archive as a GitHub Release asset, an institutional repository artifact or a DOI-backed dataset, and link its persistent location in the article or the release description. Do not substitute a source snapshot or a generated summary for the measured raw evidence.

## Validation from the released source

```bash
bash scripts/check_repository.sh
./review/run_review_suite.sh check
```

For new on-chain measurements (requires Docker/Besu):

```bash
./review/run_review_suite.sh smoke
BASE_RUN_ID=replication ./review/run_review_suite.sh full
```

Reference analyses from the historical evaluation are under `results/reference/`, while the newer campaigns are documented in `review/` and `docs/`. A smoke test demonstrates protocol execution; it is not a reproduction of the published sample sizes. The November measurements were performed on Besu with the source identified above and preserved in the evidence archive. Source packaging does not re-run Besu.

## Historical records

`RELEASE_MANIFEST.json` describes the original reference release. `REVISION_SOURCE_MANIFEST.json` and `EXTENDED_V4_RELEASE_MANIFEST.json` describe earlier intermediate source-delivery stages, including test-status statements as of those earlier stages. These files are retained for provenance, not used as the November release status. The current release status is in `REVISION_2026_11_MANIFEST.json`.
