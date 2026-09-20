# Authenticated-state, Flower, and network experiments

The authenticated-state, Flower, and controlled-delay experiments are independent so that each can be executed and audited separately.

## 1. Root-only authenticated-state ablation

Run:

```bash
./run_root_only_ablation.sh
```

The campaign compares the existing materialized contract with `RootOnlyContestFL.sol` at 10, 100, and 500 clients, on:

- a fault-free round;
- one incorrect client admission followed by a sparse-Merkle proof, root replacement, renewed challenge window, and finalization;
- one incorrect aggregate checkpoint revised while preserving the committed decision and aggregate-input roots.

The materialized implementation stores each submission hash and client decision on chain. The root-only implementation stores only the submission, decision, and aggregate-input roots. A client leaf and its authentication path are revealed only when challenged.

Default retained runs: five per design, workload, and client count, after one warm-up. The output includes:

```text
ROOT_ONLY_ABLATION_REPORT.md
root_only_ablation_summary.csv
root_only_ablation_comparison.csv
raw/rounds_root_materialized_v4.csv
raw/root_only_rounds_root_only_v4.csv
```

Interpretation boundary: this is a storage-representation ablation. The root-only contract covers clean rounds, challenged client decisions, and challenged aggregate checkpoints, but it does not duplicate every fault path of the full materialized prototype.

## 2. Flower/MNIST end-to-end integration

Run:

```bash
./run_flower_mnist_e2e.sh
```

The script builds a dedicated CPU-only image, downloads MNIST once, and executes one Flower round with two clients. Each client:

1. trains a 784-32-10 PyTorch MLP on a disjoint MNIST partition;
2. exports the model delta in deterministic `state_dict` order;
3. quantizes it to little-endian int32 using a recorded fixed-point scale;
4. writes a self-describing `.cflupd` artifact and SHA-256 commitment.

The integration then:

1. deterministically replays the integer updates;
2. compares the replay to Flower's equal-weight aggregate within the quantization error;
3. deliberately publishes a mismatching aggregate checkpoint;
4. opens an aggregate challenge backed by the deterministic replay record;
5. obtains `REVISED`, publishes the corrected checkpoint, and reopens scrutiny;
6. finalizes only the corrected checkpoint after the renewed window closes.

Outputs:

```text
flower/FLOWER_MNIST_E2E_REPORT.md
flower/FLOWER_MNIST_E2E_REPORT.json
flower/client_*.cflupd
flower/client_*.json
flower/flower_aggregate.npz
```

This is an applicability demonstration, not an accuracy, convergence, or throughput benchmark.

## 3. Controlled P2P RTT smoke experiment

Run:

```bash
./run_network_smoke.sh
```

The campaign uses the existing two-network layout:

- the control network carries JSON-RPC and benchmark traffic without emulated delay;
- the P2P network carries Besu/QBFT traffic and receives `tc netem` delay.

The helper no longer passes locale-sensitive decimal strings to `tc`. A requested integer RTT is converted to an integer one-way delay in microseconds. For 50 ms RTT, every validator receives 25,000 us of egress delay. The qdisc cleanup is idempotent.

Default retained runs:

- four validators: nominal and correction laundering at 0 and 50 ms RTT;
- seven validators: nominal at 0 and 50 ms RTT;
- five runs plus one warm-up per configuration.

Outputs:

```text
NETWORK_SMOKE_REPORT.md
network_probe.csv
network_smoke_summary.csv
network_smoke_delta.csv
raw/rounds_rtt*.csv
```

Interpretation boundary: all validators remain on one physical host. This experiment measures controlled P2P-delay sensitivity, not geographically distributed QBFT performance.

## Additional micro-measurements and formal artifact

```bash
./run_smt_offchain.sh             # build/update/prove/verify cost at 10--500 clients
./run_root_depth_sensitivity.sh   # challenged-path gas at depths 32/64/128/256
./formal/run_tlc.sh               # finite exhaustive state-space exploration
```

The depth sweep is recommended whenever challenged-path gas is used as a central production argument. It may be omitted only if every result is explicitly scoped to the evaluated depth.

## Run all three realism extensions

```bash
./run_realism_extensions.sh
```

The experiments use fresh ledger networks and independent result directories. To shorten the first validation run:

```bash
ROOT_ONLY_ROUNDS=2 \
NETWORK_ROUNDS=2 \
FLOWER_SAMPLES_PER_CLIENT=256 \
./run_realism_extensions.sh
```
