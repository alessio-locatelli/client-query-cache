from __future__ import annotations

import enum
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_BASE_DELAY_SECONDS = 0.1
DEFAULT_MAX_DELAY_SECONDS = 30.0
DEFAULT_MULTIPLIER = 2.0


class StreamHealth(enum.Enum):
    STARTING = "starting"
    HEALTHY = "healthy"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


@dataclass(slots=True)
class RetryBackoff:
    base_seconds: float = DEFAULT_BASE_DELAY_SECONDS
    max_seconds: float = DEFAULT_MAX_DELAY_SECONDS
    multiplier: float = DEFAULT_MULTIPLIER
    _attempt: int = field(default=0, init=False)

    def reset(self) -> None:
        self._attempt = 0

    def next_delay(
        self, random_uniform: Callable[[float, float], float] = random.uniform
    ) -> float:
        cap = min(
            self.max_seconds, self.base_seconds * (self.multiplier**self._attempt)
        )
        self._attempt += 1
        return random_uniform(0.0, cap)
