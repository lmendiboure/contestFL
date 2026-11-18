#!/usr/bin/env python3
"""Bounded, regenerable exploration of a two-client *dynamic* dependency DAG.

This deliberately explicit abstraction models A_i -> I_i -> G, and A_i -> G;
I_i exists iff admission i is true. It checks reject-to-admit activation,
admit-to-reject removal, frozen concurrent challenges, shared vs per-level
non-renewable retry budgets, renewed windows and single certified fallback.

Assumptions: truthful evidence verdicts, complete challenge coverage when
requested, atomic frozen-snapshot resolution, an authentic fallback, fair
ledger progress. It is NOT TLA+ model checking, EVM conformance, proof of
cryptographic soundness or a proof for arbitrary DAGs.
"""
from __future__ import annotations

import argparse
from collections import deque, Counter
from dataclasses import dataclass, replace
from itertools import product
import json
from pathlib import Path

N = 2
LEVEL = {'A': 0, 'I': 1, 'G': 2}


@dataclass(frozen=True)
class Truth:
    admission: tuple[bool, bool]
    inclusion: tuple[bool, bool]  # meaningful only if admitted


@dataclass(frozen=True)
class State:
    phase: str
    admission: tuple[bool, bool]
    inclusion: tuple[bool | None, bool | None]
    av: tuple[int, int]
    iv: tuple[int, int]
    ib: tuple[int | None, int | None]  # INCLUDE parent ADMIT version
    gv: int
    gb: tuple[tuple[int, int, int], ...]  # current AGG -> (client, AV, IV)
    aggregate_correct: bool
    ever_included: tuple[bool, bool]
    activated: int
    windows: int
    shared_used: int
    level_used: tuple[int, int, int]
    pending_levels: tuple[int, ...] = ()
    challenge_batch: tuple[str, ...] = ()
    concurrent_seen: bool = False
    fallback_used: bool = False


def binding(admission, av, iv):
    return tuple((i, av[i], iv[i]) for i in range(N) if admission[i])


def initial_states():
    for adm in product((False, True), repeat=N):
        incl_options = [(False, True) if a else (None,) for a in adm]
        for incl in product(*incl_options):
            for correct in (False, True):
                iv = tuple(1 if x is not None else 0 for x in incl)
                yield State('WINDOW', adm, incl, (1, 1), iv,
                            tuple(1 if a else None for a in adm), 1,
                            binding(adm, (1, 1), iv), correct,
                            adm, 0, 1, 0, (0, 0, 0))


def truths():
    for adm in product((False, True), repeat=N):
        for inc in product((False, True), repeat=N):
            yield Truth(adm, inc)


def active(s):
    return tuple([f'A{i}' for i in range(N)] +
                 [f'I{i}' for i in range(N) if s.admission[i]] + ['G'])


def invalid(s, truth):
    wrong = set()
    for i in range(N):
        if s.admission[i] != truth.admission[i]:
            wrong.add(f'A{i}')
        if s.admission[i] and (not truth.admission[i] or
                               s.inclusion[i] != truth.inclusion[i]):
            wrong.add(f'I{i}')
    if not s.aggregate_correct:
        wrong.add('G')
    return tuple(sorted(wrong))


def published_binding_consistent(s):
    if s.phase not in ('WINDOW', 'READY', 'FINALIZED'):
        return True  # a revision must not expose the stale roots as finalizable
    return all((s.inclusion[i] is not None) == s.admission[i] and
               s.ib[i] == (s.av[i] if s.admission[i] else None)
               for i in range(N)) and s.gb == binding(s.admission, s.av, s.iv)


def challenge_batches(s, truth, coverage=True):
    wrong = set(invalid(s, truth))
    if not wrong:
        return ()
    # C1 enforces inclusion of *all* currently invalid keys; optionally
    # admit one supported/unsupported challenge on a valid target as well.
    rest = [k for k in active(s) if k not in wrong]
    result = [tuple(sorted(wrong))]
    for extra in rest:
        result.append(tuple(sorted(wrong | {extra})))
    return tuple(dict.fromkeys(result))


def resolve_snapshot(s, truth):
    assert s.phase == 'SNAPSHOT' and s.challenge_batch
    # The entire batch is frozen before any correction; applying a canonical
    # topological order yields the same outcome for either transaction order.
    batch = set(s.challenge_batch)
    wrong = set(invalid(s, truth))
    adm = list(s.admission)
    inc = list(s.inclusion)
    av = list(s.av)
    iv = list(s.iv)
    changed = set()
    ancestor_revised = False
    for i in range(N):
        if f'A{i}' in batch and f'A{i}' in wrong:
            adm[i] = truth.admission[i]
            av[i] += 1
            if not adm[i]:
                inc[i] = None  # existing inclusion key is deactivated
            else:
                inc[i] = False  # newly activated key must face new scrutiny
                # New INCLUDE is not published until the replacement epoch;
                # the first publication gets version one.
                if not s.admission[i]:
                    iv[i] = 0
            changed.add(0)
            ancestor_revised = True
        elif f'I{i}' in batch and f'I{i}' in wrong:
            inc[i] = truth.inclusion[i]
            iv[i] += 1
            changed.add(1)
            ancestor_revised = True
    # A challenged AGGREGATE is MOOT after a changed ancestor, otherwise it
    # is revised if its verdict is invalid. Either way, the aggregate must
    # be republished and must bind the new active dependency set.
    agg = s.aggregate_correct
    if 'G' in batch and 'G' in wrong and not ancestor_revised:
        agg = True
        changed.add(2)
    if ancestor_revised:
        agg = False
    if not changed:
        return replace(s, phase='WINDOW', challenge_batch=())
    return replace(s, phase='REPLACE', admission=tuple(adm), inclusion=tuple(inc),
                   av=tuple(av), iv=tuple(iv), aggregate_correct=agg,
                   pending_levels=tuple(sorted(changed)), challenge_batch=(),
                   concurrent_seen=s.concurrent_seen or ('G' in batch and ancestor_revised) or any(f'I{i}' in batch and f'A{i}' in batch and f'A{i}' in wrong for i in range(N)))


def budget_available(s, mode, shared_budget, level_budgets):
    if mode == 'shared':
        return s.shared_used < shared_budget
    return all(s.level_used[level] < level_budgets[level] for level in s.pending_levels)


def republish(s, mode, truth, shared_budget, level_budgets):
    assert s.phase == 'REPLACE'
    if not budget_available(s, mode, shared_budget, level_budgets):
        return ()
    # An adversarial coordinator may publish either valid or faulty inclusions
    # and either a correct or bad aggregate; C1 will catch bad publications.
    options = [(False, True) if a else (None,) for a in s.admission]
    states = []
    for new_incl in product(*options):
        for new_agg_correct in (False, True):
            iv = tuple((1 if s.iv[i] == 0 else s.iv[i] + int(s.inclusion[i] != new_incl[i]))
                       if new_incl[i] is not None else s.iv[i] for i in range(N))
            activated = sum(s.admission[i] and not s.ever_included[i] for i in range(N))
            ever = tuple(s.ever_included[i] or s.admission[i] for i in range(N))
            used = list(s.level_used)
            if mode == 'levels':
                for j in s.pending_levels:
                    used[j] += 1
            states.append(replace(s, phase='WINDOW', inclusion=new_incl,
                                  iv=iv, ib=tuple(s.av[i] if a else None for i, a in enumerate(s.admission)),
                                  gv=s.gv + 1, gb=binding(s.admission, s.av, iv),
                                  aggregate_correct=new_agg_correct,
                                  ever_included=ever, activated=s.activated + activated,
                                  windows=s.windows + 1,
                                  shared_used=s.shared_used + (1 if mode == 'shared' else 0),
                                  level_used=tuple(used), pending_levels=()))
    return tuple(states)


def certified_fallback(s, truth):
    assert s.phase == 'REPLACE'
    adm = truth.admission
    inc = tuple(truth.inclusion[i] if a else None for i, a in enumerate(adm))
    av = tuple(s.av[i] + int(s.admission[i] != adm[i]) for i in range(N))
    iv = tuple(max(1, s.iv[i]) if a else s.iv[i] for i, a in enumerate(adm))
    return replace(s, phase='READY', admission=adm, inclusion=inc,
                   av=av, iv=iv, ib=tuple(av[i] if a else None for i, a in enumerate(adm)),
                   gb=binding(adm, av, iv), gv=s.gv + 1, aggregate_correct=True,
                   fallback_used=True, pending_levels=(), challenge_batch=())


def successors(s, truth, mode, shared_budget, level_budgets, coverage=True):
    if s.phase == 'WINDOW':
        wrong = invalid(s, truth)
        if not wrong or not coverage:
            yield replace(s, phase='FINALIZED'), 'finalize'
        for batch in challenge_batches(s, truth, coverage):
            yield replace(s, phase='SNAPSHOT', challenge_batch=batch), 'frozen_batch:' + ','.join(batch)
    elif s.phase == 'SNAPSHOT':
        yield resolve_snapshot(s, truth), 'resolve_in_topological_order'
    elif s.phase == 'REPLACE':
        for successor in republish(s, mode, truth, shared_budget, level_budgets):
            yield successor, 'republish'
        yield certified_fallback(s, truth), 'certified_fallback'
        yield replace(s, phase='ABORTED', pending_levels=()), 'safe_abort'
    elif s.phase == 'READY':
        yield replace(s, phase='FINALIZED'), 'finalize_certified'


def explore(mode='shared', shared_budget=2, level_budgets=(1, 1, 1), coverage=True):
    if mode not in ('shared', 'levels'):
        raise ValueError(mode)
    assert shared_budget >= 0 and all(b >= 0 for b in level_budgets)
    total_states = total_edges = terminals = 0
    statistics = Counter()
    example = {}
    for truth in truths():
        for init in initial_states():
            queue = deque([init])
            seen = {init}
            pred = {init: None}
            while queue:
                s = queue.popleft()
                total_states += 1
                if not published_binding_consistent(s):
                    raise AssertionError(('parent-closure', truth, s))
                if s.windows > 1 + (shared_budget if mode == 'shared' else sum(level_budgets)) + s.activated:
                    raise AssertionError(('window-bound', truth, s))
                if mode == 'shared' and s.shared_used > shared_budget:
                    raise AssertionError(('shared-retries', truth, s))
                if mode == 'levels' and any(x > b for x, b in zip(s.level_used, level_budgets)):
                    raise AssertionError(('level-retries', truth, s))
                if s.phase in ('FINALIZED', 'ABORTED'):
                    terminals += 1
                    statistics['terminal_' + s.phase.lower()] += 1
                    if s.phase == 'FINALIZED' and invalid(s, truth):
                        if coverage:
                            raise AssertionError(('invalid-finalized-with-C1', truth, s))
                        statistics['uncovered_invalid_finalized'] += 1
                    if s.fallback_used:
                        statistics['finalized_after_fallback'] += 1
                    if s.concurrent_seen:
                        statistics['concurrent_ancestor_descendant'] += 1
                    if s.activated:
                        statistics['dynamic_activation'] += 1
                    if any(s.ever_included[i] and not s.admission[i] for i in range(N)):
                        statistics['dynamic_deactivation'] += 1
                for child, step in successors(s, truth, mode, shared_budget, level_budgets, coverage):
                    total_edges += 1
                    if child not in seen:
                        seen.add(child)
                        pred[child] = (s, step)
                        queue.append(child)
                        if ('activate' not in example and child.activated and child.phase == 'WINDOW') or (
                                'deactivate' not in example and any(child.ever_included[i] and not child.admission[i] for i in range(N))):
                            key = 'activate' if child.activated and child.phase == 'WINDOW' else 'deactivate'
                            path = []
                            pointer = child
                            while pred[pointer] is not None:
                                parent, action = pred[pointer]
                                path.append(action)
                                pointer = parent
                            example[key] = dict(truth_admission=truth.admission,
                                                initial_admission=init.admission,
                                                actions=list(reversed(path)))
    result = dict(mode=mode, coverage=coverage, shared_budget=shared_budget,
                  level_budgets=list(level_budgets), explored_state_instances=total_states,
                  explored_edges=total_edges, terminals=terminals,
                  observations=dict(statistics), witness_examples=example,
                  scope='two clients, fixed authentic evidence oracle; bounded explicit states, not full-contract verification')
    if coverage:
        for required in ('dynamic_activation', 'dynamic_deactivation', 'concurrent_ancestor_descendant', 'finalized_after_fallback'):
            if not result['observations'].get(required):
                raise AssertionError(('coverage-gap', required))
    else:
        if not result['observations'].get('uncovered_invalid_finalized'):
            raise AssertionError('must demonstrate invalid finalization when C1 is absent')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', default='results/runs/dynamic_dependency_check')
    parser.add_argument('--shared-budget', type=int, default=2)
    parser.add_argument('--level-budgets', default='1,1,1')
    args = parser.parse_args()
    levels = tuple(int(x) for x in args.level_budgets.split(','))
    if len(levels) != 3 or any(x < 0 for x in levels):
        parser.error('three nonnegative level budgets required')
    reports = [explore('shared', args.shared_budget, levels, True),
               explore('levels', args.shared_budget, levels, True),
               explore('shared', args.shared_budget, levels, False)]
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out/'dynamic_dependency_results.json').write_text(json.dumps(reports, indent=2) + '\n')
    print(json.dumps([{k: r[k] for k in ('mode','coverage','explored_state_instances','explored_edges','observations')}
                      for r in reports], indent=2))


if __name__ == '__main__':
    main()
