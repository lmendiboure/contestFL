# Metrics and output files

Each blockchain round produces one row in `raw/rounds_<tag>_v<N>.csv` with:

- campaign tag and all sweep parameters;
- end-to-end round latency and challenge-window waiting time;
- total gas, calldata, transactions, and spanned blocks;
- number of challenges, retries, and correction epochs;
- expected and actual terminal state;
- an invariant check on the finalized checkpoint or safe abort.

Every transaction receipt is retained in `raw/transactions_<tag>_v<N>.csv`
with phase, gas, calldata, block number, and submit-to-receipt latency.

Every adapter execution is retained in `raw/adapters_<tag>_v<N>.csv` with:

- evidence and certificate digests;
- adapter verdict and corrected state;
- evidence-generation and verification latency;
- proof size and artifact bytes;
- a textual verification trace.

`bench/analyze.py` produces core, capacity, window, flooding, network, adapter,
and optimistic summaries, together with PDF/PNG figures, LaTeX tables,
`REPORT.md`, and `MANIFEST.json`.

## Interpretation

Gas is tied to the exact bytecode and call mix. Latency is tied to the host,
Besu image, validator count, block period, challenge window, and network
placement. Local replay measurements are CPU baselines rather than consensus
measurements. Network emulation on one host must be reported as emulation.
