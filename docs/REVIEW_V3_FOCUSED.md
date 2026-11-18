# ContestFL JISAS major revision — v3 focused experimental protocol

**Target:** replace or strengthen existing cost/latency and robustness results, not add several figures. This package extends the original author's `contestFL-main.zip` and the v2 review code. Original retained reference results are **not** recast as fresh v3 measurements.

## Run on Linux with Docker + Besu

From the extracted `contestFL-main/` directory:

```bash
cp .env.example .env
./review/run_focused_v3.sh check           # host-only tests, no Docker
./review/run_focused_v3.sh smoke           # minimal Besu deployment + diagnostic
BASE_RUN_ID=jisas_v3 ./review/run_focused_v3.sh focused
```

The `focused` run creates `review_outputs/jisas_v3_v3_focused/` and a corresponding ZIP of **new results** after every required stage succeeds. Run `smoke` first. Do not run multiple campaigns against the same Docker Compose project simultaneously. The launcher destroys the generated ContestFL test network/state between stages (`make network-clean`), not retained result files; never run it while another ContestFL benchmark is active. Do **not** expose Besu RPC 8545 to an untrusted network. It uses funded test accounts and insecure dev chain assumptions.

Requirements: Docker Engine + Compose v2, `make`, Bash, GNU coreutils, Python >=3.10, `unzip`. First run downloads the Besu/tools images and solc. Recommend >=16 GB RAM and >=30 GB available disk, notably for the 100 clients × 10 MiB watcher campaign. Depending on hardware and repetitions, the focused run can consume substantial time; watch logs instead of restarting on a slow stage.

### Optional knobs

```bash
BASE_RUN_ID=jisas_v3b REVIEW_REPS=25 REVIEW_SHORT_REPS=8 REVIEW_FLOOD_REPS=12 \
  ./review/run_focused_v3.sh focused
```

Defaults: `REVIEW_REPS=20` for the primary comparison, `REVIEW_SHORT_REPS=6` for deliberate single-block sensitivity, `REVIEW_FLOOD_REPS=8` per flood-count/quota combination, 4 QBFT validators, 1-second block period, 100 clients in the focused comparison (matching the watcher population), 1 MiB/int32 update per client, and three workloads: clean, wrongful admission, incorrect aggregate. `REVIEW_WORKLOADS=clean,bad_admission,bad_omission,bad_aggregate` enables inclusion omissions as an additional fault class. `REVIEW_CLIENTS=10,100` can be used for an extra exploratory scale point, but the same **100-client-sized challenge window** is then conservatively applied to both groups; do not claim this is a per-size optimized window. These are **protocol microbenchmarks with generated update vectors**, not end-to-end training.

For the upper-size sensitivity, use `REVIEW_UPDATE_DIM=2621440` for 10 MiB/client, then the window is derived from the *matching* fresh watcher observation. Other values are refused by the focused launcher so that source measurements are not mismatched with generated workload sizes. Increase the test sample only after inspecting observed variance and failures; do not selectively choose the best seed or window after looking at outcomes.

Optional Flower/MNIST integration **after** the primary benchmarks (separate new chain):

```bash
BASE_RUN_ID=jisas_v3_flower REVIEW_RUN_FLOWER=1 ./review/run_focused_v3.sh focused
```

This reruns the original Flower path for functional validation. It is **not** a four-way end-to-end throughput comparison, so do not claim the reviewer-requested real FL training throughput was experimentally established by the paired protocol CSV.

If a chain stage fails, the launcher exits nonzero and retains stage logs and partial raw CSVs. **Do not** report a partial run as completed; examine `STAGE_STATUS.tsv` and failure rows. New run IDs are required to prevent overwriting prior results.

## Three result categories

| Category | Source | Intended manuscript use | Boundary |
|---|---|---|---|
| **Correction cost** | `paired_policies/sized/paired_policies_raw.csv`, `paper_replacements/` | Substitute one existing performance table/figure with paired gas, correct-checkpoint finality latency, and success denominator | Same deterministic updates and seed per *configuration*, not simultaneous ledger replay. Policy designs, not published competitors. |
| **Realistic-window sensitivity** | `fresh_watcher/`, `window_model/`, `paired_policies/short/` | Update current text/latency comparison and show why one-block claims are fragile | Window projection combines fresh local p95 with *modeled* bandwidth and object-store RTT. Not C1 proof or actual WAN. |
| **Robustness and enforcement** | `conformance/`, `robustness/`, `trust_boundary.json` | Strengthen existing robustness result, state conformance limits | A load is called *saturated* only if measured block gas occupancy approaches the configured 5-Mgas cap. Per-identity quotas are not Sybil resistant; cleanup aborts are not timeout-induced aborts. |

`review/consolidate_focused_v3.py` generates:
- `focused_policy_summary.csv`: each design's attempts, correctness successes and failures, Wilson 95% success-rate interval, median/p95 *conditional on correct finalization*.
- `focused_paired_effects.csv`: alternative minus ContestFL for **exact seed+repetition pairs with both correct**, with bootstrap CI. Missing or failed pair counts remain visible.
- `replacement_existing_table.tex`: one compact LaTeX table suitable to *replace* an existing paper table.
- `replacement_existing_cost_latency.pdf`: one compact two-panel plot intended to **replace** an existing cost/latency figure.
- `FOCUSED_REPLACEMENT_REPORT.md` and a JSON provenance summary.

The one-block sensitivity intentionally allows *failed* runs; this is the variable being investigated, not grounds to drop a failed condition. Primary sized-window comparisons **fail the launcher** if any outcome is incorrect, to force debugging before drawing comparative claims. For both, failure counts remain in raw and summary outputs.

## Scientific checks before using results in a response to reviewers

1. Compare modified Solidity bytecode and run receipt status, not old retained gas numbers. Log Besu, Docker, solc, machine and source hashes. The v3 test suite does not self-certify an EVM behavior without a real Besu execution.
2. Inspect `STAGE_STATUS.tsv`. Count successful/failed executions for each design; never compare a fast failed run to a correctly finalized one.
3. Paired policies use fixed generated tensors/seed per condition and randomized policy execution order. The bootstrapped CI is descriptive, especially for small `smoke` and `short` samples. Benchmark the same client count, update dimensions and stated challenge windows; Eager's native pre-verification does not wait for an optimistic contest period.
4. Keep **total** EVM receipt gas distinct from **off-chain verification CPU**, and explicitly label the experimental policy designs. `level_cascade` means a downstream aggregate *re-audit* on the common substrate; it is not an arbitrary-DAG optimized cascade engine.
5. Check the `robustness/late_challenge_raw.csv` columns `saturation_observed`, `max_observed_block_gas_utilization`, honest inclusion status/deadline, and p95 latency. If none of the blocks reaches 90% gas utilization, the batch is **not an empirical beyond-capacity test**; larger or more concurrent ingress is required before making that claim.
6. `review/trust_boundary_probe.py` demonstrates a trust limitation, not a fixed vulnerability. Do not imply the contract alone authenticates evidence semantics or general dependency topology.
7. Preserve the proof obligations around Theorem 3 and abstract per-key versus prototype shared budgets. Model checking a bounded state space cannot repair a general proof. See `docs/TERMINATION_BOUND_SCOPE.md` and `docs/REVIEWER_EVIDENCE_MATRIX.md`.
8. C1 failure can allow erroneous finalization: a missed honest challenge is not equivalent to a timeout-induced abort. The v3 load study measures honest inclusion and occupancy, **not** a comprehensive causal rate of timeout aborts. If asked for the latter, either implement a separately specified resolver-service experiment or narrow the corresponding claim in the manuscript.
9. Retain the root-only storage study as a **partial ablation**, not complete root-committed recovery with authenticated receipts, witness availability and omissions handled end-to-end.
10. Reviewer R1/R4 ask for actual FL training throughput. The protocol latency is only one term; complete throughput requires a controlled Flower training campaign with all compared policies coupled to it. If omitted to limit article size, do not claim to have measured it.

## Where it changes the existing manuscript

- **Cost/latency:** replace the weaker old protocol policy comparisons with v3 paired cost, finality and explicit correctness data. Avoid claiming a universal ContestFL win.
- **Challenge windows:** substitute the old one-block headline with sized-window comparison. State the watcher/network decomposition in the caption/text.
- **Robustness:** update the existing challenge-ingress/flooding result, with honest inclusion success and observed capacity utilization; do not invent timeout aborts.
- **Formal/contract claims:** revise the proof and assumptions independently of the performance graph; the `MOOT` causal guard is a limited fixed-schema check, not arbitrary DAG refinement.

The experiment design is set *before* observing v3 results. If measured findings contradict claimed benefits, report them and narrow the claim rather than changing conditions to make ContestFL appear to win.
