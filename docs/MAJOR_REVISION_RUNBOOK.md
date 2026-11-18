# ContestFL — JISAS-D-26-07235: code + experiment runbook

This is a **research execution package**, not a claim that all reviewer concerns have been resolved. It includes the original Besu/QBFT benchmark and the November 2026 revision extensions. The supplied reviewer files are not redistributed. The source version is the archive provided by the author, not a repository commit; SHA-256 hashes in the release manifest identify the exact modified files.

## Hardware and prerequisites

- Ubuntu/Linux x86-64, Docker Engine with Compose v2, Bash, GNU Make, Python >= 3.10, `unzip`. You must be able to run `docker info` without `sudo`.
- For the **full** watcher campaign (100 clients × 10 MiB each), prefer >= 16 GiB RAM and >= 30 GiB free SSD. High disk usage and long runtimes are expected. No simulation should be silently labeled as a Besu measurement.
- Docker daemon must run. First execution needs Internet access for `hyperledger/besu:26.7.0`, Python Docker images and the Solidity compiler. The Docker build downloads `solc` 0.8.24 through `py-solc-x`.
- Docker network subnets are fixed in `.env.example`: `172.31.0.0/24` and `172.32.0.0/24`. Edit them if they conflict with VPN or LAN ranges, together with the network names. Do not expose port 8545 to untrusted machines: this is a **funded test chain** with intentionally insecure test account management.
- `make network-clean` removes the generated ContestFL network/state but **not** retained results; never run while an unrelated ContestFL campaign is active. The revision launcher tears down the dedicated Compose network after each stage and on error.

## Extract and start

```bash
unzip ContestFL_JISAS_review_ready_v2.zip
cd contestFL-main
cp .env.example .env

# Source-only checks, historical data consistency, window-model sanity.
./review/run_review_suite.sh check

# Small end-to-end Besu run: compiles/deploys contracts and runs new features.
./review/run_review_suite.sh smoke

# All original paper campaigns plus focused major-revision extensions.
./review/run_review_suite.sh full
```

Full command is deliberately substantial. To keep data separated, the runner creates `review_outputs/<UTC-ID>_<mode>/`. Each step has a log under `logs/` and a `STAGE_STATUS.tsv`. If a step fails, the runner **stops**; it does not silently skip experiments or substitute historical results. To label an execution, use:

```bash
BASE_RUN_ID=rev_jisas_2026_11 ./review/run_review_suite.sh full
```

To change run lengths:

```bash
REVIEW_ROUNDS=20 REVIEW_FLOOD_ROUNDS=20 WATCHER_ROUNDS=30 \
  BASE_RUN_ID=rev_20 ./review/run_review_suite.sh full
```

Run the two modes in separate shells, not concurrently. The full suite generates a zipped output archive after all stages pass, along with checksums and environment versions. Historical reference files are unchanged by the new code, and their gas/latency tables must **not** be attributed to the new Solidity bytecode.

## Stages and output interpretation

| Stage | Execution | Evidence | Scientific scope |
|---|---|---|---|
| Host checks | local Python/shell | source checks, reference integrity, bounded dynamic-key checker | Not new blockchain measurements |
| Watcher C1 window | measured locally + projection | `watcher_pipeline_summary.csv`, `window_sensitivity.csv`, `recommended_window.json` | Measured local p95; network transfer and object-store RTT are **modeled** |
| On-chain conformance | 4-validator Besu | `conformance/raw/rounds_review_conformance_v4.csv` and transaction receipts | Causal MOOT negative tests, exact duplicate and per-address quota tests, fault outcomes |
| Trusted resolver probe | 4-validator Besu | `trust_boundary.json` | Demonstrates that the experimental contract does **not** authenticate the semantics of a resolver certificate or state root |
| Paired protocol policies | 4-validator Besu | `paired_policies_raw.csv`, `paired_policies_effects.csv`, `PAIRED_POLICY_REPORT.md` | Real on-chain execution with **same update tensors/seed**, controlled window, successful-run medians plus failure counts; no training phase |
| Honest late challenge | 4-validator Besu, 5 Mgas/block | `late_challenge_raw.csv` and `late_challenge_summary.csv` | Multiple flood waves, late honest admission challenge, optional per-address quota 0 vs 1, measured inclusion/revert; no Sybil protection, no timeout-abort experiment |
| Original paper replay | 4/7-validator Besu + Flower + TLA+ + root ablations | Existing `results/runs/*`, `artifacts/*` | Full original breadth and caveats |
| P2P RTT sensitivity | Netem 0/150 ms, same host | Existing RTT CSV and figures | **Not** independent WAN/multi-site deployment |

**Crucial terms:**

- The `level_cascade` design in `review/paired_policies.py` is a *conservative downstream re-audit* on the common contract. It is **not** a generic optimized implementation of level-cascade or a reproduction of related work.
- The `abort_restart` design is a fresh ContestFL round after an abort, with costs of **both rounds**. Thus it is a transparent, common-substrate policy rather than an optimized minimal abort/restart contract.
- The `eager_full` design is pre-finalization exhaustive checking (ADMIT, INCLUDE, AGGREGATE); optimistic challenge windows do **not** apply to it. Its CPU verification and transaction figures are reported separately.
- `training_rounds_per_hour` in the raw *paired policy* CSV is a protocol-completion upper-bound proxy, **not** full FL training throughput. Genuine end-to-end Flower/MNIST is a separate campaign.
- The window sizing model assumes local p95 + ideal transfer at configured line speed + fixed object access RTT; it is not empirical WAN performance and **does not establish C1** under flooding, missed challenges, or malicious watchers.
- Gas in permissioned Besu is execution resource, **not a currency price**.

## Focused commands

Run a particular on-chain negative scenario on a freshly deployed 4-validator network:

```bash
make tools
make bootstrap VALIDATORS=4 BLOCK_GAS_LIMIT=30000000 TARGET_GAS_LIMIT=30000000
make up && make status VALIDATORS=4 && make deploy
make benchmark VALIDATORS=4 CLIENTS=10 ROUNDS=3 WARMUP=0 \
  CHALLENGE_BLOCKS=30 RESPONSE_BLOCKS=120 RETRY_BUDGET=2 \
  SCENARIOS=adversarial_moot_guard,review_quota_dedupe TAG=revision_checks \
  RESULT_DIR=results/runs/revision_checks
make down
```

To inspect just the model/window evidence without Docker:

```bash
python3 formal/dynamic_dependency_check.py --output-dir results/runs/dynamic
python3 review/window_sensitivity.py \
  --watcher-summary results/reference/summaries/watcher_extension/watcher_pipeline_summary.csv \
  --output-dir results/runs/window_reference
```

## Quality gates before using results in a rebuttal

1. `STAGE_STATUS.tsv` has no failed steps; check `REVIEW_RUN_MANIFEST.json` and hashes.
2. All measured rows have the expected correct terminal state; errors and run failures are **retained**, not discarded. Check the successful-pair count in `paired_policies_effects.csv`.
3. Report sample sizes, interquartile/p95 and bootstrap CI; the units and measurement boundaries must appear in every figure caption. For small samples the 95% interval is descriptive, not evidence of definitive superiority.
4. Match challenge windows to actual artifact size and transfer assumptions. *Do not* treat a 1-MiB-per-client protocol replay as measuring transfer for a 10-MiB-per-client FL job.
5. Recompute the complete gas/latency tables against the modified **bytecode**, not historical reference receipts.
6. Distinguish properties actually checked by the contract from those only guaranteed by the off-chain evidence policy, witness availability, trust in resolver, and the C1 coverage assumption.
7. Review the explicit unresolved issues in `docs/REVIEWER_EVIDENCE_MATRIX.md` and repair the paper accordingly before any response asserting full coverage.

## Limitations and honest stopping point

The added on-chain quota is optional and per address. It does not provide non-circumventable identity allocation, fair tx scheduling, challenge bonds, guaranteed witness availability, or challenge inclusion under arbitrary overload. The trust-boundary probe intentionally shows a semantically incorrect checkpoint finalized by an **authorized** malicious resolver. The Solidity contract remains a fixed-schema harness rather than a fully on-chain general-DAG certificate-verification protocol. These are material experimental/system-design boundaries, not minor wording edits.
