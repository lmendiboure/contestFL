# Release validation record

This release consolidates the available source and retained result snapshots
into one evaluator-facing repository.

## Checks completed during assembly

- shell syntax validation for every launcher;
- Python compilation and 40 host-side unit tests (31 executed successfully;
  nine dependency-gated tests skipped because Web3 packages were unavailable);
- CRC verification of every retained result ZIP;
- regeneration of the reference figures supported by the local plotting tool;
- 36 numerical and semantic reference-result assertions;
- execution of the property-specific feature-ablation checker;
- validation of the retained dependency-DAG aggregate table;
- removal checks for generated Besu state, private keys, nested repository
  copies, caches, and local `.env` files.

## Checks not executable in the assembly environment

Docker was unavailable, so the Besu/QBFT and Flower containers were not rerun.
The pinned TLA+ launcher was inspected, but its JAR could not be downloaded in
the network-isolated assembly environment. The retained experiment outputs are
included with SHA-256 checksums, and the full commands remain available for an
evaluator with Docker and network access.

The original generator source for the separate dependency-DAG aggregate table
was not present in the supplied snapshots. This is disclosed in `README.md` and
`formal/README.md`; the retained output is validated but not represented as
freshly regenerated.
