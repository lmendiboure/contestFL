# C1 monitoring cost and challenge-window projections

Measured local monitoring is combined with ideal line-rate serialization. Because streaming can overlap acquisition and verification, transfer plus local time is not a universal lower bound. The overlap projection is `max(transfer, local)` and the serial projection is `transfer + local`; they bracket ideal full overlap and no overlap for the retained implementation. Both exclude artifact publication delay, storage/object-store latency, queueing, challenge-transaction propagation/inclusion, and an engineering safety margin.

| Artifacts | Bandwidth | Local monitor | Transfer | Overlap projection | Serial projection | Blocks (overlap--serial) | p95 blocks |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100.0 MiB | 100 Mb/s | 167.0 ms | 8390.4 ms | 8390.4 ms | 8557.4 ms | 9--9 | 9--9 |
| 100.0 MiB | 1000 Mb/s | 167.0 ms | 839.0 ms | 839.0 ms | 1006.0 ms | 1--2 | 1--2 |
| 100.0 MiB | 10000 Mb/s | 167.0 ms | 83.9 ms | 167.0 ms | 250.9 ms | 1--1 | 1--1 |
| 1000.0 MiB | 100 Mb/s | 1843.9 ms | 83887.9 ms | 83887.9 ms | 85731.8 ms | 84--86 | 84--86 |
| 1000.0 MiB | 1000 Mb/s | 1843.9 ms | 8388.8 ms | 8388.8 ms | 10232.7 ms | 9--11 | 9--11 |
| 1000.0 MiB | 10000 Mb/s | 1843.9 ms | 838.9 ms | 1843.9 ms | 2682.8 ms | 2--3 | 2--3 |

## Cost interpretation

For deterministic challenge coverage, every full watcher pays the local monitoring term on every round. The fault rate multiplies only challenge-package construction and, when a separate resolver independently repeats the replay, that resolver term. The projection assumes duplicate challenges are merged so one package and one resolver invocation are charged per disputed round. Multiple watchers multiply monitoring and acquisition work unless they share infrastructure.

The one-block challenge windows used by the protocol microbenchmarks are therefore not deployment recommendations. At 1 Gb/s, the measured 100 MiB configuration projects to 1--2 one-second blocks and the 1,000 MiB configuration to 9--10 blocks before queueing or transaction inclusion. At 10 Gb/s, the 1,000 MiB configuration still projects to 2--3 blocks (3--4 using the retained p95 local time).
