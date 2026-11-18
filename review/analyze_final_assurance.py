#!/usr/bin/env python3
"""Conservative, paired statistics for the final liveness + cascade study.

No imputation or silent exclusion: any failed/missing policy or duplicate seed
invalidates the measured comparison. Interval estimates are descriptive across
experiment repetitions on a shared local QBFT host, not deployment guarantees.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean, median, stdev


def read(path):
    with path.open(newline='',encoding='utf8') as f:
        rows=list(csv.DictReader(f))
    if not rows:raise ValueError(f'empty results: {path}')
    return rows


def ci95(xs):
    n=len(xs)
    mu=mean(xs)
    if n<2:return [mu,None,None]
    # Two-sided Student t critical values for small n (n-1 degrees of freedom).
    t={1:12.706,2:4.303,3:3.182,4:2.776,5:2.571,6:2.447,
       7:2.365,8:2.306,9:2.262,10:2.228,11:2.201,12:2.179,
       13:2.160,14:2.145,15:2.131,16:2.120,17:2.110,18:2.101,19:2.093}
    tc=t.get(n-1,1.96)
    half=tc*stdev(xs)/math.sqrt(n)
    return [mu,mu-half,mu+half]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--result-dir',type=Path,required=True)
    a=p.parse_args()
    out=a.result_dir
    all_summaries=[]
    for path in sorted(out.glob('cascade/*/cascade_compare_raw.csv')):
        data=read(path)
        groups={}
        for r in data:
            key=(r['client_count'],r['seed'],r['repetition'])
            if r['design'] in groups.setdefault(key,{}):
                raise ValueError(f'duplicate policy {key} {r["design"]}')
            groups[key][r['design']]=r
        expected={'contestfl','independent_level_cascade'}
        if any(set(g)!=expected for g in groups.values()):
            raise ValueError(f'incomplete paired rows in {path}')
        if any(r['correct_checkpoint_finalized'].lower()!='true' or r['error']
               for g in groups.values() for r in g.values()):
            raise ValueError(f'failed or incorrect round in {path}; see raw CSV')
        keys=sorted(groups)
        for gname,extract in [
            ('gas_delta_cascade_minus_contestfl',lambda g:float(g['independent_level_cascade']['gas_total'])-float(g['contestfl']['gas_total'])),
            ('wall_ms_delta_cascade_minus_contestfl',lambda g:float(g['independent_level_cascade']['wall_ms'])-float(g['contestfl']['wall_ms'])),
            ('verifier_cpu_ms_delta_cascade_minus_contestfl',lambda g:float(g['independent_level_cascade']['verification_cpu_ms'])-float(g['contestfl']['verification_cpu_ms'])),
            ('additional_full_level_audit_cpu_ms',lambda g:float(g['independent_level_cascade']['full_level_audit_cpu_ms'])),
            ('full_level_audited_keys',lambda g:float(g['independent_level_cascade']['audited_keys'])),
        ]:
            xs=[extract(groups[k]) for k in keys]
            mu,lo,hi=ci95(xs)
            all_summaries.append({'group':str(path.parent.name),'metric':gname,
                      'n_pairs':len(xs),'mean':mu,'median':median(xs),
                      'ci95_lower':lo,'ci95_upper':hi,'unit':'gas' if 'gas' in gname else 'count' if 'keys' in gname else 'ms'})
    if not all_summaries:
        raise ValueError('no paired cascade data found')
    probes=list(out.glob('liveness/liveness_probe.json'))
    if len(probes)!=1:raise ValueError('missing liveness probe')
    liv=json.loads(probes[0].read_text())
    if liv.get('status')!='PASS':raise ValueError('liveness probe did not pass')
    if not all(v.get('status')=='PASS' for v in liv['liveness_cases'].values()):
        raise ValueError('some liveness scenario is not PASS')
    (out/'analysis').mkdir(exist_ok=True)
    with (out/'analysis/paired_summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(all_summaries[0]));w.writeheader();w.writerows(all_summaries)
    lines=['# Final verification: liveness + independently implemented full-level audit',
           '', 'All pairs finalized the same correct checkpoint; incomplete/failed pairs invalidate this report.',
           '', '## Liveness on corrected Solidity', '',
           'Five on-chain test cases passed, including permissionless timeout exits in SUBMIT and RESOLVING, on-time fallback and pending challenges.',
           '', 'Old/new bytecode, same network and action sequences:', '']
    for name,r in liv['paired_gas'].items():
        lines.append(f'- {name}: old {r["legacy_gas"]:,} gas; corrected {r["liveness_gas"]:,} gas; '+
                     f'delta {r["delta_gas"]:+,} gas ({r["delta_pct"]:+.2f}%).')
    lines += ['','## Independent full-level audit vs ContestFL','',
              'The cascade auditor is an **independent off-chain** state validator. Both arms deliberately share the same Solidity ledger, challenge window and resolver trust. This is NOT an independent on-chain protocol and cannot establish dominance over one.',
              '', 'Both arms receive identical published three-fault streams; levels are rechecked after publication, without look-ahead. Consequently, ledger paths may have equal gas; extra full-level audits should be measured separately.', '']
    groups=sorted({r['group'] for r in all_summaries})
    for group in groups:
        lines += [f'### {group}', '']
        for r in all_summaries:
            if r['group']==group:
                ci=f'[{r["ci95_lower"]:.3f}, {r["ci95_upper"]:.3f}]' if r['ci95_lower'] is not None else 'not available'
                lines.append(f'- {r["metric"]}: mean {r["mean"]:.4f}; median {r["median"]:.4f}; n={r["n_pairs"]}; descriptive 95% CI {ci}.')
        lines.append('')
    lines += ['## Limits','',
              '- The comparison does not reproduce an independently developed ledger or a separate full-DAG implementation.',
              '- The three faults are intentionally staged; results do not estimate natural fault prevalence.',
              '- Off-chain verification work depends on the benchmark admissibility policy and update sizes.',
              '- CI measures repeatability of this fixed-host experiment, not independent operational deployments.',
              '- The bytecode corrected for liveness is not byte-for-byte the historical v3/v4 contract; report gas deltas explicitly.',
              '- A final claim of full abstract-model-to-EVM refinement still requires an independent formal argument.', '']
    (out/'analysis/FINAL_AUDIT.md').write_text('\n'.join(lines)+'\n')
    print('Final analysis OK; groups:',len(groups),'paired contrasts:',len(all_summaries))

if __name__=='__main__':main()
