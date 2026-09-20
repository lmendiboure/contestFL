#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

from model import Phase, RoundModel

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FuzzResult:
    sequence: int
    seed: int
    retry_budget: int
    steps: int
    terminal: str
    retries_used: int
    epoch: int
    challenges_opened: int
    revisions: int
    forbidden_finalize_rejected: int
    invariant_ok: bool
    error: str = ""


def assert_invariants(model: RoundModel) -> None:
    assert 0 <= model.retries_used <= model.retry_budget
    assert model.open_challenges >= 0
    if model.phase == Phase.FINALIZED:
        assert model.open_challenges == 0
        assert model.state_published
        assert not model.needs_replacement
    if model.phase == Phase.READY:
        assert model.terminal_checkpoint
        assert model.state_published
        assert not model.needs_replacement
    if model.needs_replacement and model.phase not in (Phase.FINALIZED, Phase.ABORTED):
        assert model.phase == Phase.RESOLVING
        assert not model.state_published
    if model.phase == Phase.ABORTED:
        assert not model.history or model.history[-1] == "aborted"


def rejected_finalize(model: RoundModel) -> bool:
    try:
        model.finalize()
    except AssertionError:
        return True
    return False


def run_sequence(index: int, seed: int, max_steps: int) -> FuzzResult:
    rng = random.Random(seed)
    budget = rng.randint(0, 3)
    model = RoundModel(retry_budget=budget)
    opened = 0
    revisions = 0
    rejected = 0
    error = ""
    try:
        model.publish_initial()
        for step in range(max_steps):
            assert_invariants(model)
            if model.phase in (Phase.FINALIZED, Phase.ABORTED):
                break
            if model.phase == Phase.CHALLENGE:
                # Exercise premature-finalization rejection whenever work is open.
                if model.open_challenges > 0 and rejected_finalize(model):
                    rejected += 1
                if model.open_challenges == 0:
                    action = rng.choices(
                        ["challenge", "finalize", "abort"], weights=[0.72, 0.23, 0.05], k=1
                    )[0]
                    if action == "finalize":
                        model.finalize()
                        continue
                    if action == "abort":
                        model.abort()
                        continue
                    count = rng.randint(1, 4)
                    for _ in range(count):
                        model.challenge()
                        opened += 1
                # Resolve a snapshot batch. A revised ancestor may moot descendants.
                if model.open_challenges:
                    revise = rng.random() < 0.35
                    moot = rng.randint(0, model.open_challenges - 1) if revise else 0
                    model.resolve(revised=revise, moot=moot)
                    revisions += int(revise)
                    while model.phase == Phase.CHALLENGE and model.open_challenges:
                        model.resolve(revised=False)
            elif model.phase == Phase.RESOLVING:
                assert rejected_finalize(model)
                rejected += 1
                if model.open_challenges:
                    # Remaining snapshot challenges are deterministically settled.
                    model.resolve(revised=False)
                    continue
                choices = ["fallback", "abort"]
                if model.retries_used < model.retry_budget:
                    choices.append("replacement")
                action = rng.choice(choices)
                if action == "replacement":
                    model.coordinator_replacement()
                elif action == "fallback":
                    model.fallback()
                else:
                    model.abort()
            elif model.phase == Phase.READY:
                model.finalize()
            assert_invariants(model)
        if model.phase not in (Phase.FINALIZED, Phase.ABORTED):
            model.abort()
        assert_invariants(model)
        invariant_ok = True
    except Exception as exc:  # noqa: BLE001 - persisted for reproducibility
        invariant_ok = False
        error = f"{type(exc).__name__}: {exc}; history={model.history}"
    return FuzzResult(
        sequence=index,
        seed=seed,
        retry_budget=budget,
        steps=len(model.history),
        terminal=model.phase.name,
        retries_used=model.retries_used,
        epoch=model.epoch,
        challenges_opened=opened,
        revisions=revisions,
        forbidden_finalize_rejected=rejected,
        invariant_ok=invariant_ok,
        error=error,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Randomized model-based ContestFL invariant testing")
    parser.add_argument("--sequences", type=int, default=10_000)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    rows = [run_sequence(i, args.seed + i * 7_919, args.max_steps) for i in range(args.sequences)]
    output = ROOT / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    raw_path = output / "state_machine_fuzz.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(vars(rows[0])))
        writer.writeheader()
        writer.writerows(vars(row) for row in rows)

    failures = [row for row in rows if not row.invariant_ok]
    summary = {
        "sequences": len(rows),
        "failures": len(failures),
        "finalized": sum(row.terminal == "FINALIZED" for row in rows),
        "aborted": sum(row.terminal == "ABORTED" for row in rows),
        "revisions": sum(row.revisions for row in rows),
        "challenges": sum(row.challenges_opened for row in rows),
        "forbiddenFinalizeAttemptsRejected": sum(row.forbidden_finalize_rejected for row in rows),
        "elapsedSeconds": time.perf_counter() - started,
        "seed": args.seed,
        "maxSteps": args.max_steps,
    }
    (output / "state_machine_fuzz_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
