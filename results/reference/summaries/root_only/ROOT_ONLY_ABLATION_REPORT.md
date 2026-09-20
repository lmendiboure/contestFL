# Root-only authenticated-state ablation

- Materialized rounds: **30**
- Root-only rounds: **30**
- Failed semantic/invariant checks: **0**

The materialized design stores one submission and one decision state per client. The root-only design stores authenticated roots and reveals a sparse-Merkle path only for the challenged client. Both use the same client populations, update dimensions, QBFT network, challenge policy, and resolver trust boundary.

## Comparison

| workload      |   clients |   materialized_gas_median |   root_only_gas_median |   root_only_reduction_gas_median_pct |   materialized_calldata_median |   root_only_calldata_median |   root_only_reduction_calldata_median_pct |   materialized_tx_median |   root_only_tx_median |   root_only_reduction_tx_median_pct |   materialized_blocks_median |   root_only_blocks_median |   root_only_reduction_blocks_median_pct |
|:--------------|----------:|--------------------------:|-----------------------:|-------------------------------------:|-------------------------------:|----------------------------:|------------------------------------------:|-------------------------:|----------------------:|------------------------------------:|-----------------------------:|--------------------------:|----------------------------------------:|
| bad_admission |        10 |                1652725.00 |              561481.00 |                                66.03 |                        2724.00 |                     1812.00 |                                     33.48 |                    17.00 |                  5.00 |                               70.59 |                        11.00 |                      8.00 |                                   27.27 |
| bad_admission |       100 |               11116062.00 |              561493.00 |                                94.95 |                       17648.00 |                     1812.00 |                                     89.73 |                   108.00 |                  5.00 |                               95.37 |                        13.00 |                      8.00 |                                   38.46 |
| bad_admission |       500 |               53288842.00 |              561493.00 |                                98.95 |                       84560.00 |                     1812.00 |                                     97.86 |                   516.00 |                  5.00 |                               99.03 |                        29.00 |                      8.00 |                                   72.41 |
| clean         |        10 |                1308333.00 |              204116.00 |                                84.40 |                        2168.00 |                      364.00 |                                     83.21 |                    14.00 |                  3.00 |                               78.57 |                         8.00 |                      6.00 |                                   25.00 |
| clean         |       100 |               10771694.00 |              204128.00 |                                98.10 |                       17092.00 |                      364.00 |                                     97.87 |                   105.00 |                  3.00 |                               97.14 |                        10.00 |                      6.00 |                                   40.00 |
| clean         |       500 |               52944390.00 |              204140.00 |                                99.61 |                       84004.00 |                      364.00 |                                     99.57 |                   513.00 |                  3.00 |                               99.42 |                        26.00 |                      6.00 |                                   76.92 |

## Interpretation boundary

The root-only contract is an ablation of storage representation, not a replacement implementation of every ContestFL decision kind. The dispute run exercises a client-decision revision and root replacement; aggregate-specific disputes remain evaluated by the materialized prototype.
