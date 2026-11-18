# Architecture

ContestFL separates **off-chain evidence verification and model computation** from **on-chain versioning and checkpoint finalization**. This division allows a decision to be challenged and revised without treating an incorrect intermediate checkpoint as an immutable result.

## Main components

| Component | Role | Source |
|---|---|---|
| Experimental smart contract | Stores round/decision state, contestation and resolution transitions, and final checkpoint commitments | `contracts/ContestFLExperiment.sol` |
| Comparison contracts | Controlled design points for logging-only, eager verification, single-shot optimism, and root-only authenticated state | `contracts/` |
| Evidence adapters | Validate the selected off-chain evidence and supply the corresponding decision/certificate material to the experiment | `bench/adapters.py` |
| Besu/QBFT harness | Starts the isolated blockchain, deploys contracts, and runs workloads | `Makefile`, `tools/`, `bench/` |
| Causal and adversarial experiments | Analyze dependent corrections, deadlines, cascade baselines, and challenge floods | `review/` |
| Flower integration | Produces and consumes training checkpoints across successive rounds | `ml/`, `review/multiround_flower.py` |
| Formal checks | TLA+ model checking and bounded property-specific analyses | `formal/` |

## Decision dependencies and recovery

The evaluated model distinguishes admission, inclusion, and aggregation decisions. A correction can affect dependent decisions; the evaluation therefore considers both isolated challenges and chains of successive corrections. The exact scope of the model, the contract's fixed decision schema, and the constraints of each experiment are documented with the relevant sources in `formal/README.md` and [Experiments](experiments.md).

The blockchain stores commitments and lifecycle transitions. It does not execute arbitrary off-chain evidence verification or complete the neural-network training workload. This distinction is important for interpreting both the performance measurements and the properties established by the formal model.

## Implementation notes

- Solidity sources are in `contracts/`; the currently evaluated contract is `ContestFLExperiment.sol`.
- Docker and chain parameters live in `.env.example` and `Makefile`.
- Reference results in `results/reference/` and the paired/multi-round evidence in `evidence/revision_2026_11/` belong to separate measurement groups. See [Data and provenance](data-and-provenance.md).
