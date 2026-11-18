#!/usr/bin/env python3
"""Derived policy sensitivity over hypothetical fault mixes using *measured* v3 rows.

This is an expectation model (a weighted mixture of empirical scenario means),
NOT a newly observed workload under stochastic faults. Do not mistake the
number of grid points for independent blockchain repetitions. No extrapolation
outside the three measured scenario classes.
"""
from __future__ import annotations
import argparse
import csv
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

WORKLOADS=("clean","bad_admission","bad_aggregate")
POLICIES=("contestfl","eager_full","abort_restart","level_cascade")


def measured_cells(path: Path):
    cells=defaultdict(list)
    with path.open(newline="",encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if int(r["client_count"]) != 100 or r.get("window_label", "sized") != "sized":
                continue
            if r["workload"] not in WORKLOADS or r["design"] not in POLICIES:
                continue
            key=(r["workload"],r["design"])
            ok = r["correct_checkpoint_finalized"].lower()=="true" and not r["error"].strip()
            if not ok:
                raise ValueError(f"not modeling expected cost after failed finalization: {key}")
            cells[key].append({"wall_ms":float(r["wall_ms"]),"gas_total":float(r["gas_total"]),
                               "verification_cpu_ms":float(r["verification_cpu_ms"])})
    if any(not cells[(s,p)] for s in WORKLOADS for p in POLICIES):
        raise ValueError("required measured policy/workload cells missing")
    return cells


def sensitivity(cells, probs=tuple(v/20 for v in range(21))):
    out=[]
    for rate in probs:
        weights={"clean":1-rate,"bad_admission":rate/2,"bad_aggregate":rate/2}
        for policy in POLICIES:
            values={metric:sum(weights[w]*st.mean(r[metric] for r in cells[(w,policy)])
                                for w in WORKLOADS) for metric in ("wall_ms","gas_total","verification_cpu_ms")}
            out.append({"invalid_fraction_assumed":rate,"admission_fraction_of_invalid_assumed":0.5,
                        "policy":policy, **{f"expected_{k}":v for k,v in values.items()},
                        "underlying_n_per_scenario":min(len(cells[(w,policy)]) for w in WORKLOADS)})
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args()
    cells=measured_cells(args.source)
    rows=sensitivity(cells)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir/'fault_rate_mixture_derived.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    by={(r['invalid_fraction_assumed'],r['policy']):r for r in rows}
    delta=[(r,by[(r,'eager_full')]['expected_wall_ms'] - by[(r,'contestfl')]['expected_wall_ms'])
           for r in sorted(set(x['invalid_fraction_assumed'] for x in rows))]
    (args.output_dir/'fault_rate_mixture_scope.json').write_text(json.dumps({
        'source':str(args.source), 'model': 'convex weighted mean of three independently measured fault scenarios',
        'fault_types': {'bad_admission':0.5,'bad_aggregate':0.5},
        'eager_minus_contestfl_wall_delta_ms_min_max':[min(x for _,x in delta),max(x for _,x in delta)],
        'crossover_eager_vs_contestfl_detected_in_measured_grid':any(a[1]*b[1]<0 for a,b in zip(delta,delta[1:])),
        'limitations':['No runtime stochastic trial with mixed fault rates','Eager and ContestFL differ in verification assurances and on-chain implementation','Verification CPU separate from EVM gas; 256-bit root-only ablation is distinct','Not a model of adversary dependence or faulty replacement cascades']
    },indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'source':str(args.source),'grid_points':len(delta),'rows':len(rows)}))

if __name__=='__main__':main()
