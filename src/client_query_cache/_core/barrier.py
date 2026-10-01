from __future__ import annotations

import enum
import math
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from bson import Timestamp
from pymongo.errors import OperationFailure, PyMongoError

from client_query_cache._core.errors import (
    BarrierArgumentError,
    BarrierClosedError,
    BarrierContinuityError,
    BarrierTimeoutError,
    BarrierUnavailableError,
)
from client_query_cache._core.stream_events import CHANGE_STREAM_HISTORY_LOST_CODE

if TYPE_CHECKING:
    from client_query_cache._core.errors import (
        CausalBarrierError,
        StreamStartupError,
    )

MAX_BARRIER_TIMEOUT_SECONDS = threading.TIMEOUT_MAX
MAX_TIMESTAMP_INCREMENT = 2**32 - 1


class BarrierOutcome(enum.Enum):
    COMPLETED = "completed"
    CONTINUITY_LOST = "continuity_lost"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class CausalBoundary:
    operation_time: Timestamp
    owner: object = field(repr=False)


class BoundarySession(Protocol):
    @property
    def client(self) -> object: ...

    @property
    def in_transaction(self) -> bool: ...

    @property
    def operation_time(self) -> Timestamp | None: ...


class BarrierWaiter(Protocol):
    @property
    def target(self) -> str: ...

    def resolve(self, outcome: BarrierOutcome) -> None: ...


class BarrierProgress:
    __slots__ = ("_closed", "_floor", "_frontier", "_waiters")

    def __init__(self) -> None:
        self._frontier: str | None = None
        self._floor: str | None = None
        self._waiters: set[BarrierWaiter] = set()
        self._closed = False

    def register(self, waiter: BarrierWaiter) -> BarrierOutcome | None:
        outcome = self._outcome_for(waiter.target)
        if outcome is None:
            self._waiters.add(waiter)
        return outcome

    def discard(self, waiter: BarrierWaiter) -> None:
        self._waiters.discard(waiter)

    def advance(self, token: str) -> None:
        self._frontier = token
        if self._waiters:
            self._resolve_ready()

    def restart(self, token: str) -> None:
        self._floor = token
        self.advance(token)

    def lose_continuity(self) -> None:
        self._frontier = None
        self._resolve_all(BarrierOutcome.CONTINUITY_LOST)

    def close(self) -> None:
        self._closed = True
        self._resolve_all(BarrierOutcome.CLOSED)

    def _outcome_for(self, target: str) -> BarrierOutcome | None:
        if self._closed:
            return BarrierOutcome.CLOSED
        if self._floor is not None and target < self._floor:
            return BarrierOutcome.CONTINUITY_LOST
        if self._frontier is not None and self._frontier >= target:
            return BarrierOutcome.COMPLETED
        return None

    def _resolve_ready(self) -> None:
        ready = [
            (waiter, outcome)
            for waiter in self._waiters
            if (outcome := self._outcome_for(waiter.target)) is not None
        ]
        for waiter, outcome in ready:
            self._waiters.discard(waiter)
            waiter.resolve(outcome)

    def _resolve_all(self, outcome: BarrierOutcome) -> None:
        waiters = self._waiters
        self._waiters = set()
        for waiter in waiters:
            waiter.resolve(outcome)


def barrier_deadline(timeout: float) -> float:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int | float)
        or not math.isfinite(timeout)
        or not 0 < timeout <= MAX_BARRIER_TIMEOUT_SECONDS
    ):
        message = (
            "timeout must be a finite number of seconds greater than 0 and at most "
            f"{MAX_BARRIER_TIMEOUT_SECONDS}"
        )
        raise BarrierArgumentError(message)
    return time.monotonic() + timeout


def remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BarrierTimeoutError("the barrier deadline expired")
    return remaining


def capture_boundary(
    owner: object, client: object, session: BoundarySession
) -> CausalBoundary:
    if session.client is not client:
        raise BarrierArgumentError("the session belongs to a different client")
    if session.in_transaction:
        message = "the session is inside an open transaction; commit it first"
        raise BarrierArgumentError(message)
    operation_time = session.operation_time
    if operation_time is None:
        raise BarrierArgumentError("the session has not completed any operation")
    return CausalBoundary(operation_time, owner)


def require_owned_boundary(owner: object, boundary: CausalBoundary) -> None:
    if not isinstance(boundary, CausalBoundary) or boundary.owner is not owner:
        message = "the boundary was not captured by this manager's causal_boundary()"
        raise BarrierArgumentError(message)


def target_start_time(operation_time: Timestamp) -> Timestamp:
    if operation_time.inc == MAX_TIMESTAMP_INCREMENT:
        return Timestamp(operation_time.time + 1, 0)
    return Timestamp(operation_time.time, operation_time.inc + 1)


def raise_for_outcome(outcome: BarrierOutcome) -> None:
    if outcome is BarrierOutcome.CONTINUITY_LOST:
        message = (
            "the change stream lost the history needed to prove the boundary; "
            "read from the database instead"
        )
        raise BarrierContinuityError(message)
    if outcome is BarrierOutcome.CLOSED:
        raise BarrierClosedError("the manager was closed")


def barrier_error_for_driver_failure(error: PyMongoError) -> CausalBarrierError:
    if error.timeout:
        return BarrierTimeoutError("the barrier deadline expired")
    if (
        isinstance(error, OperationFailure)
        and error.code == CHANGE_STREAM_HISTORY_LOST_CODE
    ):
        message = "the boundary is older than the server's change-stream history"
        return BarrierContinuityError(message)
    return BarrierUnavailableError("the barrier could not reach the database")


def barrier_error_for_startup_failure(error: StreamStartupError) -> CausalBarrierError:
    cause = error.__cause__
    if isinstance(cause, PyMongoError) and cause.timeout:
        return BarrierTimeoutError("the barrier deadline expired during activation")
    return BarrierUnavailableError(str(error))
