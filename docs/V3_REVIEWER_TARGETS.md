# JISAS-D-26-07235 — concise v3 evidence plan

The article should remain roughly the same length. A test included in the artifact **does not automatically justify another paper figure**. The primary pipeline aims to replace/strengthen existing results, not expand the claims.

| Exact major concern | v3 empirical evidence / code | Manuscript strategy | Status before author's Docker run |
|---|---|---|---|
| R1.2, R3.W2: Abort/restart, cascade and fair Eager comparisons | `review/paired_policies.py` compares all policies on identical generated vectors/seeds, with correct on-chain checkpoint assertion; includes clean/bad-admission/bad-aggregate, optional omission | Replace current policy-cost comparison; qualify baselines as experimental policy designs | Implemented, **not executed on Besu** |
| R1.4, R4.4: one-block optimistic windows and full end-to-end finality | Local watcher measurements feed a **modeled** window, applied to actual Besu protocol benchmarks; parallel diagnostic at one block | Replace old single-block caption/text; clearly distinguish protocol finalization from training throughput | Implemented, **not a real four-way Flower throughput study** |
| R1.6, R4.6: late honest challenges, flooding, quotas | `review/late_challenge_flood.py`, with honest success/receipt latency and actual block occupancy under 5 Mgas; identical challenges under quotas 0 and 1 | Strengthen existing robustness figure, no new figure needed | Implemented, **true sustained above-capacity load must be verified from occupancy, not inferred from injected counts** |
| R1.1, R4.1: on-chain rule enforcement and malicious runner | `adversarial_moot_guard`, `review_quota_dedupe`, `concurrent_moot`, `trust_boundary_probe` | Compact rule→check mapping plus explicit trusted resolver boundary | Limited schema checks only; no general conformance proof |
| R3.W3, R4.5: reject/admit activation, shared budgets, ancestor–descendant concurrency | `formal/dynamic_dependency_check.py` with bounded exhaustive exploration; Solidity negative scenarios | Report reduced-model scope and actual on-chain checks, no new main figure | Bounded model, not arbitrary-DAG verified Solidity |
| R1.5, R2, R4.2: full authenticated state, receipt availability, Merkle and cost scope | Retained root-only ablation and depth study | **Narrow** claim to measured partial paths unless a complete receipt/witness system is implemented | **Unresolved full semantic equivalence** |
| R1.7, R2: assumption C1, monitor attribution and C2 | Watcher p95 and explicit network/object-store projection; honest challenge admission under load | State conditional coverage, false-positive and witness availability assumptions clearly | **Does not prove coverage or source attribution** |
| R4.3: shared vs per-level fallback and termination theorem | Bounded checker and `docs/TERMINATION_BOUND_SCOPE.md` | Repair proof or reduce theorem to the implemented shared-budget rules | **Requires theoretical revision** |
| R3.W1 and R2: independent multi-organization/WAN | Retained controlled netem experiments | Identify same-host RTT sensitivity, not an independent multi-site federation | Not a real WAN test |
| R1.8: non-text adapter | Existing Flower/MNIST binary fixed-point artifacts | Describe exactly the existing Flower integration | Does not establish general adapter ecosystem |

## What the v3 pipeline deliberately does not claim

- An unconditional speedup over Eager, proof of policy-valid finality without C1, or a universal full-Merkle implementation.
- Full end-to-end FL training throughput; `protocol_completions_per_hour_proxy` is only a protocol performance indicator.
- Quantified rate of timeout-induced aborts caused by attack load. The current evaluator observes **honest inclusion** under attack; the script's cleanup abort is not counted as a protocol timeout.
- Guaranteed p95 coverage from the watcher/network model, or saturation without observed near-capacity blocks.
- Cryptographic validation of semantics of a resolver-issued certificate by the fixed-schema on-chain contract.

## Suggested edits to current paper, keeping its length

1. Replace the weaker cost/latency comparison by one paired, correctness-conditioned v3 figure/table. State failure fractions, sample sizes, and that an eager verifier need not wait for optimistic windows.
2. Reinterpret one-block optimistic windows and present the sized-window outcome, based on *fresh* watcher plus a stated transfer model.
3. Rework the existing robustness text/figure to report honest challenge inclusion and observed gas occupancy. If no saturation is observed, describe as finite-wave load, not starvation resistance.
4. Move full negative-test enumeration to artifact; give only the rule-level assurance boundary in text.
5. Fix the proof and semantic trust claims rather than trying to fill those gaps with extraneous plots.
