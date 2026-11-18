# ContestFL

**Accountable post-dispute recovery for cross-organization federated learning.**

ContestFL records contestable decisions, manages their dependencies, and supports recovery of a canonical model checkpoint after a successful challenge. This repository contains the Solidity evaluation contract, a Hyperledger Besu/QBFT evaluation harness, Flower integration, formal models, reproducibility scripts, and the data used to produce the paper's experimental comparisons.

## Get started

Requirements: Linux, Python 3.10+, Bash, GNU Make, and Docker with Compose v2 for blockchain experiments. Java is required for TLA+ TLC. A first run needs Internet access to fetch container images and the configured Solidity compiler.

```bash
# Run source checks and validate included reference data (no Docker required)
./scripts/check_repository.sh

# Run a reduced end-to-end blockchain experiment (Docker required)
cp .env.example .env
./scripts/preflight.sh
./review/run_review_suite.sh smoke
```

The smoke test verifies the workflow; it does not reproduce the full published sample sizes. For a complete reproduction, follow [the experiment guide](docs/experiments.md).

## Where to look

| Topic | Location |
|---|---|
| Protocol and experimental contract | [`contracts/`](contracts/) · [architecture](docs/architecture.md) |
| Blockchain workloads, policies, and analysis | [`bench/`](bench/) and [`review/`](review/) |
| Flower multi-round workloads | [`ml/`](ml/) and [`review/`](review/) |
| Formal model and TLC configurations | [`formal/`](formal/) |
| Experiment commands | [Experiments](docs/experiments.md) |
| Installation and execution | [Reproduction guide](docs/reproduce.md) |
| Reference results and result interpretation | [Results](docs/results.md) |
| Dataset provenance and checksums | [Data and provenance](docs/data-and-provenance.md) |

The `review/` path is retained because the experiment launchers and imports use it. It contains executable research code, not reviewer correspondence.

## Data and reproducibility

The repository includes reference experiment archives under `results/reference/` and small result tables under `evidence/revision_2026_11/`. The larger multi-round Flower traces, EVM receipts, and related evidence are distributed as a separate research artifact; see [Data and provenance](docs/data-and-provenance.md). Results from distinct experimental setups are described separately in the guide, rather than combined into a single benchmark.

**Security:** the Docker/Besu network is an isolated evaluation environment with test accounts. Never connect it to public networks or use it with real assets or production credentials.

## License

See [LICENSE](LICENSE).
