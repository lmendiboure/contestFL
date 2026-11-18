#!/usr/bin/env python3
"""Besu regression for the fixed-schema ContestFLExperiment liveness extension.

Compares gas of nominal and one-correction paths against the exact pre-liveness
source on the same Besu chain, and tests permissionless fail-closed exits.
Do NOT run concurrently with other campaigns: the launcher owns the network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from eth_account import Account
from solcx import compile_standard
from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.deploy import private_key, send  # noqa: E402

PHASE_FINALIZED, PHASE_ABORTED, PHASE_RESOLVING = 5, 6, 3
OUTCOME_REVISED = 2
BASELINE_PATH = ROOT / 'review/fixtures/ContestFLExperiment_v4_pre_liveness.sol'
BASELINE_SHA256 = '9b0e7adc7639627be32ea94b61098be3d64b754a1007d7612a5e81bedb526a3a'


def digest(label: str) -> bytes:
    return hashlib.sha256(('ContestFL:liveness-probe:' + label).encode()).digest()


def assert_reverts(call, *, from_address: str | None = None) -> None:
    try:
        call.call({'from': from_address} if from_address else {})
    except Exception:
        return
    raise AssertionError('expected EVM revert, but call succeeded')


def status(contract, round_id):
    return contract.functions.getRoundStatus(round_id).call()


def chain_tx(w3, key: str):
    acct = Account.from_key(key)
    tx = {'chainId': w3.eth.chain_id,
          'nonce': w3.eth.get_transaction_count(acct.address, 'pending'),
          'gasPrice': 0, 'gas': 21000, 'to': acct.address, 'value': 0}
    receipt = w3.eth.wait_for_transaction_receipt(
        w3.eth.send_raw_transaction(Account.sign_transaction(tx, key).raw_transaction), timeout=180)
    if receipt.status != 1:
        raise AssertionError('block advancement transaction failed')
    return receipt


def advance_past(w3, deadline: int, key: str, max_blocks=200):
    if deadline < w3.eth.block_number:
        return
    if deadline - w3.eth.block_number > max_blocks:
        raise AssertionError('probe deadline unexpectedly large')
    while w3.eth.block_number <= deadline:
        chain_tx(w3, key)


def compile_baseline(admin, coordinator, resolver, w3):
    source_bytes = BASELINE_PATH.read_bytes()
    actual_sha = hashlib.sha256(source_bytes).hexdigest()
    if actual_sha != BASELINE_SHA256:
        raise AssertionError(f'baseline Solidity fixture changed: {actual_sha}')
    version = os.environ.get('SOLC_VERSION', '0.8.24')
    compiled = compile_standard({
        'language': 'Solidity',
        'sources': {'ContestFLExperiment.sol': {'content': source_bytes.decode()}},
        'settings': {'optimizer': {'enabled': True, 'runs': 200},
                     'viaIR': True, 'evmVersion': 'london',
                     'outputSelection': {'*': {'*': ['abi', 'evm.bytecode.object']}}}
    }, solc_version=version)
    interface = compiled['contracts']['ContestFLExperiment.sol']['ContestFLExperiment']
    factory = w3.eth.contract(abi=interface['abi'], bytecode=interface['evm']['bytecode']['object'])
    _, receipt = send(w3, admin, factory.constructor(coordinator, resolver))
    return w3.eth.contract(address=receipt.contractAddress, abi=interface['abi']), int(receipt.gasUsed)


def transact(w3, signer, contract_call, metrics, name):
    _, rec = send(w3, signer, contract_call)
    metrics.append({'operation': name, 'gas': int(rec.gasUsed), 'block': int(rec.blockNumber)})
    return rec


def exercised_path(w3, contract, keys, round_id, fault: bool, challenge_blocks=2):
    """Identical on-chain actions for legacy vs liveness-enabled contract.

    This is a gas/transition regression, not a verification of off-chain
    evidence validity: the contracted single resolver remains trusted.
    """
    ops = []
    client_id, update_hash = digest('client'), digest('update')
    initial_roots = [digest(f'root-{i}') for i in range(4)]
    replacement_roots = [digest(f'corrected-{i}') for i in range(4)]
    transact(w3, keys['coordinator'], contract.functions.openRound(round_id, 1, challenge_blocks, 12, 2), ops, 'openRound')
    transact(w3, keys['admin'], contract.functions.submit(round_id, client_id, update_hash), ops, 'submit')
    transact(w3, keys['coordinator'], contract.functions.publishDecisions(round_id, [client_id], [1 if fault else 3]), ops, 'publishDecisions')
    transact(w3, keys['coordinator'], contract.functions.publishInitialState(round_id, *initial_roots), ops, 'publishInitialState')
    if fault:
        transact(w3, keys['admin'], contract.functions.openChallenge(round_id, 0, client_id, 2, digest('reason'), digest('evidence')), ops, 'openChallenge')
        ch_id = int(contract.functions.nextChallengeId().call()) - 1
        transact(w3, keys['resolver'], contract.functions.resolveChallenge(ch_id, OUTCOME_REVISED, 2, digest('certificate'), []), ops, 'resolveChallenge')
        transact(w3, keys['coordinator'], contract.functions.publishCoordinatorReplacement(round_id, *replacement_roots), ops, 'publishCoordinatorReplacement')
    advance_past(w3, int(status(contract, round_id)[5]), keys['admin'])
    transact(w3, keys['admin'], contract.functions.finalize(round_id), ops, 'finalize')
    final = status(contract, round_id)
    if int(final[0]) != PHASE_FINALIZED or bytes(final[9]) != (replacement_roots[-1] if fault else initial_roots[-1]):
        raise AssertionError('normal execution failed to finalize expected checkpoint')
    return {'gas_total': sum(v['gas'] for v in ops), 'operations': ops, 'final_phase': int(final[0])}


def test_submit_expiry(w3, contract, keys, round_id):
    admin_addr = Account.from_key(keys['admin']).address
    gas = []
    transact(w3, keys['coordinator'], contract.functions.openRoundWithTimeouts(round_id, 1, 4, 6, 1, 3, 5), gas, 'openRoundWithTimeouts')
    submit_end, _, _ = contract.functions.getLivenessDeadlines(round_id).call()
    assert_reverts(contract.functions.expireSubmission(round_id), from_address=admin_addr)
    advance_past(w3, int(submit_end), keys['admin'])
    assert_reverts(contract.functions.submit(round_id, digest('client'), digest('update')), from_address=admin_addr)
    assert_reverts(contract.functions.publishInitialState(round_id, *[digest(f'root-{k}') for k in range(4)]), from_address=Account.from_key(keys['coordinator']).address)
    transact(w3, keys['admin'], contract.functions.expireSubmission(round_id), gas, 'expireSubmission')
    if int(status(contract, round_id)[0]) != PHASE_ABORTED:
        raise AssertionError('SUBMIT expiry failed to abort')
    assert_reverts(contract.functions.expireSubmission(round_id), from_address=admin_addr)
    assert_reverts(contract.functions.finalize(round_id), from_address=admin_addr)
    return {'deadline': int(submit_end), 'abort_gas': gas[-1]['gas'], 'final_phase': int(status(contract, round_id)[0]), 'status': 'PASS'}


def open_challenge_for_replace(w3, contract, keys, round_id, *, replacement_blocks=4):
    """Open one 1->2 admission challenge, then resolve it into RESOLVING."""
    gas = []
    cid, uh = digest('one-client'), digest('one-update')
    transact(w3, keys['coordinator'], contract.functions.openRoundWithTimeouts(round_id, 1, 25, 9, 1, 15, replacement_blocks), gas, 'openRoundWithTimeouts')
    transact(w3, keys['admin'], contract.functions.submit(round_id, cid, uh), gas, 'submit')
    transact(w3, keys['coordinator'], contract.functions.publishDecisions(round_id, [cid], [1]), gas, 'publishDecisions')
    transact(w3, keys['coordinator'], contract.functions.publishInitialState(round_id, *[digest(f'init-root-{k}') for k in range(4)]), gas, 'publishInitialState')
    transact(w3, keys['admin'], contract.functions.openChallenge(round_id, 0, cid, 2, digest('reason'), digest('evidence')), gas, 'openChallenge')
    challenge_id = int(contract.functions.nextChallengeId().call())-1
    transact(w3, keys['resolver'], contract.functions.resolveChallenge(challenge_id, OUTCOME_REVISED, 2, digest('certificate'), []), gas, 'resolveChallenge')
    if int(status(contract, round_id)[0]) != PHASE_RESOLVING:
        raise AssertionError('expected RESOLVING')
    return gas


def test_replacement_expiry(w3, contract, keys, round_id):
    gas = open_challenge_for_replace(w3, contract, keys, round_id)
    admin_addr = Account.from_key(keys['admin']).address
    _, replacement_end, _ = contract.functions.getLivenessDeadlines(round_id).call()
    if not replacement_end:
        raise AssertionError('no replacement deadline after last resolved challenge')
    assert_reverts(contract.functions.expireReplacement(round_id), from_address=admin_addr)
    advance_past(w3, int(replacement_end), keys['admin'])
    assert_reverts(contract.functions.publishCoordinatorReplacement(round_id, *[digest(f'rep-root-{k}') for k in range(4)]), from_address=Account.from_key(keys['coordinator']).address)
    assert_reverts(contract.functions.publishResolverFallback(round_id, *[digest(f'rep-root-{k}') for k in range(4)]), from_address=Account.from_key(keys['resolver']).address)
    transact(w3, keys['admin'], contract.functions.expireReplacement(round_id), gas, 'expireReplacement')
    if int(status(contract, round_id)[0]) != PHASE_ABORTED:
        raise AssertionError('RESOLVING expiry failed to abort')
    assert_reverts(contract.functions.finalize(round_id), from_address=admin_addr)
    return {'deadline': int(replacement_end), 'abort_gas': gas[-1]['gas'], 'final_phase': int(status(contract, round_id)[0]), 'status': 'PASS'}


def test_fallback_on_time(w3, contract, keys, round_id):
    gas = open_challenge_for_replace(w3, contract, keys, round_id, replacement_blocks=10)
    transact(w3, keys['resolver'], contract.functions.publishResolverFallback(round_id, *[digest(f'fallback-root-{k}') for k in range(4)]), gas, 'publishResolverFallback')
    transact(w3, keys['admin'], contract.functions.finalize(round_id), gas, 'finalize')
    if int(status(contract, round_id)[0]) != PHASE_FINALIZED:
        raise AssertionError('on-time fallback did not finalize')
    return {'gas_total': sum(op['gas'] for op in gas), 'final_phase': PHASE_FINALIZED, 'status': 'PASS'}


def test_pending_challenge_then_replacement(w3, contract, keys, round_id, *, expire_pending: bool):
    """A revised ancestor must not start a replacement window prematurely."""
    gas=[]
    cid=digest('pending-client')
    cid2=digest('unrelated-client')
    transact(w3, keys['coordinator'], contract.functions.openRoundWithTimeouts(round_id,2,20,9,1,15,5), gas, 'openRoundWithTimeouts')
    transact(w3, keys['admin'], contract.functions.submit(round_id,cid,digest('pending-update')), gas, 'submit_1')
    transact(w3, keys['admin'], contract.functions.submit(round_id,cid2,digest('other-update')), gas, 'submit_2')
    transact(w3, keys['coordinator'], contract.functions.publishDecisions(round_id,[cid,cid2],[1,1]), gas, 'publishDecisions')
    roots=[digest(f'pending-root-{k}') for k in range(4)]
    transact(w3, keys['coordinator'], contract.functions.publishInitialState(round_id,*roots), gas, 'publishInitialState')
    transact(w3, keys['admin'], contract.functions.openChallenge(round_id,0,cid,2,digest('admit-reason'),digest('admit-evidence')), gas, 'openChallenge_admit_1')
    first_id=int(contract.functions.nextChallengeId().call())-1
    # A second client's admission is independent of the revised ancestor,
    # hence it legitimately remains OPEN rather than becoming MOOT.
    transact(w3, keys['admin'], contract.functions.openChallenge(round_id,0,cid2,2,digest('other-reason'),digest('other-evidence')), gas, 'openChallenge_admit_2')
    second_id=int(contract.functions.nextChallengeId().call())-1
    transact(w3, keys['resolver'],contract.functions.resolveChallenge(first_id,OUTCOME_REVISED,2,digest('admit-certificate'),[]),gas,'resolve_admission')
    if int(status(contract,round_id)[4])!=1 or int(contract.functions.getLivenessDeadlines(round_id).call()[1])!=0:
        raise AssertionError('replacement window was opened before outstanding challenge resolved')
    assert_reverts(contract.functions.expireReplacement(round_id), from_address=Account.from_key(keys['admin']).address)
    if expire_pending:
        second_response_deadline=int(contract.functions.challenges(second_id).call()[10])
        advance_past(w3,second_response_deadline,keys['admin'])
        transact(w3,keys['admin'],contract.functions.expireChallenge(second_id),gas,'expireChallenge_pending')
        if int(status(contract,round_id)[0])!=PHASE_ABORTED:
            raise AssertionError('unanswered challenge did not abort the RESOLVING round')
    else:
        transact(w3,keys['resolver'],contract.functions.resolveChallenge(second_id,1,0,digest('other-certificate'),[]),gas,'resolve_second_admission_upheld')
        deadline=int(contract.functions.getLivenessDeadlines(round_id).call()[1])
        if deadline==0 or int(status(contract,round_id)[4])!=0:
            raise AssertionError('replacement deadline not started after last challenge')
        replacements=[digest(f'pending-fixed-{k}') for k in range(4)]
        transact(w3,keys['coordinator'],contract.functions.publishCoordinatorReplacement(round_id,*replacements),gas,'publishCoordinatorReplacement')
        if int(contract.functions.getLivenessDeadlines(round_id).call()[1])!=0:
            raise AssertionError('replacement deadline was not cleared after publication')
        advance_past(w3,int(status(contract,round_id)[5]),keys['admin'])
        transact(w3,keys['admin'],contract.functions.finalize(round_id),gas,'finalize')
        if int(status(contract,round_id)[0])!=PHASE_FINALIZED:
            raise AssertionError('multiple challenges did not reach finalization')
    return {'status':'PASS','final_phase':int(status(contract,round_id)[0]),
            'operations':len(gas), 'gas_total':sum(op['gas'] for op in gas)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rpc', default=os.environ.get('RPC_URL', 'http://node1:8545'))
    args = parser.parse_args()
    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={'timeout': 90}))
    if not w3.is_connected():
        raise RuntimeError('Besu RPC unavailable')
    info = json.loads((ROOT/'network/contracts.json').read_text())
    main_info = info['contracts']['ContestFLExperiment']
    current = w3.eth.contract(address=main_info['address'], abi=main_info['abi'])
    required = {'expireSubmission', 'expireReplacement', 'openRoundWithTimeouts', 'getLivenessDeadlines'}
    available = {x['name'] for x in main_info['abi'] if x['type'] == 'function'}
    if not required <= available:
        raise RuntimeError(f'Deployed bytecode is not the liveness version: {sorted(required-available)}')
    keys = {name: private_key(name) for name in ('admin', 'coordinator', 'resolver')}
    admin = Account.from_key(keys['admin']).address
    coordinator = Account.from_key(keys['coordinator']).address
    resolver = Account.from_key(keys['resolver']).address
    legacy, legacy_deployment_gas = compile_baseline(keys['admin'], coordinator, resolver, w3)
    prefix = int(time.time() * 10_000)
    results = {'blockchain': w3.client_version, 'chain_id': w3.eth.chain_id,
               'baseline_sha256': BASELINE_SHA256,
               'current_deployment_gas': int(main_info['deploymentGas']),
               'baseline_deployment_gas': legacy_deployment_gas,
               'paired_gas': {}, 'liveness_cases': {}}
    for i, variant in enumerate(('nominal','one_admission_correction')):
        fault = variant != 'nominal'
        old = exercised_path(w3, legacy, keys, prefix+10*i+1, fault)
        new = exercised_path(w3, current, keys, prefix+10*i+2, fault)
        old_by_op = {r['operation']: r['gas'] for r in old['operations']}
        new_by_op = {r['operation']: r['gas'] for r in new['operations']}
        if old_by_op.keys() != new_by_op.keys():
            raise AssertionError('non-identical action sequences')
        results['paired_gas'][variant] = {
            'legacy_gas': old['gas_total'], 'liveness_gas': new['gas_total'],
            'delta_gas': new['gas_total']-old['gas_total'],
            'delta_pct': 100*(new['gas_total']-old['gas_total'])/old['gas_total'],
            'per_operation': {op: {'legacy': old_by_op[op], 'liveness': new_by_op[op]} for op in old_by_op},
            'both_finalized_correct_checkpoint': True}
    results['liveness_cases']['silent_coordinator_submit'] = test_submit_expiry(w3, current, keys, prefix+100)
    results['liveness_cases']['silent_coordinator_and_resolver_replacement'] = test_replacement_expiry(w3, current, keys, prefix+101)
    results['liveness_cases']['on_time_resolver_fallback'] = test_fallback_on_time(w3, current, keys, prefix+102)
    results['liveness_cases']['pending_challenge_then_replacement'] = test_pending_challenge_then_replacement(w3,current,keys,prefix+103,expire_pending=False)
    results['liveness_cases']['pending_challenge_times_out'] = test_pending_challenge_then_replacement(w3,current,keys,prefix+104,expire_pending=True)
    results['status']='PASS'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2)+'\n')
    print(json.dumps(results, indent=2), flush=True)

if __name__ == '__main__':
    main()
