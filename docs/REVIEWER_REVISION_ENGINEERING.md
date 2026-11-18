# ContestFL — October 2026 major revision: engineering evidence map (draft 1)

Sources: `JISAS-D-26-07235-reviews.pdf` (reviewers 1–4, dated October 13–20,
2026) and reviewer 2's separate `Reviewer_Comments_1.docx`. These files are not
redistributed in the source archive. This document describes engineering status,
**not** a completed rebuttal or new blockchain performance results.

## What this revision actually implements

1. **Contract-level causal MOOT guard** in `contracts/ContestFLExperiment.sol`:
   - Only an accepted `REVISED` challenge may moot descendants.
   - `ADMIT(client)` can moot `INCLUDE(client)` and `AGGREGATE`.
   - `INCLUDE(client)` can moot `AGGREGATE`.
   - An `AGGREGATE` challenge cannot moot anything, and a revised admission
     cannot moot an independent client's admission/inclusion.
   - A non-aggregate `REVISED` verdict must change the published client state.
   - Cross-round, cross-epoch and already-resolved targets remain prohibited.
   These restrictions do **not** independently verify a certificate's semantic
   validity, the set of dependencies committed in a root or off-chain policy.
2. **Regenerable bounded dynamic-DAG checker** in
   `formal/dynamic_dependency_check.py` for two clients, `ADMIT -> INCLUDE ->
   AGGREGATE`, and `ADMIT -> AGGREGATE`. `INCLUDE(i)` exists iff `ADMIT(i)` is
   true. Explores both activation and removal, snapshot-resolved concurrent
   challenges, bounded restarts, *shared* or *per-level* retries, certificate-
   based terminal fallback and the absence of challenge coverage (C1).
   - It asserts dependency/version binding at every exposed checkpoint,
     no wrong finalization **conditional on C1**, and a finite window count.
   - It deliberately permits invalid finalization **without C1** and reports
     examples, rather than hiding the assumption.
   - All counts are **explored state instances across multiple initializations
     and truth assignments**, not unique global TLA+ states or EVM executions.
   - The oracle is stipulated authentic, the fallback is stipulated certified;
     no arbitrary-DAG or unbounded-state claim is made.
3. **Negative on-chain test scenario** `adversarial_moot_guard` added to
   `bench/run_scenarios.py`, and to the integration preflight in
   `run_campaign.sh` (stable profile). It uses actual `eth_call` against
   deployed Solidity to demand reverts when (a) an unrelated admission would
   be mooted, (b) an UPHELD verdict tries to moot, or (c) an unchanged
   admission is claimed to be REVISED. It then resolves independent challenges
   normally and verifies the final checkpoint. It is *not* a test of all
   malicious-resolver behaviors. It cannot be counted as executed until Besu
   is available and the test actually runs.
4. **Host-side assertions** in `tests/test_dynamic_dependency.py` and
   `tests/test_reviewer_moot_guard.py`; the dynamic checker is now invoked by
   `formal/run_auxiliary_checks.sh` and `scripts/check_repository.sh`.

## Reproducibility / exact commands

```bash
# No Docker required: reduced model, unit tests, legacy artifact checks.
bash scripts/check_repository.sh
python3 formal/dynamic_dependency_check.py --output-dir results/runs/review_dynamic

# Docker/Besu required; this is the *new* negative conformance test plus a
# previously-existing positive ancestor -> aggregate MOOT scenario.
# The stable profile executes the new negative test at integration preflight.
./run_campaign.sh stable

# Or launch a minimal dedicated, isolated 4-validator campaign:
VALIDATOR_LIST_OVERRIDE='4' CLIENTS_OVERRIDE='10' \
ROUNDS_OVERRIDE=1 WARMUP_OVERRIDE=0 \
SCENARIOS_OVERRIDE='adversarial_moot_guard,concurrent_moot' \
RUN_ID=review_moot_guard ./run_campaign.sh quick
```

The revised contract must be **recompiled and redeployed**; the existing
retained blockchain receipts and gas tables relate to the old bytecode.

## Requested reviewer-to-evidence matrix

| Review comments | Current finding / existing artifact | Required action or status |
|---|---|---|
| R1.1, R4.1, R2 enforcement | Fixed schema, off-chain ordering, trusted certificate hashes | **Partial code fix** for causal MOOT; still need full adversarial tests for root forgery, snapshot order, resolver compromise, and an explicit rules-to-code matrix. A hash alone is not a verified certificate. |
| R3.W3, R4.5 | Old TLA+ model is one-checkpoint; old retained 3-key DAG checker generator missing | **New** two-client dynamic activation checker with shared/per-level retries and concurrent challenged ancestors; still need an independent TLA+/formal refinement argument and arbitrary-DAG proof. |
| R1.2, R3.W2 | Audit/eager/single-shot are architectural design points | **Open**: implement *abort-and-restart* and *level-cascade* as first-class same-workload baselines; caveat that current competitors are not published-system reproductions. |
| R1.3 | Eager vs aggregate verification claim | **Open (paper)**: state which decision classes are checked; eager aggregate checking alone cannot guarantee correct admission. |
| R1.4, R4.4 | 1-block windows in some earlier comparisons; watcher-derived C1 windows in other campaigns | **Open**: re-run Eager and ContestFL under identical watcher-calibrated multi-block windows and artifact sizes; report full round finalization latency, training throughput and verification cost including all CPU and ledger phases. |
| R1.5, R4.2 | Depth-32/256 Merkle cost study and partial root-only storage ablation | **Open**: production-strength 256-bit key collision assumptions; authenticated receipt issuance, pre-root ingress, non-inclusion proofs, witness retention, full dependent recovery; cost the *whole* lifecycle. |
| R1.6, R4.6, R2 flooding | Bounded-gas *finalization* contention under a finite burst | **Open**: sustained flooding, honest challenges near closing deadline, quotas/deduplication, include success, timeout/abort rate and p95/p99 with realistic block gas; Proposition 1 cannot be presented as enforced without governance/contract code. |
| R1.7, R2 C1/C2, R3.C1 | C1 policy-validity is conditional; C2 availability not ensured solely by on-chain root | **Open (model + deployment)**: attribution, observer/watchtower incentive/coverage, evidence/witness availability adversarial failures and fail-closed behavior; quantify missed-challenge probability without claiming deterministic coverage. |
| R1.8 | Receipt and sparse Merkle adapters plus deterministic aggregate replay exist | **Open**: clarify the requested non-plain-text adapter interpretation and implement genuinely external/verifiable source evidence if required. |
| R4.3, R2 retry budgets/termination | Paper has per-level R3; Solidity implements a single per-round retry counter; fallback is global in this specific contract | **Partial model** covers both accounting rules separately. **Open**: amend Theorem 3 / Eq. 8 to count per-key fallbacks and sequential recovery of vacant keys; clearly separate prototype and parameterized protocol. |
| R3.W1, R2 co-location | Existing controlled 0–50 ms P2P RTT on one host | **Open**: extend RTT and object-store latency sensitivity and explicitly avoid a claim of real multi-organization WAN deployment. |
| R2 scope / numerical evidence | Retained measurements, C1 estimates and reference verifier | **Paper-only plus replay**: delimit clean-path gas, root-only ablation, 500-client co-located scaling and cost vs monetary price; add release commit/config and variability statistics. |

## Theorem 3 / Equation (8): necessary repair

A bound of the form `challenge_windows <= 1 + sum(level_retry_budgets) +
first_time_dynamic_key_activations` does **not itself** bound elapsed time if
resolving different vacant keys may require different **sequential** certified
fallbacks. One must include at least:

- an upper bound on distinct keys that can ever become active (including
  reject-to-admit activations), and on how often each key can enter fallback;
- a finite deadline for each fallback, or fail-closed abort;
- a bound on the number of sequential arbitration/republication stages;
- an eventual-ordering assumption for honest transactions after stabilization.

A candidate *accounting template* (not yet a proven replacement for Eq. (8)) is:

```
T <= N_window * W_challenge
   + N_resolution * W_response
   + N_publication * W_publish
   + N_fallback * W_fallback
   + W_finalize + D_network
```

All `N_*` must be derived from the **actual** per-key transition rules, including
multiple fallbacks, and all `W_*` must be expressed consistently in either
blocks or post-stabilization time. The current Solidity prototype has one
terminal global resolver fallback; the abstract per-key theorem does not.

## Security boundary: what must not be claimed after this patch

Even with the new MOOT guard, an **authorized malicious resolver** can still
submit an arbitrary nonzero `certificateHash`. The contract does not verify
that the hash corresponds to a sound signed or ZK-verifiable certificate, and
`publishResolverFallback` still accepts nonzero replacement roots supplied by
the resolver. The coordinator also selects roots without on-chain proof of
completeness of the input set. Therefore the prototype's semantic guarantees
remain **conditional on the resolver, admission policy and off-chain evidence
layer**. Proving resistance to malicious authorized resolvers would require a
different and much larger on-chain trust/certificate design.

The new dynamic checker models honest evidence/coverage explicitly; it cannot
serve as proof of trustlessness or a claim that the Solidity bytecode refines
the full abstract model. Benchmark figures must **not** be refreshed from
previous receipts after changing the Solidity bytecode.
