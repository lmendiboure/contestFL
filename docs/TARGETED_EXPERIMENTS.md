# Final targeted experiments

The targeted extension fills only the gaps needed by the final evaluation
story. It does not repeat the broad functional campaign, the full competitor
campaign, or the 4/7-validator study.

## One-command run

```bash
cp .env.example .env
./run_targeted_extension.sh
```

The script uses a fresh four-validator QBFT network and never invokes Pumba,
`tc/netem`, or another network-emulation dependency.

## Live preflight

Before retaining measurements, the runner executes:

1. eager verification with 500 clients;
2. ContestFL nominal execution with 500 clients;
3. 50 affected admission decisions;
4. five faulty coordinator replacements followed by resolver fallback;
5. 100 simultaneous challenges with resolver parallelism 5.

The campaign stops immediately if any transaction reverts or any semantic or
blockchain invariant fails.

## Clean-path scaling

The principal design points are measured at:

```text
10, 25, 50, 75, 100, 150, 200, 300, 500 clients
```

Designs:

- Audit-only;
- Eager verification;
- ContestFL.

Default protocol: three measured rounds and one warm-up per point. Gas,
calldata, and block span are the primary metrics. The small repetition count is
intentional because those metrics are deterministic or discrete for an
identical call sequence; it is not used for latency-tail claims.

## Amount of affected client-level state

The experiment injects incorrect admission decisions for:

```text
k = 1, 2, 5, 10, 20, 50 clients
```

All corrected decisions jointly change the aggregate input and therefore
require a replacement checkpoint. This experiment measures scaling with the
amount of client-level state revised. It does not claim to emulate a deeper FL
dependency graph than ADMIT/INCLUDE/AGGREGATE.

## Repeated faulty replacements

The coordinator publishes:

```text
d = 0, 1, 2, 3, 4, 5 faulty replacements
```

after the initially faulty state. Every faulty replacement is rechallenged.
The retry budget is five. For `d < 5`, a final correct coordinator replacement
is published. At `d = 5`, the resolver installs the terminal fallback.

## Challenge flooding

The sweep uses:

```text
challenges:   1, 5, 10, 20, 50, 100
parallelism:  5, 20
```

The runner records the block containing the last `ChallengeOpened`, the first
and last resolution blocks, and the finalization block. The primary resolution
span is therefore measured from the final opened challenge to finalization,
rather than being dominated by the configured challenge-admission window.

## Replay scaling

Client counts:

```text
10, 50, 100
```

Update sizes per client:

```text
4 KiB, 64 KiB, 256 KiB, 1 MiB, 4 MiB, 10 MiB
```

Each of the 18 configurations runs ten times in a fresh child process. This
keeps process-level high-water memory counters configuration-local, although
the publication figures should focus on replay time and throughput.

## Phase decomposition

Raw transaction phases are mapped to:

- Coordination;
- Challenge;
- Resolution;
- Replacement;
- Fallback/abort;
- Finalization.

The generated summary reports per-round median gas and transaction count by
phase. Submission/coordination cost remains available as a separate category so
that the final figure can de-emphasize it without silently discarding it.

## Resumption

The default is `RESUME=1`. Complete tags are checked inside the tools container
and skipped. To force a fresh run:

```bash
RESUME=0 ./run_targeted_extension.sh
```

To continue an interrupted run:

```bash
RUN_ID=<existing_targeted_run_id> RESUME=1 ./run_targeted_extension.sh
```
