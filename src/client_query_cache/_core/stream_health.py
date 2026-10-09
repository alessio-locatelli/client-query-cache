from __future__ import annotations

import enum
import random
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from client_query_cache._types import NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_BASE_DELAY_SECONDS = 0.1
DEFAULT_MAX_DELAY_SECONDS = 30.0
DEFAULT_MULTIPLIER = 2.0


class StreamHealth(enum.Enum):
    STARTING = "starting"
    CONNECTING = "connecting"
    HEALTHY = "healthy"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


class StreamHealthStatus(StrEnum):
    NOT_STARTED = "not_started"
    CONNECTING = "connecting"
    HEALTHY = "healthy"
    RECONNECTING = "reconnecting"
    STARTUP_FAILED = "startup_failed"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class StreamHealthSnapshot:
    requested_database_name: str
    status: StreamHealthStatus


_PUBLIC_HEALTH = {
    StreamHealth.STARTING: StreamHealthStatus.CONNECTING,
    StreamHealth.CONNECTING: StreamHealthStatus.CONNECTING,
    StreamHealth.HEALTHY: StreamHealthStatus.HEALTHY,
    StreamHealth.RECONNECTING: StreamHealthStatus.RECONNECTING,
    StreamHealth.CLOSED: StreamHealthStatus.CLOSED,
}


def public_stream_health(health: StreamHealth) -> StreamHealthStatus:
    return _PUBLIC_HEALTH[health]


class StreamHealthRegistry:
    """Inspect startup and supervision without acquiring the I/O coordinator lock."""

    __slots__ = ("_closed", "_lock", "_states")

    def __init__(self) -> None:
        self._closed = False
        self._lock = threading.Lock()
        self._states: dict[
            str, StreamHealthStatus | Callable[[], StreamHealthStatus]
        ] = {}

    def record_connecting(self, database_name: str) -> None:
        with self._lock:
            self._states[database_name] = StreamHealthStatus.CONNECTING

    def record_starting(
        self, database_name: str, health: Callable[[], StreamHealthStatus]
    ) -> None:
        with self._lock:
            self._states[database_name] = health

    def record_startup_failure(self, database_name: str) -> None:
        with self._lock:
            self._states[database_name] = StreamHealthStatus.STARTUP_FAILED

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._states.clear()

    def snapshot(self, database_name: str) -> StreamHealthSnapshot:
        with self._lock:
            if self._closed:
                return StreamHealthSnapshot(database_name, StreamHealthStatus.CLOSED)
            try:
                state = self._states[database_name]
            except KeyError:
                state = StreamHealthStatus.NOT_STARTED
        status = state() if callable(state) else state
        return StreamHealthSnapshot(database_name, status)


@dataclass(slots=True)
class RetryBackoff:
    base_seconds: float = DEFAULT_BASE_DELAY_SECONDS
    max_seconds: float = DEFAULT_MAX_DELAY_SECONDS
    multiplier: float = DEFAULT_MULTIPLIER
    _attempt: NonNegativeInt = field(default=0, init=False)
    _saturated: bool = field(default=False, init=False)

    def reset(self) -> None:
        self._attempt = 0
        self._saturated = False

    def next_delay(
        self, random_uniform: Callable[[float, float], float] = random.uniform
    ) -> float:
        if self._saturated:
            return random_uniform(0.0, self.max_seconds)
        cap = self.base_seconds * (self.multiplier**self._attempt)
        if cap >= self.max_seconds:
            self._saturated = True
            cap = self.max_seconds
        else:
            self._attempt += 1
        return random_uniform(0.0, cap)
