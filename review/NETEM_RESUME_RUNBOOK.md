# ContestFL v4 extended: resume at Netem preflight

The interrupted campaign has **passed** all Flower policy replay stages. Its final recorded stage is `netem_preflight FAIL_2` because `tools/netem.sh` was packaged without executable permission (`0644`). The EVM policy measurements in the earlier stages are preserved.

This patch invokes `tools/netem.sh` through Bash in the Makefile and launchers, irrespective of archive extraction permissions. It adds a narrowly scoped resume, which validates the saved stage journal and refuses to overwrite completed CSVs.

From the original checkout:

```bash
cd ~/Bureau/contestFL-main
source .venv/bin/activate
git apply --check ContestFL_v4_extended_netem_resume_fix.patch
git apply ContestFL_v4_extended_netem_resume_fix.patch
python -m unittest discover -s tests -p 'test_v4_netem_resume.py' -v
./review/resume_v4_extended_netem.sh review_outputs/v4ext_full_20261111T215814_v4_extended_run
```

The previous Flower resume command will **not** accept the new failure state, and the original full campaign must **not** be started again.

The script reboots a fresh four-validator QBFT chain, runs Netem preflight, injects measured 100 ms RTT (unless overridden with `EXT_NETEM_RTT_MS`), records the probe and causal-run metrics, optionally derives the v3 fault-rate sensitivity, consolidates the report and packages the same original results directory.

The original failed `netem_preflight.log` is preserved as `netem_preflight.previous_1.log`. The earlier failed Flower replay is also preserved in the stage journal. The final manifest summarizes **latest** status for completeness, retaining all earlier attempts. The new P2P emulation is a single-host RTT sensitivity, **not** a multi-site WAN benchmark.

**If Netem fails for a different reason** (e.g. Docker NET_ADMIN capability), do not re-run this script blindly: its strict state validation will reject a different last stage or existing partial Netem data. Inspect `logs/<last_stage>.log` first. Send the updated log for a tailored recovery.
