#!/usr/bin/env python3
from __future__ import annotations
import csv, json, math, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=ROOT/'results'/'reference'/'summaries'
A=ROOT/'results'/'reference'/'archives'
checks=[]
def add(name,obs,exp,tol=0):
    ok=abs(float(obs)-float(exp))<=tol if isinstance(exp,(int,float)) else obs==exp
    checks.append({'name':name,'observed':obs,'expected':exp,'passed':bool(ok)})
def rows(path): return list(csv.DictReader(path.open()))
# Integrity/readability of every retained archive.
for p in sorted(A.glob('*.zip')):
    with zipfile.ZipFile(p) as z: bad=z.testzip()
    checks.append({'name':f'archive readable: {p.name}','observed':bad,'expected':None,'passed':bad is None})
# Root-only values.
r=rows(S/'root_only_ablation'/'root_only_ablation_summary.csv')
def pick(rs,**kw):
    for x in rs:
        if all(str(x[k])==str(v) for k,v in kw.items()): return x
    raise KeyError(kw)
add('root-only clean gas at 500',pick(r,design='root_only',workload='clean',clients='500')['gas_median'],204140,0.1)
add('materialized clean gas at 500',pick(r,design='materialized',workload='clean',clients='500')['gas_median'],52944390,0.1)
add('root-only admission dispute gas at 500',pick(r,design='root_only',workload='bad_admission',clients='500')['gas_median'],561493,0.1)
# Flower.
f=json.loads((S/'flower_mnist'/'FLOWER_MNIST_E2E_REPORT.json').read_text())
add('Flower total gas',f['chain']['gasTotal'],790759)
add('Flower transaction count',f['chain']['txCount'],9)
add('Flower checkpoint equality',f['chain']['checkpointMatches'],True)
# Watcher latest retained run.
w=rows(S/'watcher_extension'/'watcher_pipeline_summary.csv')
add('watcher 100 MiB inspection median',pick(w,clients='100',cache_mode='fadvise',update_body_bytes='1048576')['verification_ms_median'],166.9856605,1e-6)
add('watcher 1000 MiB inspection median',pick(w,clients='100',cache_mode='fadvise',update_body_bytes='10485760')['verification_ms_median'],1843.9146875,1e-6)
# Bounded contention.
b=rows(S/'bounded_gas_contention'/'bounded_gas_contention_summary.csv')
for gas,span in [('5000000',5),('10000000',3),('30000000',1)]:
    x=pick(b,block_gas_limit=gas,flood_count='100')
    add(f'contention flood span {gas}',x['flood_block_span_median'],span,0.01)
    add(f'honest offset {gas}',x['honest_block_offset_median'],1,0.01)
# Root depth.
d=rows(S/'root_depth_sensitivity'/'root_depth_sensitivity_summary.csv')
add('depth-32 challenge gas',pick(d,smt_depth='32')['challenge_gas'],270941,0.1)
add('depth-256 challenge gas',pick(d,smt_depth='256')['challenge_gas'],616871,0.1)
# Retained DAG table.
dag=rows(S/'dependency_dag_retained'/'dag_exhaustive_results.csv')
add('DAG rows',len(dag),12)
add('DAG invalid finalized under coverage',sum(int(x['invalid_finalized_states']) for x in dag if x['coverage']=='True'),0)
add('DAG nonterminal cycles under coverage',sum(int(x['nonterminal_cycles']) for x in dag if x['coverage']=='True'),0)
# Paper feature ablation outcomes.
fa=rows(S/'feature_ablation_retained'/'paper_recovery_feature_ablation.csv')
expected={'frozen_snapshot':'ORDER_SENSITIVE_ADJUDICATION','dependency_propagation':'DEADLOCK_PARENT_MISMATCH','fresh_replacement_window':'INVALID_FINALIZED','bounded_retries':'NONTERMINAL_CYCLE','fallback_or_abort':'DEADLOCK_AT_TIMEOUT'}
for feature,outcome in expected.items():
    vals={x['outcome'] for x in fa if x['removed_feature']==feature}
    checks.append({'name':f'ablation {feature}','observed':sorted(vals),'expected':[outcome],'passed':vals=={outcome}})
failed=[c for c in checks if not c['passed']]
out={'summary':{'checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed)},'checks':checks}
outdir=ROOT/'results'/'reference'; (outdir/'REFERENCE_CHECK_REPORT.json').write_text(json.dumps(out,indent=2)+'\n')
lines=['# Reference result check','',f"- Checks: **{len(checks)}**",f"- Passed: **{len(checks)-len(failed)}**",f"- Failed: **{len(failed)}**",'', '| Status | Check | Observed | Expected |','|---|---|---:|---:|']
for c in checks: lines.append(f"| {'PASS' if c['passed'] else 'FAIL'} | {c['name']} | `{c['observed']}` | `{c['expected']}` |")
(outdir/'REFERENCE_CHECK_REPORT.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(out['summary'],indent=2))
raise SystemExit(1 if failed else 0)
