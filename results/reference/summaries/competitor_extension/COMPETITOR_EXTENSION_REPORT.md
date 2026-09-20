# ContestFL competitor-baseline extension

- Measured design points: **Plain FL, Ledger audit, Eager verify, Single-shot, ContestFL**
- Measured rounds: **285**
- Semantic failures: **0**

## Interpretation

The baseline contracts implement representative design points under the same workload, evidence adapters, and QBFT deployment. They are not line-by-line reproductions of named published systems. Eager verification executes the full receipt/Merkle/replay adapter suite before every finalization. Single-shot optimistic verification permits one terminal replacement but does not reopen contestation, maintain a correction lineage, or provide resolver fallback.

Expected-cost curves are trace-driven projections from measured clean and challenged paths. They are labelled as modelled results and must not be presented as additional blockchain executions.
