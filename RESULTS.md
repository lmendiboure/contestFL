# Retained reference results

The machine-readable source of truth is `results/reference/summaries/`; raw
transaction- and repetition-level files are retained in the corresponding ZIP
archives. Run `python3 tools/verify_reference_results.py` before using the
numbers below.

## Main comparison and scaling

The retained competitor campaign shows the semantic distinction between the
single-shot and canonical-recovery paths: single-shot finalizes faulty state for
dependent faults and correction laundering, while ContestFL corrects both. At
100 clients, the ContestFL premium over single-shot is approximately 27--31%
across the clean and fault paths. The materialized clean path scales from about
1.31 M gas at 10 clients to 52.94 M at 500 clients.

## Authenticated state

At 500 clients, clean publication falls from 52,944,390 to 204,140 gas and one
wrongful-admission path from 53,288,842 to 561,493 gas. These are 259x and 95x
reductions on the implemented paths. Full semantic parity for omission,
concurrency, flooding, retry exhaustion, and fallback is not claimed.

## Watcher and challenge-window duty

For the retained `fadvise` advisory condition, full local inspection has a
median of 166.99 ms for approximately 100 MiB and 1,843.91 ms for approximately
1,000 MiB. The latter median has a retained bootstrap interval of approximately
[1,835.28, 1,858.94] ms. The archive includes all 30 repetitions, phase
breakdowns, and ideal-line-rate overlap/serial projections.

## Bounded contention

With 100 unsupported challenges, the adversarial burst spans a median 5, 3, and
1 blocks at 5, 10, and 30 million gas per block. The independent valid
finalization is included one block after submission at all three operating
points. This is an application-level result on a colocated QBFT testbed, not a
censorship or malicious-proposer guarantee.

## Flower, SMT, and depth sensitivity

The Flower/PyTorch run revises a deliberately false aggregate and finalizes the
deterministic replayed checkpoint in nine transactions and ten blocks for
790,759 gas. Off-chain SMT operations succeed in every retained run; at 500
clients, build, update, and proof generation medians are about 12 ms, while
verification is about 0.028 ms. Increasing configured depth from 32 to 256
increases challenged-path gas from approximately 271 k to 617 k; depth 32 is an
experimental point, not a production recommendation.

## Formal validation

The supplied TLA+ model checks the reduced lifecycle abstraction. Retained
aggregate results for the separate three-key dependency-DAG model report no
invalid finalization under coverage and no non-terminal cycle for retry budgets
0--5. The original generator for that retained table was not present in the
source snapshot used to assemble this release, so the archive is integrity-
checked but not presented as regenerated source.
