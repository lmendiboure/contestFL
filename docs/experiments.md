# Experimental evaluation

The repository provides the experiments used to evaluate ContestFL's design choices, recovery behavior, and execution costs. The commands below operate on an isolated Besu/QBFT test network. Their outputs are saved under `results/runs/` or `review_outputs/`; do not interpret a reduced smoke run as a reproduction of the reported sample sizes.

## 1. Design comparisons and scalability

To run the complete reference evaluation:

```bash
cp .env.example .env
SUITE=paper ./run_all_from_scratch.sh
```

Individual campaigns can be launched separately:

| Experiment | Command | Purpose |
|---|---|---|
| Core recovery and fault scenarios | `./run_campaign.sh stable` | Challenge and correction outcomes |
| Comparison designs | `./run_competitor_extension.sh` | Verification strategies on a common evaluation substrate |
| Scaling and recovery chains | `./run_targeted_extension.sh` | Client count, dependency and replay effects |
| Authenticated-state ablation | `./run_root_only_ablation.sh` | Root-only versus materialized state |
| Merkle depth | `./run_root_depth_sensitivity.sh` | Proof-size/depth sensitivity |
| Flower integration | `./run_flower_mnist_e2e.sh` | Training-to-checkpoint integration |
| Network-delay sensitivity | `./run_network_smoke.sh` | Controlled validator delay sensitivity |
| Off-chain authenticated-state costs | `./run_smt_offchain.sh` | State and proof operations |
| Watcher work | `./run_watcher_extension.sh` | Inspection time and challenge-window inputs |
| Bounded contention | `./run_bounded_gas_contention.sh` | Transaction capacity and challenge bursts |
| Auxiliary formal analysis | `./formal/run_auxiliary_checks.sh` | Bounded rule and dependency checks |
| TLC configurations | `./formal/run_tlc.sh` | Finite-state lifecycle checks |

Raw reference archives and readable summaries are in `results/reference/`. The comparison contracts implement controlled architectural design points. They should not be described as independent reimplementations of named external systems.

## 2. Causal recovery and multi-round evaluation

The additional workload drivers under `review/` cover dependent corrections, adversarial scheduling, sustained challenge traffic, termination behavior, and Flower multi-round execution.

```bash
# Source checks and a reduced experiment
./review/run_review_suite.sh check
./review/run_review_suite.sh smoke

# Full integrated campaign (substantial runtime and disk usage)
BASE_RUN_ID=contestfl_reproduction ./review/run_review_suite.sh full
```

Individual drivers can be used where a narrower reproduction is needed, including `review/run_causal_v4.sh`, `review/run_flower_multiround.sh`, `review/run_termination_liveness.sh`, and `review/run_final_assurance.sh`. These entry points may manage or restart the dedicated Besu network. **Do not run multiple blockchain campaigns concurrently against the same Docker environment.**

The full archived EVM receipts and Flower checkpoint files for the reported November campaign are distributed separately. The corresponding compact tables are included in `evidence/revision_2026_11/`. The original reference sweeps and the additional experiments have different configurations/instrumentation; use their respective records for comparisons rather than treating them as directly paired.

## 3. Formal checks

```bash
./formal/run_auxiliary_checks.sh
./formal/run_tlc.sh
```

TLC requires Java and downloads the pinned model-checker JAR if absent. See `formal/README.md` for the model's scope and the coverage/structural configurations.

## Results and interpretation

See [Results](results.md) for selected measured values and [Data and provenance](data-and-provenance.md) for source hashes and the full evidence archive.
