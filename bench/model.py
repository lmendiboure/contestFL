from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List


class Phase(IntEnum):
    NONE = 0
    SUBMIT = 1
    CHALLENGE = 2
    RESOLVING = 3
    READY = 4
    FINALIZED = 5
    ABORTED = 6


@dataclass
class RoundModel:
    retry_budget: int = 1
    retries_used: int = 0
    epoch: int = 0
    phase: Phase = Phase.SUBMIT
    open_challenges: int = 0
    state_published: bool = False
    terminal_checkpoint: bool = False
    needs_replacement: bool = False
    decisions: Dict[bytes, int] = field(default_factory=dict)
    history: List[str] = field(default_factory=list)

    def publish_initial(self) -> None:
        assert self.phase == Phase.SUBMIT
        self.state_published = True
        self.phase = Phase.CHALLENGE
        self.history.append("initial")

    def challenge(self) -> None:
        assert self.phase == Phase.CHALLENGE
        self.open_challenges += 1
        self.history.append("challenge")

    def resolve(self, revised: bool, moot: int = 0) -> None:
        assert self.open_challenges >= 1 + moot
        self.open_challenges -= 1 + moot
        if revised:
            self.phase = Phase.RESOLVING
            self.state_published = False
            self.needs_replacement = True
        self.history.append("revised" if revised else "upheld")

    def coordinator_replacement(self) -> None:
        assert self.phase == Phase.RESOLVING and self.needs_replacement
        assert self.open_challenges == 0
        assert self.retries_used < self.retry_budget
        self.retries_used += 1
        self.epoch += 1
        self.state_published = True
        self.needs_replacement = False
        self.phase = Phase.CHALLENGE
        self.history.append("coordinator-replacement")

    def fallback(self) -> None:
        assert self.phase == Phase.RESOLVING and self.needs_replacement
        assert self.open_challenges == 0
        self.epoch += 1
        self.state_published = True
        self.terminal_checkpoint = True
        self.needs_replacement = False
        self.phase = Phase.READY
        self.history.append("fallback")

    def finalize(self) -> None:
        assert self.open_challenges == 0
        assert self.state_published and not self.needs_replacement
        assert self.phase in (Phase.CHALLENGE, Phase.READY)
        self.phase = Phase.FINALIZED
        self.history.append("finalized")

    def abort(self) -> None:
        assert self.phase not in (Phase.FINALIZED, Phase.ABORTED)
        self.phase = Phase.ABORTED
        self.history.append("aborted")
