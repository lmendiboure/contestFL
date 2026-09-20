#!/usr/bin/env python3
"""Measure whether a bounded-capacity block backlog delays an honest finalization.

The experiment creates two independent ContestFL rounds on the same ledger:

* an attack round whose challenge window receives a burst of distinct unsupported
  aggregate challenges; and
* a clean probe round whose challenge window has already elapsed and whose
  finalization transaction is valid when submitted.

The flood is broadcast first.  After a configurable delay, the honest probe
finalization is broadcast from the coordinator account at the same gas price.
This measures transaction-inclusion contention only; it does not implement a
monetary bond or claim protection against a validator-level denial of service.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import socket
import statistics
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence, TypeVar

from eth_account import Account
from web3 import Web3
from web3.exceptions import ExtraDataLengthError
from web3.middleware import ExtraDataToPOAMiddleware

try:
    from .run_scenarios import (
        Context,
        KIND,
        OUTCOME,
        PHASE,
        RoundData,
        load_contracts,
        private_key,
        sha256,
    )
except ImportError:  # direct execution from bench/
    from run_scenarios import (  # type: ignore
        Context,
        KIND,
        OUTCOME,
        PHASE,
        RoundData,
        load_contracts,
        private_key,
        sha256,
    )

ROOT = Path(__file__).resolve().parents[1]
ZERO32 = b"\x00" * 32
T = TypeVar("T")


def rpc_read(
    operation: Callable[[], T],
    *,
    label: str,
    attempts: int = 8,
    initial_delay_s: float = 0.25,
) -> T:
    """Retry an idempotent JSON-RPC read after transient HTTP/RPC failures.

    Besu can briefly close or delay an HTTP connection around block production or
    container start-up.  All uses of this helper are read-only, so retrying cannot
    duplicate a transaction.  Transaction broadcasts are intentionally not retried
    here because an RPC disconnect may happen after a node has already accepted the
    transaction.
    """
    if attempts <= 0:
        raise ValueError("attempts must be positive")
    delay = max(0.0, initial_delay_s)
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except ExtraDataLengthError:
            # This is a deterministic client-formatting error, not a transient RPC
            # failure.  It indicates that PoA/QBFT middleware was not installed.
            raise
        except Exception as exc:  # provider exceptions vary across requests/urllib3/web3
            last = exc
            if attempt == attempts:
                break
            print(
                json.dumps({
                    "rpcRetry": label,
                    "attempt": attempt,
                    "maxAttempts": attempts,
                    "error": f"{type(exc).__name__}: {exc}",
                    "sleepSeconds": round(delay, 3),
                }),
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
            delay = min(max(delay * 2.0, 0.05), 3.0)
    assert last is not None
    raise RuntimeError(f"RPC read '{label}' failed after {attempts} attempts") from last


def latest_block(w3: Web3, *, attempts: int = 8) -> Any:
    return rpc_read(
        lambda: w3.eth.get_block("latest"),
        label="eth_getBlockByNumber(latest)",
        attempts=attempts,
    )


def current_block_number(w3: Web3, *, attempts: int = 8) -> int:
    return int(
        rpc_read(
            lambda: w3.eth.block_number,
            label="eth_blockNumber",
            attempts=attempts,
        )
    )


@dataclass(frozen=True)
class PendingTx:
    ordinal: int
    label: str
    sender: str
    tx_hash: Any
    submitted_ns: int


def percentile(values: Sequence[float], p: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * p
    lo = int(math.floor(position))
    hi = int(math.ceil(position))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def parse_ints(raw: str) -> list[int]:
    values = [int(item.strip(), 0) for item in raw.split(",") if item.strip()]
    if not values or any(value < 0 for value in values):
        raise ValueError("integer list must contain non-negative values")
    return values


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    records = list(rows)
    if not records:
        raise ValueError(f"no rows for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def wait_until_after(w3: Web3, block_number: int) -> None:
    while current_block_number(w3) <= block_number:
        time.sleep(0.05)


def wait_for_next_block(w3: Web3, current: int, timeout_s: float = 15.0) -> int:
    """Return the first block strictly after ``current`` or fail clearly."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        head = current_block_number(w3)
        if head > current:
            return head
        time.sleep(0.02)
    raise TimeoutError(f"no new block after {current} within {timeout_s:.1f}s")


def account_keys() -> dict[str, str]:
    addresses_path = ROOT / "network" / "secrets" / "addresses.json"
    names = json.loads(addresses_path.read_text(encoding="utf-8"))
    return {name: private_key(name) for name in names}


def challenger_names(keys: dict[str, str]) -> list[str]:
    names = [name for name in keys if name.startswith("challenger")]
    return sorted(names, key=lambda name: int(name.removeprefix("challenger")))


def sign_call(w3: Web3, call: Any, key: str, nonce: int, gas_price: int) -> tuple[Any, str]:
    account = Account.from_key(key)
    base = {
        "from": account.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
        "gasPrice": gas_price,
    }
    estimated = int(call.estimate_gas(base))
    base["gas"] = int(estimated * 1.25) + 40_000
    built = call.build_transaction(base)
    return Account.sign_transaction(built, key), account.address


def prepare_flood_transactions(
    *,
    w3: Web3,
    contract: Any,
    round_id: int,
    flood_count: int,
    keys: dict[str, str],
    gas_price: int,
) -> list[list[tuple[int, Any, str]]]:
    names = challenger_names(keys)
    if flood_count and not names:
        raise RuntimeError("no challenger accounts configured")

    calls_by_name: dict[str, list[tuple[int, Any]]] = {}
    for ordinal in range(flood_count):
        name = names[ordinal % len(names)]
        reason = sha256(f"bounded-contention:{round_id}:{ordinal}".encode())
        evidence = sha256(f"bounded-contention:evidence:{round_id}:{ordinal}".encode())
        call = contract.functions.openChallenge(
            round_id,
            KIND["AGGREGATE"],
            ZERO32,
            0,
            reason,
            evidence,
        )
        calls_by_name.setdefault(name, []).append((ordinal, call))

    signed_groups: list[list[tuple[int, Any, str]]] = []
    for name, calls in calls_by_name.items():
        key = keys[name]
        address = Account.from_key(key).address
        nonce = int(w3.eth.get_transaction_count(address, "pending"))
        group: list[tuple[int, Any, str]] = []
        for offset, (ordinal, call) in enumerate(calls):
            signed, sender = sign_call(w3, call, key, nonce + offset, gas_price)
            group.append((ordinal, signed, sender))
        signed_groups.append(group)
    return signed_groups


def broadcast_group(endpoint: str, group: list[tuple[int, Any, str]]) -> list[PendingTx]:
    local_w3 = Web3(Web3.HTTPProvider(endpoint, request_kwargs={"timeout": 60}))
    pending: list[PendingTx] = []
    for ordinal, signed, sender in group:
        submitted_ns = time.perf_counter_ns()
        tx_hash = local_w3.eth.send_raw_transaction(signed.raw_transaction)
        pending.append(PendingTx(ordinal, "flood", sender, tx_hash, submitted_ns))
    return pending


def collect_receipt(w3: Web3, pending: PendingTx, timeout: int) -> dict[str, Any]:
    receipt = w3.eth.wait_for_transaction_receipt(pending.tx_hash, timeout=timeout)
    transaction = w3.eth.get_transaction(pending.tx_hash)
    return {
        "ordinal": pending.ordinal,
        "label": pending.label,
        "tx_hash": pending.tx_hash.hex(),
        "sender": pending.sender,
        "submitted_ns": pending.submitted_ns,
        "latency_ms": (time.perf_counter_ns() - pending.submitted_ns) / 1e6,
        "block_number": int(receipt.blockNumber),
        "gas_used": int(receipt.gasUsed),
        "status": int(receipt.status),
        "calldata_bytes": len(bytes(transaction["input"])),
        "receipt": receipt,
    }


def check_finalized(ctx: Context, expected_checkpoint: bytes) -> bool:
    status = ctx.contract.functions.getRoundStatus(ctx.round_id).call()
    return int(status[0]) == PHASE["FINALIZED"] and bytes(status[9]) == expected_checkpoint


def open_clean_round(ctx: Context) -> bytes:
    states = [3] * ctx.clients
    expected = ctx.data.checkpoint(states)
    ctx.open_contract_round(states, expected)
    return expected


def execute_one(
    *,
    w3: Web3,
    contract: Any,
    logging_contract: Any,
    evidence_contract: Any,
    keys: dict[str, str],
    validators: int,
    round_id: int,
    repetition: int,
    flood_count: int,
    resolver_parallelism: int,
    challenge_blocks: int,
    response_blocks: int,
    honest_delay_ms: float,
    alignment_delay_ms: float,
    broadcast_parallelism: int,
    gas_price: int,
    receipt_timeout: int,
    seed: int,
    tag: str,
) -> dict[str, Any]:
    # One client is sufficient because the flood uses distinct aggregate claims.
    attack_data = RoundData.generate(1, 1024, seed + round_id, 32)
    probe_data = RoundData.generate(1, 1024, seed + round_id + 1, 32)

    attack = Context(
        w3=w3,
        contract=contract,
        logging_contract=logging_contract,
        evidence_contract=evidence_contract,
        validators=validators,
        clients=1,
        repetition=repetition,
        scenario="bounded_gas_contention_attack",
        round_id=round_id,
        data=attack_data,
        batch_size=1,
        challenge_blocks=challenge_blocks,
        response_blocks=response_blocks,
        retry_budget=1,
        flood_count=flood_count,
        flood_parallelism=resolver_parallelism,
        flood_challenge_blocks=challenge_blocks,
        affected_decisions=1,
        faulty_replacements=0,
        campaign_tag=tag,
        network_rtt_ms=0,
        keys=keys,
    )
    probe = Context(
        w3=w3,
        contract=contract,
        logging_contract=logging_contract,
        evidence_contract=evidence_contract,
        validators=validators,
        clients=1,
        repetition=repetition,
        scenario="bounded_gas_contention_probe",
        round_id=round_id + 1,
        data=probe_data,
        batch_size=1,
        challenge_blocks=1,
        response_blocks=response_blocks,
        retry_budget=1,
        flood_count=0,
        flood_parallelism=1,
        flood_challenge_blocks=1,
        affected_decisions=1,
        faulty_replacements=0,
        campaign_tag=tag,
        network_rtt_ms=0,
        keys=keys,
    )

    attack_expected = open_clean_round(attack)
    probe_expected = open_clean_round(probe)
    probe_status = probe.contract.functions.getRoundStatus(probe.round_id).call()
    wait_until_after(w3, int(probe_status[5]))

    latest = latest_block(w3)
    block_gas_limit = int(latest["gasLimit"])
    endpoint = getattr(w3.provider, "endpoint_uri", None)
    if not endpoint:
        raise RuntimeError("HTTP endpoint is required for concurrent broadcast")

    flood_groups = prepare_flood_transactions(
        w3=w3,
        contract=contract,
        round_id=attack.round_id,
        flood_count=flood_count,
        keys=keys,
        gas_price=gas_price,
    )

    coordinator_key = keys["coordinator"]
    coordinator_address = Account.from_key(coordinator_key).address
    honest_nonce = int(w3.eth.get_transaction_count(coordinator_address, "pending"))
    honest_signed, honest_sender = sign_call(
        w3,
        probe.contract.functions.finalize(probe.round_id),
        coordinator_key,
        honest_nonce,
        gas_price,
    )

    # Align just after a new block so the burst and the delayed honest call have
    # nearly one full block period to enter the pool. This reduces accidental
    # dependence on whether setup happened immediately before a block boundary.
    alignment_start = current_block_number(w3)
    alignment_block = wait_for_next_block(w3, alignment_start)
    if alignment_delay_ms > 0:
        time.sleep(alignment_delay_ms / 1000.0)
    head_before = current_block_number(w3)

    pending_flood: list[PendingTx] = []
    flood_broadcast_start_ns = time.perf_counter_ns()
    if flood_groups:
        with ThreadPoolExecutor(
            max_workers=max(1, min(broadcast_parallelism, len(flood_groups)))
        ) as executor:
            futures = [executor.submit(broadcast_group, endpoint, group) for group in flood_groups]
            for future in as_completed(futures):
                pending_flood.extend(future.result())
        pending_flood.sort(key=lambda item: item.ordinal)
    flood_broadcast_ms = (time.perf_counter_ns() - flood_broadcast_start_ns) / 1e6
    head_after_flood_broadcast = current_block_number(w3)

    if honest_delay_ms > 0:
        time.sleep(honest_delay_ms / 1000.0)
    honest_submitted_ns = time.perf_counter_ns()
    honest_hash = w3.eth.send_raw_transaction(honest_signed.raw_transaction)
    honest_pending = PendingTx(-1, "honest_finalize", honest_sender, honest_hash, honest_submitted_ns)

    # Wait for the honest transaction first; this is the latency of interest.
    honest = collect_receipt(w3, honest_pending, receipt_timeout)
    flood_receipts = [collect_receipt(w3, pending, receipt_timeout) for pending in pending_flood]

    if honest["status"] != 1:
        raise RuntimeError(f"honest finalization reverted: {honest['tx_hash']}")
    failed_flood = [row for row in flood_receipts if row["status"] != 1]
    if failed_flood:
        raise RuntimeError(f"{len(failed_flood)} flood transactions reverted")

    challenge_ids: list[int] = []
    for row in flood_receipts:
        events = contract.events.ChallengeOpened().process_receipt(row["receipt"])
        if len(events) != 1:
            raise RuntimeError(f"expected one ChallengeOpened event in {row['tx_hash']}")
        challenge_ids.append(int(events[0]["args"]["challengeId"]))
    attack.challenge_count = len(challenge_ids)

    if challenge_ids:
        result = attack.aggregate_evidence([3], attack_expected)
        if result.verdict != "UPHELD":
            raise RuntimeError(f"unexpected aggregate verdict: {result.verdict}")
        for challenge_id in challenge_ids:
            attack.record_adapter(challenge_id, result)
        calls = [
            contract.functions.resolveChallenge(
                challenge_id,
                OUTCOME["UPHELD"],
                0,
                sha256(b"ContestFL:bounded-contention-upheld" + challenge_id.to_bytes(32, "big")),
                [],
            )
            for challenge_id in challenge_ids
        ]
        for start in range(0, len(calls), resolver_parallelism):
            attack.sender.send_many(
                calls[start : start + resolver_parallelism],
                keys["resolver"],
                "resolve",
                max_inflight_override=resolver_parallelism,
            )

    attack.wait_challenge_window()
    attack.finalize()

    probe_ok = check_finalized(probe, probe_expected)
    attack_ok = check_finalized(attack, attack_expected)
    flood_blocks = [int(row["block_number"]) for row in flood_receipts]
    first_flood_block = min(flood_blocks) if flood_blocks else -1
    last_flood_block = max(flood_blocks) if flood_blocks else -1
    honest_block = int(honest["block_number"])
    honest_block_data = rpc_read(
        lambda: w3.eth.get_block(honest_block),
        label=f"eth_getBlockByNumber({honest_block})",
    )
    honest_block_gas_used = int(honest_block_data["gasUsed"])
    honest_block_gas_limit = int(honest_block_data["gasLimit"])
    return {
        "tag": tag,
        "validators": validators,
        "repetition": repetition,
        "flood_count": flood_count,
        "resolver_parallelism": resolver_parallelism,
        "block_gas_limit": block_gas_limit,
        "gas_price": gas_price,
        "honest_delay_ms_configured": honest_delay_ms,
        "alignment_delay_ms_configured": alignment_delay_ms,
        "broadcast_parallelism": broadcast_parallelism,
        "alignment_block": alignment_block,
        "head_before_broadcast": head_before,
        "head_after_flood_broadcast": head_after_flood_broadcast,
        "flood_broadcast_ms": flood_broadcast_ms,
        "honest_block": honest_block,
        "honest_block_offset": honest_block - head_before,
        "honest_blocks_after_first_flood": honest_block - first_flood_block if first_flood_block >= 0 else 0,
        "honest_latency_ms": float(honest["latency_ms"]),
        "honest_gas_used": int(honest["gas_used"]),
        "honest_status": int(honest["status"]),
        "honest_block_gas_used": honest_block_gas_used,
        "honest_block_gas_limit": honest_block_gas_limit,
        "honest_block_utilization": honest_block_gas_used / honest_block_gas_limit,
        "first_flood_block": first_flood_block,
        "last_flood_block": last_flood_block,
        "flood_block_span": (last_flood_block - first_flood_block + 1) if flood_blocks else 0,
        "flood_gas_total": sum(int(row["gas_used"]) for row in flood_receipts),
        "flood_calldata_total": sum(int(row["calldata_bytes"]) for row in flood_receipts),
        "flood_in_honest_block": sum(1 for block in flood_blocks if block == honest_block),
        "probe_finalized": probe_ok,
        "attack_finalized": attack_ok,
        "invariant_ok": probe_ok and attack_ok,
        "error": "",
    }


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((int(row["block_gas_limit"]), int(row["flood_count"])), []).append(row)
    output: list[dict[str, Any]] = []
    for (gas_limit, flood_count), group in sorted(groups.items()):
        latencies = [float(row["honest_latency_ms"]) for row in group]
        offsets = [float(row["honest_block_offset"]) for row in group]
        after_first = [float(row["honest_blocks_after_first_flood"]) for row in group]
        flood_spans = [float(row["flood_block_span"]) for row in group]
        block_utilization = [float(row["honest_block_utilization"]) for row in group]
        broadcast_times = [float(row["flood_broadcast_ms"]) for row in group]
        output.append({
            "block_gas_limit": gas_limit,
            "flood_count": flood_count,
            "runs": len(group),
            "success_rate": sum(bool(row["invariant_ok"]) for row in group) / len(group),
            "honest_latency_ms_median": statistics.median(latencies),
            "honest_latency_ms_p95": percentile(latencies, 0.95),
            "honest_block_offset_median": statistics.median(offsets),
            "honest_block_offset_p95": percentile(offsets, 0.95),
            "honest_blocks_after_first_flood_median": statistics.median(after_first),
            "flood_block_span_median": statistics.median(flood_spans),
            "flood_gas_total_median": statistics.median(float(row["flood_gas_total"]) for row in group),
            "flood_in_honest_block_median": statistics.median(float(row["flood_in_honest_block"]) for row in group),
            "honest_block_utilization_median": statistics.median(block_utilization),
            "flood_broadcast_ms_median": statistics.median(broadcast_times),
        })
    return output


def write_report(path: Path, summary: list[dict[str, Any]]) -> None:
    lines = [
        "# Bounded block-gas contention",
        "",
        "A valid finalization transaction for an independent clean round is submitted after a burst of unsupported aggregate challenges has entered the transaction pool. All transactions use the same gas price. The reported delay is therefore an application-level inclusion-contention measurement under the configured Besu/QBFT block gas limit, not a proof of denial-of-service resistance.",
        "",
        "| Block gas limit | Flood | Runs | Success | Honest latency median | p95 | Honest block offset | Honest-block gas use | Flood span |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            f"| {int(row['block_gas_limit']):,} | {int(row['flood_count'])} | {int(row['runs'])} | "
            f"{100*float(row['success_rate']):.0f}% | {float(row['honest_latency_ms_median']):.1f} ms | "
            f"{float(row['honest_latency_ms_p95']):.1f} ms | {float(row['honest_block_offset_median']):.1f} | "
            f"{100*float(row['honest_block_utilization_median']):.1f}% | {float(row['flood_block_span_median']):.1f} |"
        )
    lines += [
        "",
        "Interpretation boundary: the experiment uses a permissioned single-host testbed and does not model malicious validators, network saturation, transaction censorship, or monetary bonds. It isolates whether admitted challenge transactions consume enough bounded block capacity to delay a simultaneously valid protocol transaction.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def failure_row(
    *,
    args: argparse.Namespace,
    repetition: int,
    flood_count: int,
    block_gas_limit: int,
    exc: Exception,
) -> dict[str, Any]:
    """Build an error row without issuing another RPC request.

    The previous implementation queried ``latest`` while handling an RPC failure,
    which could mask the original exception and terminate the entire campaign.
    """
    return {
        "tag": args.tag,
        "validators": args.validators,
        "repetition": repetition,
        "flood_count": flood_count,
        "resolver_parallelism": args.resolver_parallelism,
        "block_gas_limit": block_gas_limit,
        "gas_price": args.gas_price,
        "honest_delay_ms_configured": args.honest_delay_ms,
        "alignment_delay_ms_configured": args.alignment_delay_ms,
        "broadcast_parallelism": args.broadcast_parallelism,
        "alignment_block": -1,
        "head_before_broadcast": -1,
        "head_after_flood_broadcast": -1,
        "flood_broadcast_ms": math.nan,
        "honest_block": -1,
        "honest_block_offset": -1,
        "honest_blocks_after_first_flood": -1,
        "honest_latency_ms": math.nan,
        "honest_gas_used": 0,
        "honest_status": 0,
        "honest_block_gas_used": 0,
        "honest_block_gas_limit": block_gas_limit,
        "honest_block_utilization": math.nan,
        "first_flood_block": -1,
        "last_flood_block": -1,
        "flood_block_span": 0,
        "flood_gas_total": 0,
        "flood_calldata_total": 0,
        "flood_in_honest_block": 0,
        "probe_finalized": False,
        "attack_finalized": False,
        "invariant_ok": False,
        "error": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validators", type=int, default=4)
    parser.add_argument("--flood-counts", default="0,10,25,50,100")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--resolver-parallelism", type=int, default=20)
    parser.add_argument("--challenge-blocks", type=int, default=40)
    parser.add_argument("--response-blocks", type=int, default=120)
    parser.add_argument("--honest-delay-ms", type=float, default=100.0)
    parser.add_argument("--alignment-delay-ms", type=float, default=50.0)
    parser.add_argument("--broadcast-parallelism", type=int, default=64)
    parser.add_argument("--gas-price", type=int, default=0)
    parser.add_argument("--receipt-timeout", type=int, default=300)
    parser.add_argument("--rpc", default=os.getenv("RPC_URL", "http://node1:8545"))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tag", default="bounded_gas_contention")
    parser.add_argument("--seed", type=int, default=20260806)
    args = parser.parse_args()

    if args.rounds <= 0 or args.warmup < 0:
        raise SystemExit("--rounds must be positive and --warmup non-negative")
    if args.resolver_parallelism <= 0:
        raise SystemExit("--resolver-parallelism must be positive")
    if args.challenge_blocks <= 0 or args.response_blocks <= 0:
        raise SystemExit("challenge/response blocks must be positive")
    if args.honest_delay_ms < 0 or args.alignment_delay_ms < 0:
        raise SystemExit("honest/alignment delays must be non-negative")
    if args.broadcast_parallelism <= 0:
        raise SystemExit("--broadcast-parallelism must be positive")

    flood_counts = parse_ints(args.flood_counts)
    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 60}))
    # Besu/QBFT encodes validator metadata and seals in block ``extraData``.
    # web3.py otherwise applies the Ethereum 32-byte validation rule and raises
    # ExtraDataLengthError before returning any block.  The PoA compatibility
    # middleware must be the innermost response middleware (layer 0).
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    try:
        startup_block = latest_block(w3, attempts=12)
        startup_chain_id = int(rpc_read(lambda: w3.eth.chain_id, label="eth_chainId", attempts=12))
        startup_client_version = str(
            rpc_read(lambda: w3.client_version, label="web3_clientVersion", attempts=12)
        )
    except Exception as exc:
        raise RuntimeError(f"RPC initialization failed: {args.rpc}: {type(exc).__name__}: {exc}") from exc
    startup_block_gas_limit = int(startup_block["gasLimit"])
    contract, logging_contract, evidence_contract, deployment = load_contracts(w3)
    keys = account_keys()

    raw: list[dict[str, Any]] = []
    base_round_id = int(time.time_ns() // 1_000_000) * 10_000
    ordinal = 0
    for flood_count in flood_counts:
        for repetition in range(-args.warmup, args.rounds):
            ordinal += 1
            round_id = base_round_id + ordinal * 10
            started = time.perf_counter_ns()
            try:
                row = execute_one(
                    w3=w3,
                    contract=contract,
                    logging_contract=logging_contract,
                    evidence_contract=evidence_contract,
                    keys=keys,
                    validators=args.validators,
                    round_id=round_id,
                    repetition=repetition,
                    flood_count=flood_count,
                    resolver_parallelism=args.resolver_parallelism,
                    challenge_blocks=args.challenge_blocks,
                    response_blocks=args.response_blocks,
                    honest_delay_ms=args.honest_delay_ms,
                    alignment_delay_ms=args.alignment_delay_ms,
                    broadcast_parallelism=args.broadcast_parallelism,
                    gas_price=args.gas_price,
                    receipt_timeout=args.receipt_timeout,
                    seed=args.seed,
                    tag=args.tag,
                )
            except Exception as exc:
                row = failure_row(
                    args=args,
                    repetition=repetition,
                    flood_count=flood_count,
                    block_gas_limit=startup_block_gas_limit,
                    exc=exc,
                )
            elapsed_ms = (time.perf_counter_ns() - started) / 1e6
            print(json.dumps({
                "flood": flood_count,
                "repetition": repetition,
                "elapsedMs": round(elapsed_ms, 1),
                "invariantOk": bool(row["invariant_ok"]),
                "honestBlockOffset": row["honest_block_offset"],
                "error": bool(row["error"]),
            }), flush=True)
            if repetition >= 0:
                raw.append(row)

    failures = [row for row in raw if not bool(row["invariant_ok"])]
    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "bounded_gas_contention_raw.csv", raw)
    summary = summarize(raw)
    write_csv(output_dir / "bounded_gas_contention_summary.csv", summary)
    write_report(output_dir / "BOUNDED_GAS_CONTENTION_REPORT.md", summary)
    metadata = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tag": args.tag,
        "validators": args.validators,
        "floodCounts": flood_counts,
        "rounds": args.rounds,
        "warmup": args.warmup,
        "resolverParallelism": args.resolver_parallelism,
        "challengeBlocks": args.challenge_blocks,
        "responseBlocks": args.response_blocks,
        "honestDelayMs": args.honest_delay_ms,
        "alignmentDelayMs": args.alignment_delay_ms,
        "broadcastParallelism": args.broadcast_parallelism,
        "gasPrice": args.gas_price,
        "blockGasLimit": startup_block_gas_limit,
        "chainId": startup_chain_id,
        "clientVersion": startup_client_version,
        "deployment": deployment,
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "scope": "Application-level transaction inclusion under bounded block gas. The flood uses unique unsupported aggregate challenges and the honest transaction finalizes an independent clean round.",
        "limitations": "Single-host permissioned QBFT; no malicious validators, network saturation, censorship, or monetary bond evaluation.",
    }
    (output_dir / "bounded_gas_contention_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"outputDir": str(output_dir), "rows": len(raw), "failures": len(failures)}, indent=2))
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
