#!/usr/bin/env python3
"""Besu run of an independent level-cascade *audit policy* on a common ledger.

The audit algorithm is in independent_level_cascade.py, not causal_chain.py.
Same deliberately staged fault stream, same challenge windows, EVM substrate,
resolver certificates and on-chain transitions as ContestFL. This is an
independent off-chain verifier, NOT a separate end-to-end on-chain protocol.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Any

from web3 import Web3
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from bench.run_scenarios import Context, RoundData, load_contracts, private_key
from review.independent_level_cascade import LevelCascadeAuditor

BAD_CP_DOMAIN=b'ContestFL:chain:wrong-aggregate:v4'
WORKLOAD='reject_admit_include_aggregate_chain'


def emitted_candidate(data:RoundData,stage:int)->tuple[list[int],bytes]:
    if stage not in (0,1,2,3): raise ValueError(stage)
    states=[3]*len(data.client_ids)
    states[0]=[1,2,3,3][stage]
    cp=data.checkpoint(states)
    if stage==2: cp=hashlib.sha256(cp+BAD_CP_DOMAIN).digest()
    return states,cp


def ctx_for(w3,contracts,keys,args,rep,round_id,data)->Context:
    return Context(w3=w3, contract=contracts[0],logging_contract=contracts[1],
        evidence_contract=contracts[2],validators=args.validators,clients=args.clients,
        repetition=rep,scenario='independent_level_cascade',round_id=round_id,
        data=data,batch_size=args.batch_size,challenge_blocks=args.challenge_blocks,
        response_blocks=args.response_blocks,retry_budget=3,flood_count=0,
        flood_parallelism=1,flood_challenge_blocks=args.challenge_blocks,
        affected_decisions=1,faulty_replacements=0,campaign_tag=args.tag,
        network_rtt_ms=0,keys=keys)


def run_cascade(w3,contracts,keys,args,rep,seed,round_id,data)->dict[str,Any]:
    ctx=ctx_for(w3,contracts,keys,args,rep,round_id,data)
    auditor=LevelCascadeAuditor(data.client_ids,data.updates,data.update_hashes,data.smt_depth)
    started=time.perf_counter_ns()
    proof_cpu=proof_wall=audit_cpu=audit_wall=0.0
    audits=0
    inspected_keys=0
    errors=''
    finalized=False
    detected=[]
    try:
        for stage in range(4):
            states,checkpoint=emitted_candidate(data,stage)
            if stage==0:ctx.open_contract_round(states,checkpoint)
            else:ctx.publish_replacement(states,checkpoint)
            # Audit what Besu actually published, not the local runner's
            # expected roots; otherwise the baseline would be self-fulfilling.
            publication_tx=ctx.sender.metrics[-1]
            publication_receipt=w3.eth.get_transaction_receipt(publication_tx.tx_hash)
            published=ctx.contract.events.StatePublished().process_receipt(publication_receipt)
            if len(published)!=1 or int(published[0]['args']['roundId'])!=round_id:
                raise AssertionError('missing/ambiguous on-chain StatePublished event')
            event=published[0]['args']
            root_triplet=tuple(bytes(event[field]) for field in
                               ('submissionRoot','admittedRoot','aggregateInputRoot'))
            published_checkpoint=bytes(event['checkpointHash'])
            if published_checkpoint!=checkpoint:
                raise AssertionError('on-chain published checkpoint differs from candidate')
            audit=auditor.audit(states,root_triplet,published_checkpoint)
            audits+=1
            inspected_keys+=audit.verified_keys
            audit_cpu+=audit.cpu_ms
            audit_wall+=audit.wall_ms
            # A decision is based only on the candidate just published.
            if stage==3:
                if audit.finding is not None:
                    raise AssertionError('final published candidate failed independent audit')
                break
            finding=audit.finding
            expected_kind=('ADMIT','INCLUDE','AGGREGATE')[stage]
            if finding is None or finding.kind!=expected_kind:
                raise AssertionError(f'level auditor did not find fault at stage {stage}: {finding}')
            detected.append(finding.kind)
            if stage==0:
                ev=ctx.admission_evidence(0,observed_state=1,policy_state=2)
            elif stage==1:
                ev=ctx.inclusion_evidence(0,observed_state=2)
            else:
                ev=ctx.aggregate_evidence(states,checkpoint)
            if not ev.valid_evidence or ev.verdict!='REVISED' or ev.corrected_state!=finding.corrected_state:
                raise AssertionError('independent full-level finding diverged from evidence adapter')
            proof_cpu+=ev.evidence_generation_cpu_ms+ev.verification_cpu_ms
            proof_wall+=ev.evidence_generation_ms+ev.verification_ms
            ch=ctx.open_challenge(finding.kind,finding.client_id,finding.corrected_state,
                                  f'level_cascade_staged_{stage}',evidence_hash=ev.evidence_hash)
            ctx.record_adapter(ch,ev)
            ctx.resolve(ch,'REVISED',finding.corrected_state,certificate_hash=ev.certificate_hash)
            if stage<2:
                if int(ctx.contract.functions.decisionState(round_id,finding.client_id).call())!=finding.corrected_state:
                    raise AssertionError('on-chain decision state != independent finding')
        ctx.wait_challenge_window()
        ctx.finalize()
        status=ctx.contract.functions.getRoundStatus(round_id).call()
        final_correct=data.checkpoint([3]*args.clients)
        final_state=int(ctx.contract.functions.decisionState(round_id,data.client_ids[0]).call())
        final_ver=int(ctx.contract.functions.decisionVersion(round_id,data.client_ids[0]).call())
        finalized=(int(status[0])==5 and int(status[1])==3 and int(status[4])==0
                   and bytes(status[9])==final_correct and final_state==3 and final_ver==3
                   and detected==['ADMIT','INCLUDE','AGGREGATE'])
        if not finalized:raise AssertionError('cascade terminal invariant failed')
    except Exception as exc:
        errors=f'{type(exc).__name__}: {exc}\n{traceback.format_exc()}'
    elapsed=(time.perf_counter_ns()-started)/1e6
    metrics=ctx.sender.metrics
    return {
        'workload':WORKLOAD,'design':'independent_level_cascade',
        'client_count':args.clients,'repetition':rep,'seed':seed,'round_id':round_id,
        'correct_checkpoint_finalized':finalized,'wall_ms':round(elapsed,3),
        'gas_total':sum(m.gas_used for m in metrics),'tx_count':len(metrics),
        'verification_cpu_ms':round(proof_cpu+audit_cpu,4),
        'verification_wall_ms':round(proof_wall+audit_wall,4),
        'full_level_audit_cpu_ms':round(audit_cpu,4),
        'full_level_audit_wall_ms':round(audit_wall,4),
        'full_level_audit_count':audits,'audited_keys':inspected_keys,
        'challenge_wait_wall_ms':round(ctx.challenge_wait_ms,3),
        'verified_fault_count':len(detected),'rounds_created':1,
        'final_phase':int(ctx.contract.functions.getRoundStatus(round_id).call()[0]) if not errors else -1,
        'challenge_blocks':args.challenge_blocks,'response_blocks':args.response_blocks,
        'retry_budget':3,'update_dim':args.update_dim,'error':errors,
        '_tx_receipts':[{'design':'independent_level_cascade','repetition':rep,'seed':seed,
                         'round_id':round_id,'phase':t.phase,'tx_hash':t.tx_hash,
                         'gas_used':t.gas_used,'block_number':t.block_number,'status':t.status}
                        for t in metrics],
        '_adapter_records':[asdict(a) for a in ctx.adapter_metrics]
    }
