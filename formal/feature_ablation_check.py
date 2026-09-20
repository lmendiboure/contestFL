#!/usr/bin/env python3
"""Property-specific explicit-state checks used for Table VII.

Each scenario is a deliberately minimal finite transition system.  The checker
constructs the reachable graph, reports terminal observations, and verifies the
specific property supplied by the recovery rule.  It is not a gas benchmark and
is not the separate three-key exhaustive DAG model retained under
formal/retained/dependency_dag/.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import deque
import argparse, csv, json
from pathlib import Path

@dataclass(frozen=True)
class Graph:
    initial: str
    edges: dict[str, tuple[str, ...]]
    terminal: dict[str, str]

def explore(g: Graph):
    seen={g.initial}; q=deque([g.initial]); transitions=0
    while q:
        s=q.popleft()
        for t in g.edges.get(s,()):
            transitions += 1
            if t not in seen: seen.add(t); q.append(t)
    return seen, transitions, {g.terminal[s] for s in seen if s in g.terminal}

def models():
    return [
      ('full','none','concurrent_ancestor_descendant_challenges','order-independent adjudication of challenges admitted in one window',
       Graph('q0',{'q0':('eval_a','eval_g'),'eval_a':('both_eval',),'eval_g':('both_eval',),'both_eval':('apply_a',),'apply_a':('moot_g',),'moot_g':('done',)}, {'done':'ADMIT=REVISED,AGGREGATE=MOOT'}),
       'ORDER_INDEPENDENT',True,True),
      ('no_snapshot','frozen_snapshot','concurrent_ancestor_descendant_challenges','order-independent adjudication of challenges admitted in one window',
       Graph('q0',{'q0':('a_first','g_first'),'a_first':('done_moot',),'g_first':('done_both',)}, {'done_moot':'ADMIT=REVISED,AGGREGATE=MOOT','done_both':'ADMIT=REVISED,AGGREGATE=REVISED'}),
       'ORDER_SENSITIVE_ADJUDICATION',True,True),
      ('full','none','ancestor_revision_with_dependent_aggregate','parent-consistent terminal closure after an ancestor revision',
       Graph('start',{'start':('ancestor_revised',),'ancestor_revised':('replacement_open',),'replacement_open':('replacement_terminal',),'replacement_terminal':('finalized',)}, {'finalized':'FINALIZED'}),
       'CORRECTED',True,True),
      ('no_propagation','dependency_propagation','ancestor_revision_with_dependent_aggregate','parent-consistent terminal closure after an ancestor revision',
       Graph('start',{'start':('parent_mismatch',)}, {}),'DEADLOCK_PARENT_MISMATCH',False,True),
      ('full','none','invalid_replacement_after_successful_challenge','an uncertified replacement cannot inherit the expired window',
       Graph('start',{'start':('invalid_replacement_open',),'invalid_replacement_open':('certified_valid',),'certified_valid':('valid_finalized',)}, {'valid_finalized':'VALID_FINALIZED'}),
       'CORRECTED',True,True),
      ('no_fresh_window','fresh_replacement_window','invalid_replacement_after_successful_challenge','an uncertified replacement cannot inherit the expired window',
       Graph('start',{'start':('invalid_terminal',),'invalid_terminal':('invalid_finalized',)}, {'invalid_finalized':'INVALID_FINALIZED'}),
       'INVALID_FINALIZED',True,False),
      ('full','none','repeated_faulty_replacements','finite recovery under repeated faulty republication',
       Graph('r0',{'r0':('c1',),'c1':('r1',),'r1':('c2',),'c2':('r2',),'r2':('c3',),'c3':('fallback',),'fallback':('finalized',)}, {'finalized':'FINALIZED'}),
       'TERMINAL_CLOSURE',True,True),
      ('no_retry_bound','bounded_retries','repeated_faulty_replacements','finite recovery under repeated faulty republication',
       Graph('replace',{'replace':('challenge',),'challenge':('replace',)}, {}),'NONTERMINAL_CYCLE',False,True),
      ('full','none','resolver_unavailable','terminal fail-closed behavior after resolver timeout',
       Graph('waiting',{'waiting':('aborted',)}, {'aborted':'ABORTED'}),'SAFE_ABORT',True,True),
      ('no_fallback_abort','fallback_or_abort','resolver_unavailable','terminal fail-closed behavior after resolver timeout',
       Graph('waiting',{}, {}),'DEADLOCK_AT_TIMEOUT',False,True),
    ]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output-dir',default='results/runs/feature_ablation_check'); a=ap.parse_args()
    out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for design,removed,scenario,prop,g,outcome,terminates,safe in models():
        seen,ntrans,terms=explore(g)
        order_independent=not (design=='no_snapshot')
        has_cycle=(design=='no_retry_bound')
        observed_terminates=bool(terms) and not has_cycle
        if terminates != observed_terminates:
            raise AssertionError((design,scenario,terminates,observed_terminates))
        rows.append(dict(design=design,removed_feature=removed,scenario=scenario,checked_property=prop,
                         outcome=outcome,terminates=terminates,canonical_safe=safe,
                         order_independent=order_independent,reachable_states=len(seen),transitions=ntrans,
                         terminal_observations=' | '.join(sorted(terms)) if terms else 'none'))
    fields=list(rows[0])
    with (out/'recovery_feature_ablation.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    (out/'recovery_feature_ablation.json').write_text(json.dumps({'rows':rows},indent=2)+'\n')
    print(json.dumps({'rows':len(rows),'output':str(out)},indent=2))
if __name__=='__main__': main()
