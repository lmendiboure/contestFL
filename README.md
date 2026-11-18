# ContestFL

ContestFL provides an accountable recovery mechanism for contested decisions in cross-organization federated learning. This repository includes the protocol evaluation contract, comparison implementations, the Hyperledger Besu/QBFT harness, a Flower integration, formal models and experiment analysis code.

## Requirements

- Ubuntu/Linux (x86-64), Bash, GNU Make, `unzip` and Python 3.10+.
- Docker Engine with Compose v2 for on-chain experiments; a running Docker daemon accessible to the current user.
- Internet access for the initial image builds and installation of `solc` 0.8.24.
- Java 17+ for TLC model checking. The host-only source/reference checks do not require Java or Docker.
- For full campaigns, allow at least 16 GiB RAM and 30 GiB free disk; workloads and runtime vary.

The `.env.example` file contains isolated test-network defaults. **Do not expose the funded test chain or reuse its accounts on a production network.** If the default Docker subnets conflict with a local LAN or VPN, change the network settings in `.env` before starting.

## Validate the source and retained reference data

```bash
./scripts/check_repository.sh
# Tests and reference-integrity checks without launching Besu

./review/run_review_suite.sh check
# Adds local window analysis (model-based, not a new on-chain measurement)
```

These commands verify source syntax, tests, retained output integrity and bounded formal checks. Some unit tests skip optional Docker/Web3 dependencies. They do not replace an on-chain reproduction.

## Run a Besu smoke test

```bash
cp .env.example .env
./scripts/preflight.sh
./review/run_review_suite.sh smoke
```

The larger reviewer-oriented suite is:

```bash
BASE_RUN_ID=contestfl_revision ./review/run_review_suite.sh full
```

The full suite involves multiple Besu network restarts and can consume considerable time and disk. Each stage records logs and status; failures are not silently converted into successful runs. Review the outputs under `review_outputs/` before using any newly generated figure or claim. Consult [`docs/MAJOR_REVISION_RUNBOOK.md`](docs/MAJOR_REVISION_RUNBOOK.md) for the detailed stage descriptions.

## Reproduce the retained original evaluation campaigns

```bash
SUITE=smoke ./run_all_from_scratch.sh
SUITE=paper ./run_all_from_scratch.sh
```

The original paper workflows cover the design comparisons, scaling, authenticated-state experiments, Flower integration, watcher measurements, controlled network-delay sensitivity and TLA+ checks. Detailed claim-to-command mappings are in [`ARTIFACT_EVALUATION.md`](ARTIFACT_EVALUATION.md). The retained historical results live in `results/reference/archives/` and `results/reference/summaries/`, with paper figures under `figures/reference/`. Do not conflate these historical reference measurements with the November campaign: the experiment configuration and instrumentation differ.

## Repository structure

| Path | Content |
|---|---|
| `contracts/` | ContestFL evaluation contract and common-substrate alternatives |
| `bench/` | Original blockchain benchmarking and analysis |
| `review/` | Additional causal-recovery, flood, termination and multi-round experiments |
| `ml/` | Flower/MNIST integration and checkpoint handling |
| `formal/`, `supplementary/` | TLA+ / TLC and supporting formal analyses |
| `tests/` | Source-level and unit tests |
| `results/reference/` | Preserved earlier experiment outputs |
| `evidence/revision_2026_11/` | Small, exact result tables and analyses from November 2026 |
| `figures/reference/` | Figures from the original evaluation |
| `tools/`, `scripts/` | Build, deployment, analysis and artifact utilities |

## Reproducibility and release data

Start with [`ARTIFACT_RELEASE_2026_11.md`](ARTIFACT_RELEASE_2026_11.md) for evidence provenance, exact source hashes, and the separation between files committed here and the full experimental data archive. [`REVISION_2026_11_MANIFEST.json`](REVISION_2026_11_MANIFEST.json) is machine-readable. `

## License

See [`LICENSE`](LICENSE).
