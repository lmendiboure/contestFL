# Artifact evaluation guide

## Fast validation

```bash
./scripts/check_repository.sh
python3 tools/verify_reference_results.py
SUITE=smoke ./run_all_from_scratch.sh
```

The first two commands require only host Python. The smoke suite additionally
requires Docker and runs reduced workloads; it checks control flow rather than
reproducing retained medians.

## Full paper reproduction

```bash
SUITE=paper ./run_all_from_scratch.sh
```

This runs the stable, competitor, targeted, root-only, Flower, network, root
depth, SMT, watcher, bounded-contention, auxiliary formal, and TLA+ campaigns.
Set `SKIP_ADDITIONAL_CAMPAIGNS=1` only for debugging; a complete paper artifact
must not use it.

## Claim-to-command mapping

| Claim family | Command | Main output |
|---|---|---|
| Canonical recovery and fault scenarios | `./run_campaign.sh stable` | `REPORT.md` and raw blockchain CSVs |
| Audit/eager/single-shot comparison | `./run_competitor_extension.sh` | `COMPETITOR_EXTENSION_REPORT.md` |
| Scaling, recovery chains, flooding, replay | `./run_targeted_extension.sh` | `TARGETED_EXTENSION_REPORT.md` |
| Authenticated-state ablation | `./run_root_only_ablation.sh` | `ROOT_ONLY_ABLATION_REPORT.md` |
| Merkle-depth sensitivity | `./run_root_depth_sensitivity.sh` | `ROOT_DEPTH_SENSITIVITY_REPORT.md` |
| End-to-end Flower revision | `./run_flower_mnist_e2e.sh` | `FLOWER_MNIST_E2E_REPORT.json` |
| 4/7-validator and RTT sensitivity | `./run_network_smoke.sh` | `NETWORK_SMOKE_REPORT.md` |
| Off-chain SMT cost | `./run_smt_offchain.sh` | `SMT_OFFCHAIN_REPORT.md` |
| Full watcher duty and C1 windows | `./run_watcher_extension.sh` | `WATCHER_PIPELINE_REPORT.md`, C1 tables |
| Bounded block-capacity contention | `./run_bounded_gas_contention.sh` | `BOUNDED_GAS_CONTENTION_REPORT.md` |
| Reduced lifecycle TLA+ model | `./formal/run_tlc.sh` | `TLC_RESULTS.md` |
| Property-specific rule ablations | `./formal/run_auxiliary_checks.sh` | feature-ablation CSV/JSON |
| Retained result audit | `python3 tools/verify_reference_results.py` | `REFERENCE_CHECK_REPORT.*` |

## Success criteria

- all retained ZIP archives pass CRC checks and the reference verifier reports zero failures;
- every blockchain scenario records the expected semantic outcome, not merely a successful transaction;
- Flower reports `REVISED` and checkpoint equality;
- the root-only challenge includes on-chain proof reconstruction;
- watcher and contention reports retain all repetitions and metadata;
- TLC terminates normally for both configurations;
- the feature checker exposes the expected counterexample when each rule is removed.

## Interpretation boundaries

The comparison contracts are architectural design points, not source-level
reimplementations of named systems. The authenticated-state implementation is a
partial ablation, the RTT campaign is colocated, and bounded contention does not
establish general denial-of-service resistance. `POSIX_FADV_DONTNEED` is an
eviction advisory, not a guaranteed cold-device condition.
