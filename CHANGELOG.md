# Changelog

## 2026-11-17 — major-revision source release

- Updated from the original GitHub snapshot to the frozen source used for the November 2026 Besu and Flower experiments.
- Added the verified causal-MOOT guard, bounded-recovery and termination/timeout paths, tests and supporting TLA+ checks present in the frozen source.
- Added paired-policy, cascade, late-challenge/flood and multi-round Flower experiments and their analyses.
- Preserved the original benchmarking, figure assets, reference archives and comparison contracts.
- Published compact, unmodified November experiment result extracts under `evidence/revision_2026_11/`.
- Consolidated root documentation and added machine-readable source/evidence provenance. Full raw Flower model data remain a separate experimental archive.

**Verification:** source-only tests and reference checks have been executed on this prepared release. A new Docker/Besu performance campaign was not run for packaging. See `ARTIFACT_RELEASE_2026_11.md`.
