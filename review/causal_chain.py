#!/usr/bin/env python3
"""Reviewer extension: multiple *observed*, evidence-backed causal revisions.

This is an intentionally adversarial repeated-fault workload, not the average
failure rate of an FL deployment.  It exercises the experimental contract's
compressed state (not a fully dynamic on-chain dependency DAG):

  initial reject(1) -> admission revision to admitted/excluded(2)
  -> inclusion revision to admitted/included(3)
  -> aggregate checkpoint revision -> finalization.

The same submissions and seeded update arrays are used by each policy.  A
restart policy sees the same staged faulty successive candidate publications,
then a final correct candidate.  The 'aggregate_reaudit' policy uses the same
ContestFL ledger actions and additionally performs off-chain rechecking;
therefore it is a *policy ablation*, not a generic level-cascade implementation.
The existing v3 measurements remain the Eager benchmark.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import sys
import time
import traceback
from pathlib import Path
from dataclasses import asdict
from typing import Any

from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.run_scenarios import Context, RoundData, load_contracts, private_key
from review.causal_chain_plan import candidate, chain_plan, verify_plan

POLICIES = ("contestfl", "abort_restart", "aggregate_reaudit")
WORKLOAD = "reject_admit_include_aggregate_chain"


def context(w3: Web3, contracts: tuple, keys: dict[str, str], args: argparse.Namespace,
            round_id: int, data: RoundData, rep: int, policy: str) -> Context:
    return Context(
        w3=w3, contract=contracts[0], logging_contract=contracts[1],
        evidence_contract=contracts[2], validators=args.validators,
        clients=args.clients, repetition=rep, scenario=WORKLOAD + "_" + policy,
        round_id=round_id, data=data, batch_size=args.batch_size,
        challenge_blocks=args.challenge_blocks, response_blocks=args.response_blocks,
        retry_budget=args.retry_budget, flood_count=0, flood_parallelism=1,
        flood_challenge_blocks=args.challenge_blocks, affected_decisions=1,
        faulty_replacements=0, campaign_tag=args.tag, network_rtt_ms=0, keys=keys,
    )


def evidence_for(ctx: Context, stage: int, state: list[int], checkpoint: bytes):
    if stage == 0:
        evidence = ctx.admission_evidence(0, observed_state=1, policy_state=2)
        kind, client_id, corrected_state = "ADMIT", ctx.data.client_ids[0], 2
    elif stage == 1:
        # In the preceding epoch, the admitted root includes this client but
        # the aggregate-input root does not. This is a *newly active* INCLUDE.
        evidence = ctx.inclusion_evidence(0, observed_state=2)
        kind, client_id, corrected_state = "INCLUDE", ctx.data.client_ids[0], 3
    elif stage == 2:
        evidence = ctx.aggregate_evidence(state, checkpoint)
        kind, client_id, corrected_state = "AGGREGATE", bytes(32), 0
    else:
        raise ValueError(f"unexpected fault stage {stage}")
    if evidence.verdict != "REVISED" or evidence.corrected_state != corrected_state:
        raise AssertionError(
            f"stage {stage} evidence mismatch: expected REVISED/{corrected_state}, "
            f"got {evidence.verdict}/{evidence.corrected_state}: {evidence.detail}"
        )
    if not evidence.valid_evidence:
        raise AssertionError("invalid or unavailable evidence cannot authorize a correction")
    return evidence, kind, client_id, corrected_state


def run_case(w3: Web3, contracts: tuple, keys: dict[str, str], args: argparse.Namespace,
             rep: int, seed: int, first_id: int, policy: str, data: RoundData) -> dict[str, Any]:
    initial_states = [3] * args.clients
    correct_checkpoint = data.checkpoint(initial_states)
    contexts: list[Context] = []
    proof_cpu_ms = proof_wall_ms = recheck_cpu_ms = recheck_wall_ms = 0.0
    verified_faults = 0
    publication_epochs: list[int] = []
    checkpoints: list[str] = []
    error = ""
    final_ok = False
    state_version = -1
    final_phase = -1
    started = time.perf_counter_ns()
    try:
        ctx = context(w3, contracts, keys, args, first_id, data, rep, policy)
        contexts.append(ctx)
        for stage, planned in enumerate(chain_plan()):
            states, checkpoint = candidate(initial_states, stage, data)
            if planned.prior_epoch != stage:
                raise AssertionError("static causal plan changed unexpectedly")
            if stage == 0 or policy == "abort_restart":
                # A new round resends the same underlying client updates.
                ctx.open_contract_round(states, checkpoint)
            else:
                # A replacement in the same logical round, preserving submissions.
                ctx.publish_replacement(states, checkpoint)
            status_before = ctx.contract.functions.getRoundStatus(ctx.round_id).call()
            if int(status_before[0]) != 2:  # ContestFL Phase.CHALLENGE
                raise AssertionError(f"candidate not in CHALLENGE at stage {stage}")
            if policy != "abort_restart" and int(status_before[1]) != stage:
                raise AssertionError("unexpected replacement epoch")
            if bytes(status_before[9]) != checkpoint:
                raise AssertionError("published checkpoint mismatch")
            if policy == "aggregate_reaudit" and stage > 0:
                # Recheck the *published* replacement, not a hypothetical
                # future checkpoint.  The second recheck sees the intentionally
                # wrong aggregate and identifies it before normal challenge
                # resolution.  This is an off-chain policy ablation only.
                from bench.adapters import AggregateAdapter
                extra = AggregateAdapter.verify(
                    updates=data.updates, states=states,
                    claimed_checkpoint=checkpoint,
                    aggregate_root=ctx.current_trees[2].root)
                expected = "UPHELD" if stage == 1 else "REVISED"
                if extra.verdict != expected:
                    raise AssertionError(f"re-audit at stage {stage}: {extra.verdict} != {expected}")
                recheck_cpu_ms += extra.evidence_generation_cpu_ms + extra.verification_cpu_ms
                recheck_wall_ms += extra.evidence_generation_ms + extra.verification_ms
            publication_epochs.append(int(status_before[1]))
            checkpoints.append(checkpoint.hex())
            evidence, kind, cid, corrected_state = evidence_for(ctx, stage, states, checkpoint)
            if kind != planned.kind or corrected_state != planned.corrected_state:
                raise AssertionError("runtime evidence diverged from the causal plan")
            proof_cpu_ms += evidence.evidence_generation_cpu_ms + evidence.verification_cpu_ms
            proof_wall_ms += evidence.evidence_generation_ms + evidence.verification_ms
            challenge = ctx.open_challenge(kind, cid, corrected_state,
                                           f"causal_chain_stage_{stage}",
                                           evidence_hash=evidence.evidence_hash)
            ctx.record_adapter(challenge, evidence)
            verified_faults += 1
            if policy == "abort_restart":
                ctx.abort(f"abort_after_causal_fault_{stage}")
                if int(ctx.contract.functions.getRoundStatus(ctx.round_id).call()[0]) != 6:
                    raise AssertionError("restart policy failed to abort current round")
                ctx = context(w3, contracts, keys, args, first_id + stage + 1, data, rep, policy)
                contexts.append(ctx)
            else:
                ctx.resolve(challenge, "REVISED", corrected_state,
                            certificate_hash=evidence.certificate_hash)
                state_version_expected = 2 if stage == 0 else 3
                if stage < 2:
                    actual_state = int(ctx.contract.functions.decisionState(ctx.round_id, cid).call())
                    if actual_state != corrected_state:
                        raise AssertionError("corrected state was not imposed by Solidity")
                    actual_version = int(ctx.contract.functions.decisionVersion(ctx.round_id, cid).call())
                    if actual_version != state_version_expected:
                        raise AssertionError("decisionVersion not incremented")
        final_states, final_cp = candidate(initial_states, 3, data)
        if policy == "abort_restart":
            ctx.open_contract_round(final_states, final_cp)
        else:
            ctx.publish_replacement(final_states, final_cp)
        ctx.wait_challenge_window()
        ctx.finalize()
        final_status = ctx.contract.functions.getRoundStatus(ctx.round_id).call()
        final_phase = int(final_status[0])
        state_version = int(ctx.contract.functions.decisionVersion(ctx.round_id, data.client_ids[0]).call())
        actual_state = int(ctx.contract.functions.decisionState(ctx.round_id, data.client_ids[0]).call())
        final_ok = (final_phase == 5 and bytes(final_status[9]) == correct_checkpoint
                    and actual_state == 3 and int(final_status[4]) == 0
                    and (int(final_status[1]) == 3 and state_version == 3
                         if policy != "abort_restart" else int(final_status[1]) == 0 and state_version == 1)
                    and verified_faults == 3)
        if not final_ok:
            raise AssertionError("final checkpoint/version/open-challenge invariant failed")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    elapsed = (time.perf_counter_ns() - started) / 1e6
    txs = [tx for c in contexts for tx in c.sender.metrics]
    return {
        "workload": WORKLOAD, "design": policy, "client_count": args.clients,
        "repetition": rep, "seed": seed, "round_id": first_id,
        "correct_checkpoint_finalized": final_ok, "wall_ms": round(elapsed, 3),
        "gas_total": sum(m.gas_used for m in txs), "tx_count": len(txs),
        "verification_cpu_ms": round(proof_cpu_ms + recheck_cpu_ms, 4),
        "verification_wall_ms": round(proof_wall_ms + recheck_wall_ms, 4),
        "extra_reaudit_cpu_ms": round(recheck_cpu_ms, 4),
        "challenge_wait_wall_ms": round(sum(c.challenge_wait_ms for c in contexts), 3),
        "verified_fault_count": verified_faults, "rounds_created": len(contexts),
        "published_epochs": json.dumps(publication_epochs),
        "published_checkpoints": json.dumps(checkpoints),
        "final_phase": final_phase, "final_decision_version": state_version,
        "challenge_blocks": args.challenge_blocks, "response_blocks": args.response_blocks,
        "retry_budget": args.retry_budget, "update_dim": args.update_dim,
        "error": error,
        "_tx_receipts": [
            {"workload": WORKLOAD, "design": policy, "repetition": rep,
             "seed": seed, "round_id": ctx.round_id, "phase": tx.phase,
             "tx_hash": tx.tx_hash, "block_number": tx.block_number,
             "gas_used": tx.gas_used, "status": tx.status,
             "calldata_bytes": tx.calldata_bytes, "latency_ms": tx.latency_ms}
            for ctx in contexts for tx in ctx.sender.metrics
        ],
        "_adapter_records": [asdict(a) for ctx in contexts for a in ctx.adapter_metrics],
    }


def store_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("refusing empty results")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--validators", type=int, default=4)
    p.add_argument("--clients", type=int, default=100)
    p.add_argument("--rounds", type=int, default=20)
    p.add_argument("--warmup", type=int, default=1)
    p.add_argument("--challenge-blocks", type=int, default=11)
    p.add_argument("--response-blocks", type=int, default=120)
    p.add_argument("--retry-budget", type=int, default=3)
    p.add_argument("--update-dim", type=int, default=262144)
    p.add_argument("--batch-size", type=int, default=50)
    p.add_argument("--seed", type=int, default=20261111)
    p.add_argument("--designs", default=",".join(POLICIES))
    p.add_argument("--tag", default="review_causal_v4")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--rpc", default=os.environ.get("RPC_URL", "http://node1:8545"))
    p.add_argument("--allow-failures", action="store_true")
    args = p.parse_args()
    policies = [p.strip() for p in args.designs.split(",") if p.strip()]
    if set(policies) - set(POLICIES) or len(set(policies)) != len(policies) or not policies:
        p.error(f"unique policies required among {POLICIES}")
    if args.clients < 2 or args.rounds < 1 or args.warmup < 0 or args.retry_budget < 3:
        p.error("clients>=2, rounds>=1, warmup>=0 and retry-budget>=3 required")
    if args.challenge_blocks <= 0 or args.response_blocks <= 0 or args.batch_size <= 0:
        p.error("deadlines and batch size must be positive")
    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 90}))
    if not w3.is_connected():
        raise RuntimeError(f"Besu RPC unavailable at {args.rpc}")
    contracts = load_contracts(w3)[:3]
    addresses = json.loads((ROOT / "network/secrets/addresses.json").read_text())
    keys = {name: private_key(name) for name in addresses}
    measurements: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []
    adapter_records: list[dict[str, Any]] = []
    serial = int(time.time_ns() // 1000) * 100
    for rep in range(-args.warmup, args.rounds):
        seed = args.seed + rep * 1000003 + args.clients * 101
        data = RoundData.generate(args.clients, args.update_dim, seed, 32)
        # An invariant of the workload, not blockchain protocol time: validate
        # once per shared seed and outside timed policy comparisons.
        verify_plan(data)
        order = policies.copy()
        random.Random(seed).shuffle(order)
        for policy in order:
            serial += 1000  # reserve 4 distinct round IDs per policy
            row = run_case(w3, contracts, keys, args, rep, seed, serial, policy, data)
            print(json.dumps({k: row[k] for k in (
                "repetition", "design", "correct_checkpoint_finalized", "verified_fault_count",
                "wall_ms", "gas_total", "error")}), flush=True)
            if rep >= 0:
                transactions.extend(row.pop("_tx_receipts"))
                adapter_records.extend(row.pop("_adapter_records"))
                measurements.append(row)
                store_csv(args.output_dir / "causal_chain_raw.csv", measurements)
                if transactions:
                    store_csv(args.output_dir / "causal_chain_transactions.csv", transactions)
                if adapter_records:
                    store_csv(args.output_dir / "causal_chain_evidence.csv", adapter_records)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "causal_chain_metadata.json").write_text(json.dumps({
        "description": __doc__, "workload": WORKLOAD, "policies": policies,
        "rounds": args.rounds, "warmup": args.warmup, "clients": args.clients,
        "seed": args.seed, "challenge_blocks": args.challenge_blocks,
        "response_blocks": args.response_blocks, "retry_budget": args.retry_budget,
        "update_dim": args.update_dim, "chain_id": w3.eth.chain_id,
        "client_version": w3.client_version,
        "contracts_json_sha256": hashlib.sha256((ROOT / "network/contracts.json").read_bytes()).hexdigest(),
        "scope": [
            "three adversarial revisions across same logical round, vs three full restarts",
            "aggregate_reaudit shares the same on-chain path as ContestFL; extra aggregate verification is off-chain",
            "compressed decisionState contract; does not prove arbitrary dynamic DAG support",
            "restart sees staged faults on each reposting; no claim about faults that eager prevents",
            "the v3 Eager experiment is reported separately, not falsely paired to later-stage faults",
            "no model of FL training, WAN transport, availability or Sybil resistance",
        ],
    }, indent=2) + "\n", encoding="utf-8")
    if any(not r["correct_checkpoint_finalized"] or r["error"] for r in measurements) and not args.allow_failures:
        print("Some measured runs failed; raw CSV retained. See error column.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
