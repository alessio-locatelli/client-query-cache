from __future__ import annotations

import threading
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

from client_query_cache._types import NonNegativeFloat, NonNegativeInt, PositiveFloat

if TYPE_CHECKING:
    from collections.abc import Callable

from pymongo.monitoring import (
    CommandFailedEvent,
    CommandListener,
    CommandStartedEvent,
    CommandSucceededEvent,
)


@dataclass(frozen=True, slots=True)
class AwaitCommand:
    started_seconds: NonNegativeFloat  # Monotonic.
    completed_seconds: NonNegativeFloat | None  # Monotonic; None means in flight.
    max_time_ms: NonNegativeInt | None  # None means the option was absent.
    failed: bool


class AwaitCommandListener(CommandListener):
    def __init__(self) -> None:
        self._lock = threading.Condition()
        self._version = 0
        self._on_next_start: Callable[[], None] | None = None
        self._commands: list[AwaitCommand] = []
        self._in_flight: dict[int, NonNegativeInt] = {}

    def started(self, event: CommandStartedEvent) -> None:
        if event.command_name != "getMore":
            return
        try:
            requested: NonNegativeInt | None = event.command["maxTimeMS"]
        except KeyError:
            requested = None
        with self._lock:
            callback = self._on_next_start
            self._on_next_start = None
        if callback is not None:
            callback()
        with self._lock:
            self._in_flight[event.request_id] = len(self._commands)
            self._commands.append(
                AwaitCommand(monotonic(), None, requested, failed=False)
            )
            self._version += 1
            self._lock.notify_all()

    def succeeded(self, event: CommandSucceededEvent) -> None:
        if event.command_name == "getMore":
            self._complete(event.request_id, failed=False)

    def failed(self, event: CommandFailedEvent) -> None:
        if event.command_name == "getMore":
            self._complete(event.request_id, failed=True)

    def _complete(self, request_id: int, *, failed: bool) -> None:
        with self._lock:
            index = self._in_flight.pop(request_id)
            command = self._commands[index]
            self._commands[index] = AwaitCommand(
                command.started_seconds, monotonic(), command.max_time_ms, failed
            )
            self._version += 1
            self._lock.notify_all()

    def snapshot(self) -> tuple[AwaitCommand, ...]:
        with self._lock:
            return tuple(self._commands)

    @property
    def version(self) -> NonNegativeInt:
        with self._lock:
            return self._version

    def wait_for_change(self, version: NonNegativeInt, seconds: PositiveFloat) -> None:
        with self._lock:
            if not self._lock.wait_for(lambda: self._version != version, seconds):
                raise TimeoutError("no getMore boundary observed within the window")

    def at_next_start(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._on_next_start = callback
