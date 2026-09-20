# ContestFL dependency-DAG exhaustive check

The checker enumerates all eight initial validity assignments and every valid/invalid provisional replacement for a fixed ADMIT–INCLUDE–AGGREGATE DAG.
It checks parent-version closure, transitive invalidation, renewed windows, bounded retries, certified fallback/safe abort, and absence of non-terminal cycles.

| Retry budget | Coverage | Reachable states | Transitions | Finalized | Aborted | Invalid finalized | Non-terminal cycles |
|---:|:---:|---:|---:|---:|---:|---:|---:|
| 0 | no | 40 | 32 | 8 | 0 | 7 | 0 |
| 0 | yes | 28 | 31 | 4 | 5 | 0 | 0 |
| 1 | no | 40 | 32 | 8 | 0 | 7 | 0 |
| 1 | yes | 144 | 154 | 27 | 15 | 0 | 0 |
| 2 | no | 40 | 32 | 8 | 0 | 7 | 0 |
| 2 | yes | 514 | 540 | 113 | 33 | 0 | 0 |
| 3 | no | 40 | 32 | 8 | 0 | 7 | 0 |
| 3 | yes | 1308 | 1358 | 311 | 59 | 0 | 0 |
| 4 | no | 40 | 32 | 8 | 0 | 7 | 0 |
| 4 | yes | 2694 | 2776 | 669 | 93 | 0 | 0 |
| 5 | no | 40 | 32 | 8 | 0 | 7 | 0 |
| 5 | yes | 4840 | 4962 | 1235 | 135 | 0 | 0 |

Coverage is intentionally separated from structural safety. Without coverage, invalid provisional decisions may close their windows and finalize; with coverage, no invalid finalized state is reachable.
This is a bounded executable model, not a parameterized proof and not a substitute for the appendix proofs.
