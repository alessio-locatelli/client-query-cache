from __future__ import annotations

import random
from dataclasses import dataclass, field
from time import monotonic

from client_query_cache._core.stream_health import RetryBackoff


def _startup_jitter(_low: float, cap: float) -> float:
    return random.uniform(cap / 2, cap)


@dataclass(slots=True)
class StartupRetry:
    deadline: float = 0.0  # Zero permits the first attempt.
    backoff: RetryBackoff = field(default_factory=RetryBackoff)

    def ready(self) -> bool:
        return monotonic() >= self.deadline

    def failed(self) -> None:
        self.deadline = monotonic() + self.backoff.next_delay(_startup_jitter)


@dataclass(slots=True)
class StreamActivation[Supervisor, Completion]:
    supervisor: Supervisor
    completion: Completion
    pending: bool = True
    retry: StartupRetry = field(default_factory=StartupRetry)
