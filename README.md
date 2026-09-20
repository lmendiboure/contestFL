# ContestFL artifact

This repository contains the implementation, evaluation harness, formal model,
and reference outputs for ContestFL. It builds permissioned Hyperledger
Besu/QBFT networks, deploys the protocol and comparison contracts, executes the
fault and scaling campaigns, records transaction-level data, and regenerates
publication figures and tables.

## Requirements

- Linux with Bash, GNU Make, and `unzip`;
- Docker Engine with the Docker Compose plugin;
- Python 3.10 or newer on the host;
- Java 17 or newer for the TLA+/TLC checks;
- at least 8 GiB of free disk space; more is recommended for the complete suite.

The Python dependencies used by the experiments are installed in pinned Docker
images. Host Python is used for orchestration, lightweight source/reference checks, environment capture, artifact assembly, and TLC-output parsing. Plot regeneration additionally uses NumPy, pandas, and Matplotlib; the Docker tools image supplies the pinned versions.

Check the host before running anything:

```bash
./scripts/preflight.sh
```

A source-only check that does not start Besu is available as:

```bash
./scripts/check_repository.sh
```

## Quick start

The smoke suite checks the contracts, network, Flower path, authenticated-state
path, off-chain tree code, and formal model with reduced repetitions:

```bash
SUITE=smoke ./run_all_from_scratch.sh
```

The complete paper suite, including the watcher, bounded-capacity contention, authenticated-state, Flower, and formal checks, is:

```bash
SUITE=paper ./run_all_from_scratch.sh
```

The runner creates `.env` from `.env.example` only when `.env` is absent. It
never overwrites a local configuration. If the host interpreter has a
non-standard name, set it explicitly:

```bash
PYTHON_BIN=/path/to/python3 SUITE=paper ./run_all_from_scratch.sh
```

A completed suite produces a checksum-protected release:

```text
artifacts/<UTC_ID>_<suite>/
artifacts/<UTC_ID>_<suite>.zip
```

Runs can be resumed with the same base identifier:

```bash
BASE_RUN_ID=<UTC_ID> RESUME=1 SUITE=paper ./run_all_from_scratch.sh
```

`SKIP_TLC=1` is available only for offline debugging. It must not be used for a
paper artifact that reports TLC state counts.

## Individual campaigns

```bash
./run_campaign.sh stable
./run_competitor_extension.sh
./run_targeted_extension.sh
./run_root_only_ablation.sh
./run_flower_mnist_e2e.sh
./run_network_smoke.sh
./run_smt_offchain.sh
./run_root_depth_sensitivity.sh
./formal/run_tlc.sh
```

The authenticated-state campaign compares per-client materialization with
root-only commitments. The default root-only workloads are `clean`,
`bad_admission`, and `bad_aggregate`. Flower exercises a deliberately incorrect
aggregate checkpoint, a `REVISED` verdict, corrected republication, a renewed
window, and finalization of the corrected checkpoint.

## Reference outputs

`results/reference/archives/` contains every retained result bundle available for the final paper, including raw per-run data where it was supplied. Directly inspectable summaries are under
`results/reference/summaries/`. Publication-ready vector figures are under
`figures/reference/`.

See:

- `ARTIFACT_EVALUATION.md` for the claim-to-command mapping;
- `RESULTS.md` for verified reference values and interpretation limits;
- `results/reference/README.md` for the bundle inventory;
- `docs/` for campaign-specific methodology;
- `supplementary/` and `formal/` for the proofs and TLA+ model.

## Repository layout

```text
bench/          experiment drivers, adapters, and analyses
contracts/      ContestFL and comparison contracts
formal/         TLA+ specification, TLC configurations, parser, and launcher
ml/             deterministic Flower/MNIST integration
results/        immutable reference bundles; new runs are written to results/runs
figures/        retained publication figures
supplementary/  extended proofs and authenticated-state specification
tests/          unit and source-level tests
tools/          network, deployment, profiling, and artifact utilities
```

## Scope

The comparison contracts represent architectural design points under the same
workload and deployment; they are not line-by-line reproductions of named
systems. The Flower experiment is an end-to-end applicability check rather than
an accuracy, convergence, or throughput study. The controlled RTT experiment
uses colocated validators and is a sensitivity check, not a geographically
distributed QBFT benchmark.

## Additional validation campaigns

Two additional experiments used in the final evaluation are provided without changing the protocol contract:

```bash
./run_watcher_extension.sh
./run_bounded_gas_contention.sh
```

The first collects 30 retained watcher measurements at approximately 100 and
1,000 MiB and reports bootstrap confidence intervals. The second restarts Besu
with a bounded block gas limit and measures whether an unsupported challenge
burst delays a valid finalization transaction for an independent clean round.
See [`docs/ADDITIONAL_CAMPAIGNS.md`](docs/ADDITIONAL_CAMPAIGNS.md) for
scope, commands, outputs, interpretation limits, and watcher post-processing
resume instructions.

