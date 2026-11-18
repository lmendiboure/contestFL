"""Validate an interrupted v4 extended run before an immutable Netem resume.

The only supported transition is FAIL_netem_preflight -> PASS_netem_preflight.
All prior raw measurements are preserved; there is no global replay.
"""
from __future__ import annotations
import csv
from pathlib import Path


def validate(out: Path, flower_reps: int = 3) -> dict:
    out = Path(out)
    if not out.name.endswith('_v4_extended_run'):
        raise ValueError('expected original *_v4_extended_run directory')
    if flower_reps < 1:
        raise ValueError('flower_reps must be positive')
    if (out / 'REVIEW_RUN_MANIFEST.json').exists():
        raise ValueError('final manifest already exists; refusing to alter a packaged run')
    status = out / 'STAGE_STATUS.tsv'
    if not status.is_file():
        raise ValueError(f'missing stage status: {status}')
    with status.open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    if not rows or rows[-1]['stage'] != 'netem_preflight' or not rows[-1]['status'].startswith('FAIL_'):
        raise ValueError('latest attempt must be FAIL_netem_preflight')
    latest = {}
    for row in rows:
        latest[row['stage']] = row['status']
    failures = {name: val for name, val in latest.items() if val != 'PASS'}
    if failures != {'netem_preflight': latest['netem_preflight']}:
        raise ValueError(f'unresolved stages before Netem: {failures}')
    causal = [k for k in latest if k.startswith('causal_')]
    if not causal:
        raise ValueError('no completed causal scaling stage')
    for stage in causal:
        csv_path = out / 'scale' / stage.removeprefix('causal_') / 'causal_chain_raw.csv'
        if not csv_path.is_file() or csv_path.stat().st_size == 0:
            raise ValueError(f'missing measured causal CSV: {csv_path}')
    for seed in (20261111 + 101 * k for k in range(flower_reps)):
        key = f'flower_policies_{seed}'
        if latest.get(key) != 'PASS':
            raise ValueError(f'not a completed policy stage: {key}')
        directory = out / 'flower' / f'seed_{seed}'
        for filename in ('FLOWER_ARTIFACT_REPORT.json', 'paired_flower_policies.csv'):
            path = directory / filename
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f'missing Flower measurement: {path}')
    late = out / 'timeouts' / 'late_challenge_raw.csv'
    if not late.is_file() or late.stat().st_size == 0:
        raise ValueError(f'missing timeout measurements: {late}')
    for future in (out / 'netem/network_probe.csv', out / 'netem/causal_chain/causal_chain_raw.csv'):
        if future.exists():
            raise ValueError(f'partial Netem measurements exist; manual audit required: {future}')
    return {'passed_stages': sum(v == 'PASS' for v in latest.values()),
            'retained_failed_attempts': sum(r['status'].startswith('FAIL_') for r in rows),
            'flower_repetitions': flower_reps}


def main() -> None:
    import argparse
    import json
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run_dir', type=Path)
    p.add_argument('--flower-reps', type=int, default=3)
    args = p.parse_args()
    print(json.dumps(validate(args.run_dir, args.flower_reps), indent=2))


if __name__ == '__main__':
    main()
