#!/usr/bin/env python3
"""Source-level comparison of historical vs corrected Solidity timeout paths.

This is a limited source audit, NOT a Solidity model checker nor EVM proof.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/'contracts/ContestFLExperiment.sol'
LEGACY=ROOT/'review/fixtures/ContestFLExperiment_v4_pre_liveness.sol'


def function_source(source: str, name: str) -> str:
    import re
    m=re.search(r'\bfunction\s+'+re.escape(name)+r'\s*\(',source)
    if not m: raise ValueError('function not found: '+name)
    a=source.find('{',m.end())
    if a<0: raise ValueError('missing body')
    depth=0
    for i in range(a,len(source)):
        if source[i]=='{': depth+=1
        elif source[i]=='}':
            depth-=1
            if depth==0: return source[m.start():i+1]
    raise ValueError('unclosed function: '+name)


def inspect_contract(source: str) -> dict:
    names=['openRound','publishInitialState','openChallenge','resolveChallenge',
           'expireChallenge','publishCoordinatorReplacement',
           'publishResolverFallback','finalize','abortRound']
    bodies={x:function_source(source,x) for x in names}
    assert 'r.phase = Phase.RESOLVING' in bodies['resolveChallenge']
    assert 'r.needsReplacement = true' in bodies['resolveChallenge']
    assert 'onlyCoordinator' in bodies['publishCoordinatorReplacement'].split('{')[0]
    assert 'onlyResolver' in bodies['publishResolverFallback'].split('{')[0]
    assert 'onlyResolver' in bodies['abortRound'].split('{')[0]
    assert 'ChallengeOutcome.OPEN' in bodies['expireChallenge']
    assert 'Phase.RESOLVING' not in bodies['finalize']
    # The original contract cannot progress when the resolver/coordinator are
    # silent. The corrected contract adds explicitly permissionless aborts.
    if ('function expireSubmission(' in source and 'function expireReplacement(' in source):
        submit=function_source(source,'expireSubmission')
        replace=function_source(source,'expireReplacement')
        publish=function_source(source,'publishCoordinatorReplacement')
        fallback=function_source(source,'publishResolverFallback')
        initial=function_source(source,'publishInitialState')
        if (all(x in body for x,body in [
             ('r.phase = Phase.ABORTED',submit),
             ('r.phase = Phase.ABORTED',replace),
             ('ReplacementDeadlineExpired',publish),
             ('ReplacementDeadlineExpired',fallback),
             ('SubmissionDeadlineExpired',initial)])
             and 'external only' not in submit.split('{')[0]
             and 'external only' not in replace.split('{')[0]):
            return {
              'source':str(CONTRACT.relative_to(ROOT)),
              'status':'STATIC_TIMEOUT_EXIT_PATHS_PRESENT_NOT_EVM_VERIFIED',
              'checks':['permissionless submit expiry','permissionless replacement expiry',
                        'late publication rejected','original role guards unchanged'],
              'qualification':'Source checks only; EVM tests, network progress and bounded inclusion still required.'}
    return {
        'source': str(CONTRACT.relative_to(ROOT)),
        'status':'COUNTEREXAMPLE_TO_UNCONDITIONAL_ONCHAIN_LIVENESS',
        'trace':[
            'openRound; submit all; publishDecisions; publishInitialState -> CHALLENGE',
            'openChallenge(AGGREGATE) -> OPEN, openChallenges=1',
            'resolver resolves with REVISED -> RESOLVING, openChallenges=0, needsReplacement=true',
            'coordinator stops; resolver stops (the permissionless honest actor remains active)',
            'finalize rejects (RESOLVING); expireChallenge rejects (already REVISED)',
            'publishCoordinatorReplacement requires coordinator; publishResolverFallback and abortRound require resolver',
            'No permissionless expiry for RESOLVING -> terminal transition is not forced',
        ],
        'secondary_gap': 'SUBMIT phase has no submission deadline callable by an unrelated actor',
        'important_qualification': 'Abstract theorem assumes honest actionable timeout callers. This execution violates that premise; it does not disprove the conditional abstract theorem.',
        'safety_warning': 'Do not change the evaluated Solidity contract and reuse historical gas numbers as if it were unchanged.'
    }


def main():
    result={'historical':inspect_contract(LEGACY.read_text()),
            'corrected':inspect_contract(CONTRACT.read_text())}
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
