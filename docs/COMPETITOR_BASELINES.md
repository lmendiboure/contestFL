# Representative competitor baselines

## Scope

The baselines are controlled implementations of representative verification
architectures under the same clients, synthetic updates, evidence adapters,
Solidity compiler, Besu/QBFT network, and transaction sender. They permit fair
within-harness cost and semantic comparisons. They are not source-compatible or
parameter-matched reproductions of particular published systems.

## Plain FL (`plain_fl`)

The coordinator computes and accepts the checkpoint locally. It has zero
on-chain gas, transactions, and block span. Faults therefore reach local
finality unless another external mechanism is assumed. This is a lower-bound
cost reference, not a ledger competitor.

## Ledger audit (`ledger_audit`)

`LoggingOnly.sol` records submissions, roots, and the checkpoint. After
finalization, the relevant adapter is run as an external audit. A mismatch is
therefore detectable, but the canonical on-chain checkpoint is not revised.
This design point represents blockchain-backed traceability without a shared
correction state machine.

## Eager verification (`eager_full`)

`EagerVerification.sol` requires a resolver certificate before finalization.
For each round, the runner executes:

1. receipt checks for every submission;
2. sparse-Merkle inclusion/non-inclusion checks for every decision;
3. deterministic aggregate replay;
4. one certificate/evidence-root commitment on chain.

A faulty candidate is overwritten by the verified state before finalization.
Resolver unavailability expires into a safe abort. This is a controlled eager
adapter baseline, not an implementation of any specific zk proof system.

## Single-shot optimistic verification (`single_shot`)

`SingleShotOptimistic.sol` provides one challenge and one coordinator-published
terminal replacement. The replacement has no fresh contestation window and the
contract has no correction lineage, retry budget, resolver fallback, or timeout
transition. It can correct isolated faults, but:

- a dependent checkpoint can remain inconsistent after an ancestor correction;
- a malicious terminal replacement can launder a new error into finality;
- an unavailable resolver leaves the round stuck.

This design point is both a representative isolated optimistic baseline and a
mechanism ablation for ContestFL.

## ContestFL

Matching ContestFL scenarios are executed by `bench/run_scenarios.py`. The
analysis maps `concurrent_moot` to the dependent-fault column and
`resolver_timeout_abort` to resolver unavailability.

## Semantic outcome taxonomy

- `FAULTY_FINALIZED`: an incorrect checkpoint reaches finality;
- `DETECTED_ONLY`: evidence identifies the fault but canonical state is not
  repaired;
- `PREVENTED`: eager verification replaces the fault before finalization;
- `CORRECTED`: an already-published state is revised into a coherent canonical
  state;
- `SAFE_ABORT`: no incorrect checkpoint finalizes and the round terminates;
- `STUCK`: no bounded terminal transition is available;
- `NOT_APPLICABLE`: the design has no corresponding resolver dependency.
