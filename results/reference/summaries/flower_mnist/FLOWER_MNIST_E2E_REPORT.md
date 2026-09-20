# Flower/MNIST end-to-end ContestFL integration

- Flower clients: **2**
- MNIST samples per client: **512**
- Fixed-point values per update: **25450**
- Clean replay verdict: **UPHELD**
- Disputed aggregate verdict: **REVISED**
- Maximum reconstruction error: **4.970e-07**
- Faulty checkpoint differs from replay: **True**
- Finalized checkpoint matches corrected replay: **True**
- Ledger gas: **790759** over **9** transactions

This run demonstrates the interface Flower training -> deterministic fixed-point artifact -> authenticated commitment -> faulty aggregate publication -> REVISED replay verdict -> corrected replacement -> ContestFL finalization. It is an applicability check, not a model-accuracy or throughput benchmark.
