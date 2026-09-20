# Sparse-Merkle depth sensitivity

- Failed semantic checks: **0**
- Workload: one challenged client decision at 500 clients.

|   smt_depth |   runs |   success_rate |   proof_bytes |   total_gas |   total_calldata |   total_latency_ms |   challenge_gas |   challenge_calldata |
|------------:|-------:|---------------:|--------------:|------------:|-----------------:|-------------------:|----------------:|---------------------:|
|       32.00 |   3.00 |           1.00 |       1026.00 |   563776.00 |          1812.00 |            7977.16 |       270941.00 |              1252.00 |
|       64.00 |   3.00 |           1.00 |       2050.00 |   612870.00 |          2836.00 |            7983.37 |       320071.00 |              2276.00 |
|      128.00 |   3.00 |           1.00 |       4098.00 |   711369.00 |          4884.00 |            8023.80 |       418558.00 |              4324.00 |
|      256.00 |   3.00 |           1.00 |       8194.00 |   909682.00 |          8980.00 |            8008.34 |       616871.00 |              8420.00 |

The proof path grows linearly with the configured depth. Clean-path root publication is depth-independent, whereas challenged-path calldata and verification gas are not. Depth 32 is therefore reported as an evaluated benchmark point, not as a universal production setting.
