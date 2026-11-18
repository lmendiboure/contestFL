#!/usr/bin/env python3
"""Late honest challenge under multi-wave transaction flooding (real Besu receipts).

Distinguishes transaction admission/inclusion success, EVM revert, and RPC
failure. It tests an honest ADMIT challenge submitted near the challenge-window
boundary, unlike the historical experiment which tests a valid finalization tx.
Runs with optional *per-identity* quota 0 or N. This is not an anti-Sybil proof.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import statistics
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# Direct invocation (`python review/late_challenge_flood.py`) must resolve the repository packages.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.run_scenarios import Context, KIND, RoundData, load_contracts, private_key, sha256
from review.block_bounds import sampled_challenge_blocks
from review.timeout_semantics import classify


def sign_call(w3: Web3, call: Any, key: str, nonce: int, gas: int = 400000) -> Any:
    account = Account.from_key(key)
    return Account.sign_transaction(call.build_transaction({
        "from": account.address, "nonce": nonce, "chainId": w3.eth.chain_id,
        "gasPrice": 0, "gas": gas,
    }), key)


def wait_until(w3: Web3, block_target: int) -> int:
    while w3.eth.block_number < block_target:
        time.sleep(.08)
    return int(w3.eth.block_number)


def send_group(endpoint: str, transactions: list[tuple[int, Any]]) -> list[dict[str, Any]]:
    local = Web3(Web3.HTTPProvider(endpoint, request_kwargs={"timeout": 60}))
    rows = []
    for ident, signed in transactions:
        at = time.perf_counter_ns()
        try:
            txid = local.eth.send_raw_transaction(signed.raw_transaction)
            rows.append({"index": ident, "hash": txid.hex(), "submitted_ns": at, "rpc_error": ""})
        except Exception as exc:
            rows.append({"index": ident, "hash": "", "submitted_ns": at,
                         "rpc_error": f"{type(exc).__name__}: {exc}"})
    return rows


def sign_waves(w3: Web3, ctx: Context, attacker_names: list[str],
               count: int, wave_count: int) -> list[list[list[tuple[int, Any]]]]:
    """Pre-sign distinct challenges per nonce stream before waiting near deadline."""
    if count == 0:
        return [[] for _ in range(wave_count)]
    nonces = {
        name: int(w3.eth.get_transaction_count(Account.from_key(ctx.keys[name]).address, "pending"))
        for name in attacker_names
    }
    waves: list[list[list[tuple[int, Any]]]] = []
    for wave in range(wave_count):
        grouped: dict[str, list[tuple[int, Any]]] = defaultdict(list)
        for index in range(count):
            if index % wave_count != wave:
                continue
            who = attacker_names[index % len(attacker_names)]
            call = ctx.contract.functions.openChallenge(
                ctx.round_id, KIND["AGGREGATE"], b"\x00" * 32, 0,
                sha256(f"sustained-flood:reason:{ctx.round_id}:{index}".encode()),
                sha256(f"sustained-flood:evidence:{ctx.round_id}:{index}".encode()),
            )
            signed = sign_call(w3, call, ctx.keys[who], nonces[who])
            nonces[who] += 1
            grouped[who].append((index, signed))
        waves.append(list(grouped.values()))
    return waves


def execute(w3: Web3, contracts: tuple, keys: dict[str, str],
            args: argparse.Namespace, rep: int, count: int, quota: int) -> dict[str, Any]:
    round_id = (time.time_ns() // 1000) * 100 + rep
    data = RoundData.generate(2, args.update_dim, 20261106 + rep * 991, 32)
    ctx = Context(
        w3=w3, contract=contracts[0], logging_contract=contracts[1],
        evidence_contract=contracts[2], validators=args.validators,
        clients=2, repetition=rep, scenario="review_late_honest_challenge",
        round_id=round_id, data=data, batch_size=2,
        challenge_blocks=args.challenge_blocks, response_blocks=args.response_blocks,
        retry_budget=1, flood_count=count, flood_parallelism=args.attacker_identities,
        flood_challenge_blocks=args.challenge_blocks, affected_decisions=1,
        faulty_replacements=0, campaign_tag="revision_late_challenge",
        network_rtt_ms=0, keys=keys,
    )
    previous_quota = int(ctx.contract.functions.maxChallengesPerIdentity().call())
    output: dict[str, Any] = {"repetition": rep, "flood_count": count,
                              "quota_per_identity": quota, "window_blocks": args.challenge_blocks,
                              "lead_blocks": args.lead_blocks, "wave_count": args.waves,
                              "honest_receipt_status": -1,
                              "honest_before_deadline": False, "honest_success": False,
                              "honest_inclusion_latency_ms": float("nan"),
                              "honest_mined_block": -1, "deadline_block": -1,
                              "flood_sent": 0, "flood_mined_success": 0,
                              "flood_mined_reverted": 0, "flood_rpc_errors": 0,
                              "round_finalized": False,
                              "cleanup_abort": False, "error": "",
                              "honest_submission_block": -1, "honest_delay_blocks": -1,
                              "max_observed_block_gas_utilization": float("nan"),
                              "blocks_at_least_90pct_capacity": 0,
                              "measured_blocks": 0, "saturation_observed": False,
                              "resolver_outage_injected": bool(getattr(args, "resolver_timeout_probe", False)),
                              "honest_challenge_id": -1, "resolver_timeout_abort": False,
                              "timeout_expire_tx_hash": "", "terminal_outcome": "not_probed"}
    try:
        # Global policy is configured in isolation: NEVER interleave rounds with
        # other quota settings on this single local test network.
        ctx.sender.send_one(ctx.contract.functions.setMaxChallengesPerIdentity(quota),
                            keys["admin"], "quota_configure")
        wrong = [1, 3]
        ctx.open_contract_round(wrong)
        deadline = int(ctx.contract.functions.getRoundStatus(round_id).call()[5])
        output["deadline_block"] = deadline
        names = sorted((k for k in keys if k.startswith("challenger") and k != "challenger0"),
                       key=lambda x: int(x.removeprefix("challenger")))
        attackers = names[:args.attacker_identities]
        if not attackers:
            raise RuntimeError("need at least one non-honest challenger identity")
        wave_groups = sign_waves(w3, ctx, attackers, count, args.waves)
        endpoint = getattr(w3.provider, "endpoint_uri", None)
        if endpoint is None:
            raise RuntimeError("an HTTP JSON-RPC endpoint is required")
        target_honest = deadline - args.lead_blocks
        # Flood ingress is divided into several waves over the final blocks.
        first_target = target_honest - args.waves * args.wave_spacing_blocks
        if int(w3.eth.block_number) > first_target:
            raise RuntimeError("pre-signing finished too late for the selected window; enlarge CHALLENGE_BLOCKS")
        all_flood = []
        for index, groups in enumerate(wave_groups):
            wait_until(w3, first_target + index * args.wave_spacing_blocks)
            with ThreadPoolExecutor(max_workers=max(1, min(len(groups), args.attacker_identities))) as pool:
                futs = [pool.submit(send_group, endpoint, group) for group in groups]
                for fut in as_completed(futs):
                    all_flood.extend(fut.result())
        wait_until(w3, target_honest)
        honest_call = ctx.contract.functions.openChallenge(
            round_id, KIND["ADMIT"], data.client_ids[0], 3,
            sha256(b"late-honest-admission"), sha256(b"evidence-late-honest"),
        )
        honest_key = keys["challenger0"]
        honest_nonce = int(w3.eth.get_transaction_count(Account.from_key(honest_key).address, "pending"))
        signed = sign_call(w3, honest_call, honest_key, honest_nonce)
        honest_submitted = time.perf_counter_ns()
        output["honest_submission_block"] = int(w3.eth.block_number)
        honest_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(honest_hash, timeout=args.receipt_timeout)
        output["honest_receipt_status"] = int(receipt.status)
        output["honest_mined_block"] = int(receipt.blockNumber)
        output["honest_delay_blocks"] = max(0, int(receipt.blockNumber) - output["honest_submission_block"])
        output["honest_before_deadline"] = int(receipt.blockNumber) <= deadline
        output["honest_success"] = int(receipt.status) == 1 and int(receipt.blockNumber) <= deadline
        output["honest_inclusion_latency_ms"] = round((time.perf_counter_ns()-honest_submitted)/1e6, 3)
        output["honest_tx_hash"] = honest_hash.hex()
        for tx in all_flood:
            if tx["rpc_error"]:
                output["flood_rpc_errors"] += 1
                continue
            output["flood_sent"] += 1
            try:
                r = w3.eth.wait_for_transaction_receipt(tx["hash"], timeout=args.receipt_timeout)
                if int(r.status) == 1:
                    output["flood_mined_success"] += 1
                else:
                    output["flood_mined_reverted"] += 1
            except Exception:
                output["flood_rpc_errors"] += 1
        # Measure whether the attack actually approached this chain's block gas
        # capacity. Submitted transaction count alone is not a saturation test.
        observed = []
        # The challenge deadline may still be in the future after a successful
        # honest receipt. Never query blocks that Besu has not mined yet.
        # Restrict the metric to the actual challenge window as well.
        latest_mined_block = int(w3.eth.block_number)
        for block_number in sampled_challenge_blocks(first_target, deadline, latest_mined_block):
            block = w3.eth.get_block(block_number)
            if int(block.gasLimit) > 0:
                observed.append(int(block.gasUsed) / int(block.gasLimit))
        output["measured_blocks"] = len(observed)
        output["max_observed_block_gas_utilization"] = max(observed) if observed else float("nan")
        output["blocks_at_least_90pct_capacity"] = sum(x >= .90 for x in observed)
        output["saturation_observed"] = any(x >= .90 for x in observed)
        if getattr(args, "resolver_timeout_probe", False):
            # Failure-injection only: the resolver deliberately does not reply.
            # It tests the explicit contract timeout transition, NOT its
            # probability during normal operation or protection against Sybils.
            if output["honest_success"]:
                events = ctx.contract.events.ChallengeOpened().process_receipt(receipt)
                honest = [e for e in events if int(e["args"]["roundId"]) == round_id]
                if len(honest) != 1:
                    raise AssertionError("cannot identify honest challenge event from its receipt")
                challenge_id = int(honest[0]["args"]["challengeId"])
                output["honest_challenge_id"] = challenge_id
                stored = ctx.contract.functions.challenges(challenge_id).call()
                if int(stored[0]) != round_id:
                    raise AssertionError("challenge id does not belong to this round")
                ctx.wait_response_deadline(challenge_id)
                expiry = ctx.sender.send_one(
                    ctx.contract.functions.expireChallenge(challenge_id),
                    keys["challenger0"], "expire_unanswered_honest_challenge")
                status = ctx.contract.functions.getRoundStatus(round_id).call()
                output["resolver_timeout_abort"] = int(status[0]) == 6 and int(expiry.status) == 1
                output["timeout_expire_tx_hash"] = expiry.tx_hash
                output["terminal_outcome"] = classify(
                    included_before_deadline=True,
                    response_timed_out=True,
                    aborted_onchain=output["resolver_timeout_abort"])
            else:
                # No valid on-chain honest challenge: losing C1 cannot be
                # relabeled as a resolver-timeout abort. Other adversarial
                # challenges may remain pending and are not resolved here.
                output["terminal_outcome"] = classify(
                    included_before_deadline=False, response_timed_out=False,
                    aborted_onchain=False)
    except Exception as exc:
        output["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        # Cleanup is deliberately reported separately. It is NOT a measured
        # timeout-induced abort rate and must not be interpreted as one.
        try:
            status = ctx.contract.functions.getRoundStatus(round_id).call()
            if int(status[0]) not in (0, 5, 6):
                ctx.abort("review_experiment_cleanup")
                output["cleanup_abort"] = True
        except Exception as exc:
            output["error"] += f"\nCleanup abort failed: {exc}"
        try:
            ctx.sender.send_one(ctx.contract.functions.setMaxChallengesPerIdentity(previous_quota),
                                keys["admin"], "quota_restore")
        except Exception as exc:
            output["error"] += f"\nQuota restore failed: {exc}"
    return output


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    i = int(pos)
    return xs[i] if i == len(xs) - 1 else xs[i] + (pos - i) * (xs[i + 1] - xs[i])


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        # A failed early trial can lack optional keys (e.g., honest_tx_hash).
        # Build the union, so later trials do not corrupt or erase the CSV.
        fields = list(dict.fromkeys(k for row in rows for k in row))
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--validators", type=int, default=4)
    p.add_argument("--flood-counts", default="0,30,90")
    p.add_argument("--quotas", default="0,1")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--attacker-identities", type=int, default=4)
    p.add_argument("--waves", type=int, default=3)
    p.add_argument("--wave-spacing-blocks", type=int, default=2)
    p.add_argument("--lead-blocks", type=int, default=2)
    p.add_argument("--challenge-blocks", type=int, default=40)
    p.add_argument("--response-blocks", type=int, default=120)
    p.add_argument("--update-dim", type=int, default=1024)
    p.add_argument("--receipt-timeout", type=int, default=300)
    p.add_argument("--resolver-timeout-probe", action="store_true", help="Inject a resolver outage and exercise the on-chain expireChallenge transition for admitted honest challenges; NOT an empirical outage rate")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--rpc", default=os.getenv("RPC_URL", "http://node1:8545"))
    args = p.parse_args()
    if args.rounds <= 0 or min(args.attacker_identities, args.waves,
                               args.wave_spacing_blocks, args.lead_blocks) <= 0:
        p.error("positive repetitions, identities, waves and timing required")
    if args.challenge_blocks < (args.waves + 1) * args.wave_spacing_blocks + args.lead_blocks + 10:
        p.error("challenge_blocks too small for preparation + staged flood + honest probe")
    floods = [int(v) for v in args.flood_counts.split(",")]
    quotas = [int(v) for v in args.quotas.split(",")]
    if any(v < 0 for v in floods + quotas):
        p.error("nonnegative flood counts and quotas required")
    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 90}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        raise RuntimeError("Besu RPC unavailable")
    contracts = load_contracts(w3)[:3]
    keys = {name: private_key(name) for name in json.loads((ROOT / "network/secrets/addresses.json").read_text())}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    repetition = 0
    for quota in quotas:
        for flood in floods:
            for _ in range(args.rounds):
                repetition += 1
                row = execute(w3, contracts, keys, args, repetition, flood, quota)
                rows.append(row)
                write_csv(args.output_dir / "late_challenge_raw.csv", rows)
                print(json.dumps({"repetition": repetition, "flood": flood, "quota": quota,
                                  "honest_success": row["honest_success"],
                                  "error": bool(row["error"])}), flush=True)
                if row["error"]:
                    print(f"TRIAL_ERROR repetition={repetition}: {row['error'].splitlines()[0]}",
                          file=sys.stderr, flush=True)
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["flood_count"], r["quota_per_identity"])].append(r)
    summary = []
    for (flood, quota), group in sorted(groups.items()):
        values = [r["honest_inclusion_latency_ms"] for r in group if r["honest_success"]]
        summary.append({"flood_count": flood, "quota_per_identity": quota,
                        "attempts": len(group),
                        "honest_successes": sum(r["honest_success"] for r in group),
                        "rpc_or_setup_errors": sum(bool(r["error"]) for r in group),
                        "median_honest_latency_ms_success_only": statistics.median(values) if values else "",
                        "flood_mined_success_total": sum(r["flood_mined_success"] for r in group),
                        "flood_mined_reverted_total": sum(r["flood_mined_reverted"] for r in group),
                        "saturated_trials_observed": sum(r["saturation_observed"] for r in group),
                        "coverage_misses_C1": sum(r["terminal_outcome"] == "coverage_miss_C1" for r in group),
                        "injected_resolver_timeout_aborts_onchain": sum(r["resolver_timeout_abort"] for r in group),
                        "honest_latency_p95_all_receipts_ms": percentile([r["honest_inclusion_latency_ms"] for r in group if r["honest_receipt_status"] != -1], .95),
                        "honest_latency_p99_all_receipts_ms": percentile([r["honest_inclusion_latency_ms"] for r in group if r["honest_receipt_status"] != -1], .99),
                        "max_observed_block_gas_utilization": max((r["max_observed_block_gas_utilization"] for r in group if r["measured_blocks"]), default=float("nan")),
                        "honest_delay_blocks_p95_success_only": percentile([r["honest_delay_blocks"] for r in group if r["honest_success"]], .95)})
    write_csv(args.output_dir / "late_challenge_summary.csv", summary)
    (args.output_dir / "late_challenge_metadata.json").write_text(json.dumps({
        "chain_id": w3.eth.chain_id, "client_version": w3.client_version,
        "parameters": vars(args) | {"output_dir": str(args.output_dir)},
        "note": "Honest inclusion and optional forced-resolver-outage terminal state are distinct. When injected, timeout_abort is an observed expireChallenge on chain conditional on intentionally withheld resolution, NOT a naturally occurring resolver-timeout probability. A challenge missed at deadline is a C1 coverage loss, NOT a timeout abort. All cleanup aborts excluded. Quotas are per address, not Sybil-proof.",
    }, indent=2) + "\n")
    if any(row["error"] for row in rows):
        raise SystemExit("some runs had errors: inspect late_challenge_raw.csv; no result is discarded")


if __name__ == "__main__":
    main()
