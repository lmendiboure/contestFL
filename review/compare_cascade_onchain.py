#!/usr/bin/env python3
"""Paired ContestFL vs independent off-chain level-cascade on corrected Solidity.

Runs exactly the same staged published faults for both arms, preserving the
same EVM transaction semantics. Records differences in verifier work, not
claims about a hypothetical independent Solidity contract.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
from web3 import Web3

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from bench.run_scenarios import RoundData, load_contracts, private_key
from review.causal_chain import run_case as run_contestfl
from review.causal_chain_plan import candidate, verify_plan
from review.cascade_runtime import emitted_candidate, run_cascade, ctx_for
from review.independent_level_cascade import LevelCascadeAuditor


def write_csv(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows:return
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys() for r in rows))))
        writer.writeheader();writer.writerows(rows)
    temp.replace(path)



def run_clean(w3, contracts, keys, args, rep, seed, rid, data, policy):
    """Same valid publication, no faults, one challenge window, same EVM substrate."""
    c=ctx_for(w3,contracts,keys,args,rep,rid,data)
    c.scenario=f'clean_{policy}'
    c.sender.scenario=c.scenario
    started=time.perf_counter_ns()
    audit_cpu=audit_wall=0.0
    audited_keys=0
    error=''
    correct=False
    try:
        states=[3]*args.clients
        cp=data.checkpoint(states)
        c.open_contract_round(states,cp)
        if policy=='independent_level_cascade':
            auditor=LevelCascadeAuditor(data.client_ids,data.updates,data.update_hashes,data.smt_depth)
            result=auditor.audit(states,tuple(t.root for t in c.current_trees),cp)
            if result.finding is not None: raise AssertionError('unexpected clean cascade fault')
            audit_cpu,audit_wall=result.cpu_ms,result.wall_ms
            audited_keys=result.verified_keys
        c.wait_challenge_window()
        c.finalize()
        status=c.contract.functions.getRoundStatus(rid).call()
        correct=(int(status[0])==5 and bytes(status[9])==cp and int(status[4])==0)
        if not correct:raise AssertionError('clean checkpoint not finalized')
    except Exception as exc:
        import traceback
        error=f'{type(exc).__name__}: {exc}\n{traceback.format_exc()}'
    txs=c.sender.metrics
    return {'workload':'clean','design':policy,'client_count':args.clients,'repetition':rep,
            'seed':seed,'round_id':rid,'correct_checkpoint_finalized':correct,
            'wall_ms':round((time.perf_counter_ns()-started)/1e6,3),
            'gas_total':sum(t.gas_used for t in txs),'tx_count':len(txs),
            'verification_cpu_ms':round(audit_cpu,4),'verification_wall_ms':round(audit_wall,4),
            'full_level_audit_cpu_ms':round(audit_cpu,4),
            'full_level_audit_wall_ms':round(audit_wall,4),
            'full_level_audit_count':int(policy=='independent_level_cascade'),
            'audited_keys':audited_keys,'verified_fault_count':0,
            'challenge_wait_wall_ms':round(c.challenge_wait_ms,3),
            'challenge_blocks':args.challenge_blocks,'response_blocks':args.response_blocks,
            'update_dim':args.update_dim,'error':error,
            '_tx_receipts':[{'design':policy,'repetition':rep,'seed':seed,'round_id':rid,
                'phase':t.phase,'tx_hash':t.tx_hash,'gas_used':t.gas_used,
                'block_number':t.block_number,'status':t.status} for t in txs],
            '_adapter_records':[]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clients',type=int,required=True)
    p.add_argument('--workload',choices=('clean','chain'),default='chain')
    p.add_argument('--rounds',type=int,required=True)
    p.add_argument('--warmup',type=int,default=1)
    p.add_argument('--update-dim',type=int,default=4096)
    p.add_argument('--seed',type=int,default=20261112)
    p.add_argument('--validators',type=int,default=4)
    p.add_argument('--batch-size',type=int,default=50)
    p.add_argument('--challenge-blocks',type=int,default=11)
    p.add_argument('--response-blocks',type=int,default=120)
    p.add_argument('--retry-budget',type=int,default=3)
    p.add_argument('--tag',default='liveness_cascade_final')
    p.add_argument('--rpc',default=os.getenv('RPC_URL','http://node1:8545'))
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args()
    if args.clients<2 or args.rounds<1 or args.warmup<0 or args.update_dim<1:
        p.error('invalid population/repetitions')
    if args.retry_budget!=3:p.error('exact three-fault budget required')
    w3=Web3(Web3.HTTPProvider(args.rpc,request_kwargs={'timeout':90}))
    if not w3.is_connected():raise RuntimeError('Besu unavailable')
    contracts=load_contracts(w3)[:3]
    keys={name:private_key(name) for name in json.loads((ROOT/'network/secrets/addresses.json').read_text())}
    expected_abi={x['name'] for x in contracts[0].abi if x.get('type')=='function'}
    if not {'expireSubmission','expireReplacement'}<=expected_abi:
        raise RuntimeError('corrected liveness contract not deployed')
    rows=[]; tx_rows=[]; proofs=[]
    serial=int(time.time_ns()//1000)*100
    for rep in range(-args.warmup,args.rounds):
        seed=args.seed+rep*1000003+args.clients*101
        data=RoundData.generate(args.clients,args.update_dim,seed,32)
        if args.workload=='chain':
            verify_plan(data)
            for stage in range(4):
                a,b=candidate([3]*args.clients,stage,data)
                c,d=emitted_candidate(data,stage)
                if a!=c or b!=d:raise AssertionError('different physical workload across policies')
        policies=['contestfl','independent_level_cascade']
        random.Random(seed).shuffle(policies)
        for policy in policies:
            serial+=1000
            if args.workload=='clean':
                r=run_clean(w3,contracts,keys,args,rep,seed,serial,data,policy)
            elif policy=='contestfl':
                r=run_contestfl(w3,contracts,keys,args,rep,seed,serial,policy,data)
                r['full_level_audit_cpu_ms']=0.0
                r['full_level_audit_wall_ms']=0.0
                r['full_level_audit_count']=0
                r['audited_keys']=0
            else:
                r=run_cascade(w3,contracts,keys,args,rep,seed,serial,data)
            print(json.dumps({k:r.get(k) for k in ('repetition','design','client_count',
                    'correct_checkpoint_finalized','wall_ms','gas_total','audited_keys','error')}),flush=True)
            if rep>=0:
                tx_rows.extend(r.pop('_tx_receipts'))
                proofs.extend(r.pop('_adapter_records'))
                rows.append(r)
                write_csv(args.output_dir/'cascade_compare_raw.csv',rows)
                write_csv(args.output_dir/'cascade_transactions.csv',tx_rows)
                write_csv(args.output_dir/'cascade_adapter_evidence.csv',proofs)
            if r['error'] or not r['correct_checkpoint_finalized']:
                raise RuntimeError(f'{policy} failed rep {rep}: {r["error"][:500]}')
    metadata={'workload':args.workload,'policies':policies,
             'assurance':'same Solidity contract and resolver assumptions; independent off-chain full-level re-audit',
             'not_claimed':'a separately implemented independent on-chain cascade protocol',
             'clients':args.clients,'rounds':args.rounds,'warmup':args.warmup,
             'seed':args.seed,'update_dim':args.update_dim,'challenge_blocks':args.challenge_blocks,
             'response_blocks':args.response_blocks,'chain_id':w3.eth.chain_id,
             'source_sha256':hashlib.sha256((ROOT/'contracts/ContestFLExperiment.sol').read_bytes()).hexdigest()}
    (args.output_dir/'cascade_metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print('DONE paired comparison',args.output_dir)

if __name__=='__main__':main()
