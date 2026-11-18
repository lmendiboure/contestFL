# Results

This page summarizes selected results *already present* in the published repository data. It is not a new benchmark report. Consult the raw/summary files for the underlying configurations and repetitions.

## Design comparisons and scalability

The reference benchmarks examine single-shot, eager, logging-only, and ContestFL design variants. At 100 clients, the retained comparison reports a ContestFL gas premium over single-shot of approximately 27–31% across the clean and tested fault paths. In the materialized clean-state experiment, gas rises from approximately 1.31 million at 10 clients to 52.94 million at 500 clients.

For the root-only authenticated-state ablation at 500 clients, the included summary records 204,140 gas for clean publication, compared with 52,944,390 gas for the materialized design. The ablation measures implemented paths and should not be interpreted as complete semantic equivalence between designs.

## Challenge-window and network sensitivity

The retained watcher experiment reports median local inspection times of approximately 167 ms for 100 MiB and 1,844 ms for 1,000 MiB under the `fadvise` advisory condition. Controlled network-delay sweeps examine 4 and 7 validators in a colocated testbed.

## Dependent corrections

Paired causal-recovery runs record median gas savings relative to full abort/restart of **67.704% at 25 clients**, **72.963% at 100 clients**, and **74.580% at 500 clients**, for the tested three-fault dependent-correction scenarios. These comparisons concern the specific restart reference measured in that campaign.

## Flower multi-round integration

The additional Flower experiment comprises five trajectories of 20 successive rounds for each policy (200 rounds in total). The recorded mean throughput is **132.04 rounds/hour for ContestFL** and **219.86 rounds/hour for eager verification**. The round-level metrics and paired data are under `evidence/revision_2026_11/`.

## What to reproduce

The exact matching of a result to a script, configuration, and underlying data is provided in [Experiments](experiments.md). The results above must not be combined into one speedup or cost comparison across different experimental conditions. The corresponding archived measurements and hashes are described in [Data and provenance](data-and-provenance.md).
