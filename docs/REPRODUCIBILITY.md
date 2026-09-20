# Reproducibility notes

The campaign records profile, contract deployment metadata, Besu client version,
chain identifier, validator count, batch size, challenge and response windows,
retry budget, update dimension, false-challenge parameters, and emulated RTT.

For a paper run, report:

- host CPU, RAM, OS, kernel, Docker and Compose versions;
- immutable Besu and tools-image digests;
- Solidity compiler, optimizer, and EVM target;
- block period and QBFT timeout;
- validator count and whether validators are co-located;
- challenge-window length in blocks;
- decision batch size and update dimensions/sizes;
- warm-up and measured repetitions;
- whether latency was native, emulated, or physical multi-host.

The `paper` profile uses 10 repetitions to keep the full set of sweeps practical.
The `exhaustive` profile uses 30 measured repetitions and is preferred for final
p95 values. A targeted rerun may also set `SWEEP_ROUNDS=30` while disabling
campaigns that are not used in the final figures.
