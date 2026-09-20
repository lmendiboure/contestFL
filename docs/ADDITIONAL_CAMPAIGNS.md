# Additional validation campaigns

This document describes two additional experiments used by the final paper. Both are included in `SUITE=paper` and may also be run independently.

## 1. Watcher statistics at 100 and 1,000 MiB

Run:

```bash
./run_watcher_extension.sh
```

Defaults:

- 100 clients;
- 1 MiB and 10 MiB update bodies per client (approximately 100 and 1,000 MiB
  committed per round);
- 30 retained repetitions per artifact size and cache mode;
- two warm-ups;
- page-cache-eligible and `POSIX_FADV_DONTNEED` advisory modes;
- deterministic 10,000-sample bootstrap confidence intervals for the median.

Outputs are written to `results/runs/<UTC>_watcher_extension/`:

- `watcher_pipeline_raw.csv`;
- `watcher_pipeline_summary.csv`;
- `WATCHER_PIPELINE_REPORT.md`;
- `watcher_pipeline_metadata.json`;
- optionally, regenerated C1 projection files when a
  `replay_scaling_summary.csv` is available.

Useful overrides:

```bash
WATCHER_ROUNDS=40 WATCHER_RETAIN_DATASETS=1 ./run_watcher_extension.sh
REPLAY_SUMMARY=results/runs/<run>/replay_scaling_summary.csv ./run_watcher_extension.sh
```

If the measurement phase completed but a later post-processing step failed, resume
without repeating the watcher measurements:

```bash
RESULT_DIR=results/runs/<existing-run> WATCHER_RESUME=1 \
  ./run_watcher_extension.sh
```

Resume mode requires non-empty `watcher_pipeline_raw.csv` and
`watcher_pipeline_summary.csv` in the existing result directory.

Fast launcher smoke test:

```bash
WATCHER_CLIENTS=2 WATCHER_UPDATE_BYTES=4096 WATCHER_ROUNDS=2 \
WATCHER_WARMUP=0 WATCHER_BOOTSTRAP_SAMPLES=500 \
  ./run_watcher_extension.sh
```

The `fadvise` condition remains an eviction advisory. It must not be described
as a guaranteed cold-device measurement.

## 2. Bounded block-gas contention

Run the 30 M gas operating point:

```bash
./run_bounded_gas_contention.sh
```

Run a small capacity sweep:

```bash
BLOCK_GAS_LIMITS="5000000 10000000 30000000" \
  ./run_bounded_gas_contention.sh
```

Fast Besu/QBFT smoke test:

```bash
BLOCK_GAS_LIMITS=5000000 FLOOD_COUNTS=0,2 \
CONTENTION_ROUNDS=1 CONTENTION_WARMUP=0 \
CHALLENGER_ACCOUNTS_CONTENTION=2 \
  ./run_bounded_gas_contention.sh
```

Defaults:

- 4 co-located QBFT validators;
- block gas limit 30,000,000;
- floods of 0, 10, 25, 50, and 100 unsupported aggregate challenges;
- five retained repetitions and one warm-up;
- alignment immediately after a fresh block, then 50 ms before the burst;
- 100 ms between completion of the flooding broadcast and the honest transaction;
- identical gas price for flood and honest transactions;
- genesis and Besu target gas limits set to the same configured value;
- 100 challenger accounts for the 100-challenge case.

The experiment uses two independent protocol rounds. The attack round receives
the challenge burst. A second clean round has already completed its challenge
window, so its finalization transaction is valid when it is submitted into the
same transaction pool. This avoids measuring a transaction that would revert
for protocol reasons.

Outputs are written to `results/runs/<UTC>_bounded_gas_contention/`:

- one `gas_<limit>/` directory per network configuration;
- combined `bounded_gas_contention_raw.csv`;
- combined `bounded_gas_contention_summary.csv`;
- `BOUNDED_GAS_CONTENTION_REPORT.md`;
- metadata JSON files.

The raw results additionally record the measured gas limit, block utilization
of the block containing the honest transaction, burst-broadcast duration, and
whether a new block appeared while the burst was being submitted.

This is an application-level inclusion-contention experiment. It does not
establish resistance to malicious validators, censorship, network saturation,
or monetary-bond attacks.

## Interpretation guidance

The watcher extension can replace the current small-sample p95 statement with
statistics from the new retained run and a bootstrap interval around the
median.

The contention extension should be reported separately from the existing
unbounded-gas flooding experiment. A safe formulation is:

> Under a configured block gas limit of X, a burst of Y admitted challenge
> transactions delayed an independently valid finalization by a median of Z
> blocks (p95: P), on the co-located four-validator testbed.

Do not merge this result into a general denial-of-service claim.
