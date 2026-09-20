# Evidence adapters

The scenario runner does not directly choose `REVISED` or `UPHELD`. It first
constructs evidence, executes the registered adapter, records its result, and
passes the adapter certificate digest to the contract.

## Admission receipt adapter

Inputs:

- round and client identifier;
- committed update hash;
- submission transaction hash;
- initial-state publication block;
- observed decision state;
- public policy state.

Checks:

1. the receipt exists and succeeded;
2. the receipt precedes initial-state publication;
3. the on-chain submission mapping contains the same update hash;
4. the observed decision matches the public policy.

The benchmark exports receipt lookup and verification time. The adapter is used
by `bad_admission`, the ancestor challenge in `correction_laundering`, and the
false challenges in `challenge_flooding`.

## Sparse-Merkle inclusion adapter

The implementation uses sparse Merkle maps indexed by `bytes32` client IDs. The
adapter generates and verifies two proofs:

- membership or non-membership in the admitted map;
- membership or non-membership in the aggregate-input map.

An admitted-but-absent client proves omission. A client absent from the admitted
map but present in the aggregate map proves injection. Proof size and both
generation and verification time are recorded.

## Deterministic aggregate replay adapter

Updates are signed 32-bit integer vectors. Replay accumulates selected updates
in signed 64-bit canonical arithmetic and hashes the result with the selected
count and a domain separator. The adapter compares that digest with the claimed
checkpoint.

The benchmark records:

- number of selected clients;
- total artifact bytes read;
- evidence-header generation time;
- deterministic replay and comparison time.

## Certificate binding

`resolveChallenge` requires a non-zero certificate digest. The digest binds the
adapter, evidence hash, verdict, corrected state where relevant, and replayed
checkpoint for aggregation disputes. The experimental contract stores the
digest in the challenge record and emits it in `ChallengeResolved`.

## Public sparse-Merkle verification

For the two inclusion scenarios, both admitted-set and aggregate-set proofs are
submitted to `EvidenceVerifier.verifySparseProofOrRevert`. These transactions
exercise the same SHA-256 leaf, empty-leaf, and internal-node domain separation
as the Python sparse map. Their receipts appear under phase `verify_evidence`,
which isolates public verification gas from challenge admission and resolution.
