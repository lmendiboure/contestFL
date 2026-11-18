# Reproduction guide

## Prerequisites

- Ubuntu/Linux x86-64 and Bash, GNU Make, Python 3.10+.
- Docker Engine and Docker Compose v2, with permission to access the local daemon.
- Internet access on first setup for Besu images, Python dependencies, and Solidity compiler 0.8.24.
- Java 17+ for TLC model checking.
- For substantial campaigns, plan for at least 16 GiB RAM and 30 GiB free disk. Requirements depend on client count and dataset size.

All chain accounts are for an **isolated test network**. Do not expose RPC port 8545 to an untrusted network. The Docker subnets in `.env.example` may need changing if they overlap with your LAN/VPN.

## Local checks (no Docker required)

```bash
./scripts/check_repository.sh
python3 tools/verify_reference_results.py
```

The repository check performs shell/Python validation, unit tests, reference-data integrity checks, and bounded auxiliary formal checks. Docker/Web3-dependent tests can be skipped if optional dependencies are unavailable. This check does not reproduce an on-chain measurement.

## Minimal blockchain run

```bash
cp .env.example .env
./scripts/preflight.sh
./review/run_review_suite.sh smoke
```

The run creates logs and stage status information under `review_outputs/`. A failed stage stops the campaign. Inspect the files produced before attributing new observations to an experiment.

## Complete campaigns

```bash
# Design and reference campaigns
SUITE=paper ./run_all_from_scratch.sh

# Additional dependent-correction, adversarial and multi-round stages
BASE_RUN_ID=contestfl_full ./review/run_review_suite.sh full
```

These commands may recreate the isolated chain. Do not run concurrently. Preserve the generated run directory and environment metadata if results will be reported.

## Analysis and retained data

The `results/reference/` directory includes archived observations and summary files from the reference evaluation. `evidence/revision_2026_11/` contains selected paired-policy and Flower multi-round results. To verify the source and data provenance, consult [Data and provenance](data-and-provenance.md).

A full re-run is not implied by the source checks alone. The GitHub ZIP includes no live Docker runtime state, secrets, or local `.env` file.
