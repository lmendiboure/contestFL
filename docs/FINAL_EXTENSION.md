# Publication-oriented final extension

Run:

```bash
cp .env.example .env
./run_final_extension.sh
```

The command performs four targeted components:

1. **4-validator statistical confirmation**
   - logging-only and nominal: 10, 50, and 100 clients, 30 runs by default;
   - bad aggregate, bad omission, fallback, and correction laundering:
     100 clients, 20 runs by default.
2. **7-validator sensitivity**
   - logging-only and nominal at 50 and 100 clients;
   - bad aggregate and correction laundering at 100 clients;
   - 10 measured runs by default.
3. **memory-bounded replay scaling**
   - 10, 50, and 100 clients;
   - 4 KiB, 256 KiB, 1 MiB, and 10 MiB per update.
4. **controlled P2P network sensitivity**
   - 4 validators at 0, 10, 25, and 50 ms RTT;
   - 7 validators at 0 and 25 ms RTT;
   - nominal and correction laundering at 100 clients;
   - 5 measured runs plus one warm-up.

The network component uses `tc/netem` on a dedicated P2P interface and leaves
JSON-RPC on an undelayed control network. Pumba is not used.

## Fail-fast checks

Before long measurements, the script verifies:

- Docker and Compose availability;
- disk capacity;
- unit tests and Python compilation;
- Besu integration for nominal and correction laundering;
- NET_ADMIN support;
- effective RTT increase and qdisc cleanup.

## Resume

```bash
RUN_ID=<previous_run_id> RESUME=1 ./run_final_extension.sh
```

Each tag has an independent CSV. Complete tags are skipped, while incomplete or
failed tags are rerun.
