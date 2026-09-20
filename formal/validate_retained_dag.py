#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'formal'/'retained'/'dependency_dag'/'dag_exhaustive_results.csv'
rows=list(csv.DictReader(p.open()))
assert len(rows)==12
for r in rows:
    b=int(r['retry_budget']); coverage=r['coverage']=='True'
    assert r['passed']=='True'
    assert int(r['nonterminal_cycles'])==0
    if coverage: assert int(r['invalid_finalized_states'])==0
    else: assert int(r['reachable_states'])==40 and int(r['invalid_finalized_states'])==7
print(json.dumps({'validatedRows':len(rows),'note':'aggregate retained-output validation; original DAG generator was not present in the supplied source snapshot'},indent=2))
