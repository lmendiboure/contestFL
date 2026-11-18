#!/usr/bin/env python3
"""Single Besu probe for INCLUDE removal when admission changes 3 -> 1.

A concrete compressed-state transition, not a refinement proof for arbitrary DAGs.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path
from web3 import Web3

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from bench.run_scenarios import RoundData, load_contracts, private_key
from review.causal_chain import context


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--rpc',default=os.environ.get('RPC_URL','http://node1:8545'))
    p.add_argument('--challenge-blocks',type=int,default=11)
    a=p.parse_args()
    w3=Web3(Web3.HTTPProvider(a.rpc,request_kwargs={'timeout':90}))
    if not w3.is_connected():
        raise RuntimeError('Besu RPC unavailable')
    contracts=load_contracts(w3)[:3]
    addresses=json.loads((ROOT/'network/secrets/addresses.json').read_text())
    keys={k:private_key(k) for k in addresses}
    data=RoundData.generate(10,1024,2026111101,32)
    round_id=int(time.time_ns()//1000)*100
    a.validators=4; a.clients=10; a.batch_size=10; a.response_blocks=120
    a.retry_budget=2; a.tag='deactivation_probe_v4'
    c=context(w3,contracts,keys,a,round_id,data,0,'deactivation_probe')
    before=[3]*10
    c.open_contract_round(before)
    evidence=c.admission_evidence(0,observed_state=3,policy_state=1)
    if not evidence.valid_evidence or evidence.verdict!='REVISED' or evidence.corrected_state!=1:
        raise AssertionError('deactivation proof invalid')
    ch=c.open_challenge('ADMIT',data.client_ids[0],1,'v4_admit_to_reject',evidence_hash=evidence.evidence_hash)
    c.record_adapter(ch,evidence)
    c.resolve(ch,'REVISED',1,certificate_hash=evidence.certificate_hash)
    after=[1]+[3]*9
    c.publish_replacement(after)
    c.wait_challenge_window()
    c.finalize()
    status=c.contract.functions.getRoundStatus(round_id).call()
    result={'scenario':'admit_to_reject_3_to_1',
            'round_id':round_id,'final_phase':int(status[0]),
            'final_epoch':int(status[1]),
            'final_checkpoint_matches':bytes(status[9])==data.checkpoint(after),
            'decision_state':int(c.contract.functions.decisionState(round_id,data.client_ids[0]).call()),
            'decision_version':int(c.contract.functions.decisionVersion(round_id,data.client_ids[0]).call()),
            'open_challenges':int(status[4]),
            'note':'Checks compressed-state deactivation only; no generic dependency-key deletion guaranteed'}
    result['passed']=(result['final_phase']==5 and result['final_epoch']==1
                      and result['final_checkpoint_matches'] and result['decision_state']==1
                      and result['decision_version']==2 and result['open_challenges']==0)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if not result['passed']:
        raise AssertionError('deactivation on-chain invariants failed')

if __name__=='__main__':
    main()
