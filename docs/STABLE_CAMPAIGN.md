# Stable paper campaign

This profile is a reduced, fail-fast campaign intended to provide the main paper results without rerunning the full exhaustive matrix.

## Defaults

- 4 QBFT validators;
- 10, 50, and 100 clients;
- 5 measured repetitions and 1 warm-up for the complete scenario set;
- capacity sweep: 10, 50, 100, 200, and 500 clients with batch sizes 25, 50, and 100;
- challenge-window sweep: 1, 5, and 10 blocks at 100 clients;
- flooding sweep: 1, 20, and 50 challenges with resolver parallelism 5 and 20;
- no Pumba/network emulation;
- reduced optimistic sweep and 5,000 state-machine fuzz sequences.

A targeted integration preflight executes `concurrent_moot`, `correction_laundering`, and a 50-challenge/20-way flooding case before the long campaign. It stops immediately if one of these known stress paths fails.

## Run

```bash
./run_campaign.sh stable
```

The script uses Python only inside the tools container. The host needs Docker Engine, Docker Compose, Bash, Make, and sufficient free disk space.

## Optional 7-validator sanity check

After the stable run, a small separate check can be launched without the extended sweeps:

```bash
VALIDATOR_LIST_OVERRIDE="7" \
CLIENTS_OVERRIDE="50,100" \
ROUNDS_OVERRIDE=3 \
WARMUP_OVERRIDE=1 \
SCENARIOS_OVERRIDE="logging_only,nominal,correction_laundering" \
./run_campaign.sh core
```
