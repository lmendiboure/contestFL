# ContestFL v4-extended — Flower print fix and scientific resume

## Scope

This corrects a pure reporting error in `review/flower_policy_replay.py`:
`(row['error'] or '').splitlines()[0]` raises `IndexError` for a successful
EVM policy run with an empty error message. It does **not** change the
contract, policy semantics, Flower model, training, gas accounting or the
policy comparison implementation.

The fix enables a **resume after the first failed Flower-policy stage** without
rerunning completed causal scaling, Merkle depth, deadline/timeout or already
measured Flower training. It DOES NOT resume the same blockchain: the failed
launcher shuts down Besu on exit. The remaining policy measurements use a new
four-validator QBFT network with the same configuration. Block heights from
that fresh chain must not be compared directly to the previous chain.

## Apply to the already patched v4-extended checkout

From the ContestFL repository root, activate the existing environment:

```bash
source .venv/bin/activate
git apply --check ContestFL_v4_extended_flower_resume_fix.patch
git apply ContestFL_v4_extended_flower_resume_fix.patch
python -m unittest tests.test_v4_flower_resume -v
```

The patch only changes `review/flower_policy_replay.py` and
`review/package_results.py` and adds a separate resume launcher, tests, and
this guide; it does **not** conflict with the earlier causal-plan fix.

## Resume the failed actual run

```bash
./review/resume_v4_extended_flower.sh \
  review_outputs/v4ext_full_20261111T215814_v4_extended_run
```

This command requires the exact original directory, not the ZIP filename and
not a new `BASE_RUN_ID`. The resume launcher validates that all prior steps
completed and that the last failed stage is `flower_policies_<seed>` before it
starts Docker. If files or status rows are missing, it stops instead of
silently rerunning or overwriting original measurements.

The script then restarts Besu, reuses the measured Flower artifact directory,
completes policy comparisons for the pending seeds, performs the remaining
Netem sensitivity and v3-derived analysis, consolidates the results, and
packages the same output directory into a ZIP. Only new stages are executed.

Output:

`review_outputs/v4ext_full_20261111T215814_v4_extended_run.zip`

Logs from an earlier failed stage are moved to
`logs/flower_policies_<seed>.previous_1.log`, not deleted. Every attempt
remains in `STAGE_STATUS.tsv`; the manifest reports the last status of each
stage and counts the retained failed attempts. A `RESUME_PROVENANCE.json`
explains why a separate chain instance was used.

**Scientific limitations:** the sequential Flower round reuses one measured
training duration for both EVM policies; it is *not* multi-round concurrent
training throughput. Results from independent Besu instances may be compared
by per-run latency and gas, but not by absolute block heights.

## If the resume stops again

Inspect the latest failure log and keep the same results directory intact.
Do not launch `run_v4_extended.sh run` from the beginning without first
investigating the new error. This specialized resume script intentionally
handles only a run interrupted at the Flower policy stage, not arbitrary
partial failures later in the run.
