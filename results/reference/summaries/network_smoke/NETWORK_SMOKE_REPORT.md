# Controlled P2P RTT smoke experiment

- Measured rounds: **30**
- Failed invariants: **0**
- Emulation scope: validator P2P interfaces only; JSON-RPC remains on the control network.

## Summary

|   validators |   network_rtt_ms |   clients | scenario              |   runs |   success_rate |   latency_ms_median |   latency_ms_q1 |   latency_ms_q3 |   blocks_median |   gas_median |   tx_median |
|-------------:|-----------------:|----------:|:----------------------|-------:|---------------:|--------------------:|----------------:|----------------:|----------------:|-------------:|------------:|
|            4 |                0 |       100 | correction_laundering |      5 |           1.00 |            12957.38 |        12921.96 |        12971.06 |           13.00 |  11436522.00 |      111.00 |
|            4 |                0 |       100 | nominal               |      5 |           1.00 |            10012.17 |         9977.22 |        10046.82 |           10.00 |  10771682.00 |      105.00 |
|            4 |               50 |       100 | correction_laundering |      5 |           1.00 |            13026.07 |        12977.15 |        13927.97 |           13.00 |  11436558.00 |      111.00 |
|            4 |               50 |       100 | nominal               |      5 |           1.00 |            10017.96 |        10001.60 |        10035.58 |           10.00 |  10771694.00 |      105.00 |
|            7 |                0 |       100 | nominal               |      5 |           1.00 |            10993.33 |        10985.43 |        11001.50 |           11.00 |  10771634.00 |      105.00 |
|            7 |               50 |       100 | nominal               |      5 |           1.00 |             9976.05 |         9958.58 |        10034.90 |           10.00 |  10771658.00 |      105.00 |

## Relative to zero-delay runs

|   validators |   network_rtt_ms |   clients | scenario              |   runs |   success_rate |   latency_ms_median |   latency_ms_q1 |   latency_ms_q3 |   blocks_median |   gas_median |   tx_median |   baseline_latency_ms |   baseline_blocks |   baseline_gas |   latency_delta_ms |   latency_delta_pct |   block_delta |   gas_delta |
|-------------:|-----------------:|----------:|:----------------------|-------:|---------------:|--------------------:|----------------:|----------------:|----------------:|-------------:|------------:|----------------------:|------------------:|---------------:|-------------------:|--------------------:|--------------:|------------:|
|            4 |               50 |       100 | correction_laundering |      5 |           1.00 |            13026.07 |        12977.15 |        13927.97 |           13.00 |  11436558.00 |      111.00 |              12957.38 |             13.00 |    11436522.00 |              68.69 |                0.53 |          0.00 |       36.00 |
|            4 |               50 |       100 | nominal               |      5 |           1.00 |            10017.96 |        10001.60 |        10035.58 |           10.00 |  10771694.00 |      105.00 |              10012.17 |             10.00 |    10771682.00 |               5.78 |                0.06 |          0.00 |       12.00 |
|            7 |               50 |       100 | nominal               |      5 |           1.00 |             9976.05 |         9958.58 |        10034.90 |           10.00 |  10771658.00 |      105.00 |              10993.33 |             11.00 |    10771634.00 |           -1017.28 |               -9.25 |         -1.00 |       24.00 |

## RTT calibration

| timestamp_utc        |   validators |   requested_rtt_ms |   observed_rtt_ms |   packets | node1_p2p_ip   | node2_p2p_ip   |
|:---------------------|-------------:|-------------------:|------------------:|----------:|:---------------|:---------------|
| 2026-08-05T22:48:41Z |            4 |                  0 |             0.081 |         5 | 172.31.0.11    | 172.31.0.12    |
| 2026-08-05T22:51:39Z |            4 |                 50 |            50.197 |         5 | 172.31.0.11    | 172.31.0.12    |
| 2026-08-05T22:55:11Z |            7 |                  0 |             0.103 |         5 | 172.31.0.11    | 172.31.0.12    |
| 2026-08-05T22:56:48Z |            7 |                 50 |            50.189 |         5 | 172.31.0.11    | 172.31.0.12    |

## Interpretation boundary

The validators remain co-located on one physical host. tc/netem adds controlled symmetric egress delay to the dedicated P2P network; the experiment is a delay-sensitivity check, not a geographically distributed QBFT benchmark.
