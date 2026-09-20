# Experimental scenarios

| Scenario | Injected condition | Evidence adapter | Expected terminal state | Main property exercised |
|---|---|---|---|---|
| `logging_only` | No fault, no dispute state machine | None | `FINALIZED` | Blockchain logging baseline |
| `nominal` | No fault | None | `FINALIZED` | Normal-path fixed overhead |
| `bad_admission` | Receipted client rejected | Admission receipt | `FINALIZED` after correction | Sound admission revision |
| `bad_omission` | Admitted client absent from the aggregate map | Sparse-Merkle inclusion/non-inclusion | `FINALIZED` after correction | Inclusion correction |
| `bad_injection` | Rejected client absent from the admitted map but present in the aggregate map | Sparse-Merkle non-inclusion/inclusion | `FINALIZED` after correction | Injection removal and descendant supersession |
| `bad_aggregate` | Checkpoint differs from deterministic replay | Aggregate replay | `FINALIZED` after corrected republication | Aggregation correction |
| `resolver_fallback` | Faulty aggregate; coordinator does not repair | Aggregate replay | `FINALIZED` from terminal fallback | Fallback path |
| `correction_laundering` | Correct admission revision followed by a false replacement checkpoint | Admission receipt then aggregate replay | `FINALIZED` after retry exhaustion and fallback | Correction closure |
| `concurrent_moot` | Ancestor admission fault and descendant aggregate fault challenged in one epoch | Both adapters; descendant is not resolved after ancestor revision | `FINALIZED`; descendant becomes `MOOT` | Snapshot/topological resolution |
| `challenge_flooding` | Multiple false admission challenges | Admission receipt for each challenge | `FINALIZED` without a correction epoch | Adversarial cost without false revision |
| `resolver_timeout_abort` | Resolver remains silent past its deadline | Aggregate replay evidence is generated but no certificate arrives | `ABORTED` | Deadline enforcement and bounded termination |
| `artifact_unavailable_abort` | Required replay artifact unavailable | No positive certificate | `ABORTED` | Safe failure default |

The four central paper cases remain admission, inclusion, aggregation, and
correction laundering. The remaining scenarios support threat-model and
implementation claims.

## Targeted final scenarios

### `affected_decisions`

The first `k` client admission decisions are incorrect. Their revisions jointly
invalidate the aggregate and require a replacement checkpoint. Parameter:
`AFFECTED_DECISIONS`.

### `faulty_replacement_chain`

The initial aggregate and then `d` coordinator replacements are incorrect. Each
replacement is rechallenged. A correct coordinator replacement closes the round
before the retry budget; at the budget, the resolver fallback is terminal.
Parameter: `FAULTY_REPLACEMENTS` with `RETRY_BUDGET=5` in the final campaign.
