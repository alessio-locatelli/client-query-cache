from __future__ import annotations

import math
import time
from types import SimpleNamespace

import pytest
from bson import Timestamp
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    rule,
    run_state_machine_as_test,
)
from pymongo.errors import (
    ConnectionFailure,
    ExecutionTimeout,
    NetworkTimeout,
    OperationFailure,
)

from client_query_cache._core.barrier import (
    MAX_BARRIER_TIMEOUT_SECONDS,
    MAX_TIMESTAMP_INCREMENT,
    BarrierOutcome,
    BarrierProgress,
    CausalBoundary,
    barrier_deadline,
    barrier_error_for_driver_failure,
    barrier_error_for_startup_failure,
    capture_boundary,
    raise_for_outcome,
    remaining_seconds,
    require_owned_boundary,
    target_start_time,
)
from client_query_cache._core.errors import (
    BarrierArgumentError,
    BarrierClosedError,
    BarrierContinuityError,
    BarrierTimeoutError,
    BarrierUnavailableError,
    CacheClosedError,
    StreamStartupError,
)
from client_query_cache._core.stream_events import CHANGE_STREAM_HISTORY_LOST_CODE

pytestmark = pytest.mark.unit

_TOKEN_SPACE = 2**16


def _token(position: int) -> str:
    return f"{position:08x}"


class _RecordingWaiter:
    __slots__ = ("outcomes", "target")

    def __init__(self, target: str) -> None:
        self.target = target
        self.outcomes: list[BarrierOutcome] = []

    def resolve(self, outcome: BarrierOutcome) -> None:
        self.outcomes.append(outcome)


@pytest.fixture
def progress() -> BarrierProgress:
    return BarrierProgress()


@pytest.fixture
def owner() -> object:
    return object()


@pytest.fixture
def client() -> object:
    return object()


@pytest.mark.parametrize(
    "timeout",
    [
        0,
        -1,
        0.0,
        math.nan,
        math.inf,
        MAX_BARRIER_TIMEOUT_SECONDS * 2,
        10**1000,
        True,
        "1",
        None,
    ],
)
def test_barrier_deadline_rejects_non_finite_non_positive_and_non_numeric_timeouts(
    timeout: object,
) -> None:
    with pytest.raises(BarrierArgumentError):
        barrier_deadline(timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize("timeout", [0.25, 3, MAX_BARRIER_TIMEOUT_SECONDS])
def test_barrier_deadline_is_one_absolute_monotonic_deadline(timeout: float) -> None:
    before = time.monotonic()

    deadline = barrier_deadline(timeout)

    assert before + timeout <= deadline <= time.monotonic() + timeout


def test_remaining_seconds_raises_once_the_deadline_passed() -> None:
    with pytest.raises(BarrierTimeoutError):
        remaining_seconds(time.monotonic())


def test_remaining_seconds_reports_the_time_left() -> None:
    assert 0 < remaining_seconds(time.monotonic() + 60) <= 60


def test_capture_boundary_copies_the_operation_time_and_owner(
    owner: object, client: object
) -> None:
    operation_time = Timestamp(1_700_000_000, 7)
    session = SimpleNamespace(
        client=client, in_transaction=False, operation_time=operation_time
    )

    boundary = capture_boundary(owner, client, session)

    assert boundary == CausalBoundary(operation_time, owner)


@pytest.mark.parametrize(
    ("session_fields", "message"),
    [
        pytest.param(
            {"client": "foreign", "in_transaction": False},
            "different client",
            id="foreign_client",
        ),
        pytest.param(
            {"in_transaction": True}, "open transaction", id="open_transaction"
        ),
        pytest.param(
            {"in_transaction": False, "operation_time": None},
            "not completed any operation",
            id="no_operation",
        ),
    ],
)
def test_capture_boundary_rejects_unverifiable_sessions(
    owner: object, client: object, session_fields: dict[str, object], message: str
) -> None:
    session = SimpleNamespace(
        **({"client": client, "operation_time": Timestamp(1, 1)} | session_fields)
    )

    with pytest.raises(BarrierArgumentError, match=message):
        capture_boundary(owner, client, session)


@pytest.mark.parametrize(
    "boundary",
    [
        pytest.param(CausalBoundary(Timestamp(1, 1), object()), id="other_owner"),
        pytest.param(Timestamp(1, 1), id="raw_timestamp"),
    ],
)
def test_require_owned_boundary_rejects_foreign_or_raw_boundaries(
    owner: object, boundary: CausalBoundary
) -> None:
    with pytest.raises(BarrierArgumentError):
        require_owned_boundary(owner, boundary)


def test_require_owned_boundary_accepts_its_own_boundary(owner: object) -> None:
    require_owned_boundary(owner, CausalBoundary(Timestamp(1, 1), owner))


@pytest.mark.parametrize(
    ("boundary", "start"),
    [
        pytest.param(
            Timestamp(1_700_000_000, 7), Timestamp(1_700_000_000, 8), id="increment"
        ),
        pytest.param(
            Timestamp(1_700_000_000, MAX_TIMESTAMP_INCREMENT),
            Timestamp(1_700_000_001, 0),
            id="increment_rollover",
        ),
    ],
)
def test_target_starts_at_the_next_timestamp_after_the_boundary(
    boundary: Timestamp, start: Timestamp
) -> None:
    assert target_start_time(boundary) == start


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        (BarrierOutcome.CONTINUITY_LOST, BarrierContinuityError),
        (BarrierOutcome.CLOSED, BarrierClosedError),
    ],
)
def test_raise_for_outcome_maps_failures_to_explicit_errors(
    outcome: BarrierOutcome, error: type[Exception]
) -> None:
    with pytest.raises(error):
        raise_for_outcome(outcome)


def test_raise_for_outcome_returns_on_completion() -> None:
    raise_for_outcome(BarrierOutcome.COMPLETED)


def test_closed_error_is_also_a_cache_closed_error() -> None:
    assert issubclass(BarrierClosedError, CacheClosedError)


@pytest.mark.parametrize(
    ("driver_error", "barrier_error"),
    [
        pytest.param(NetworkTimeout("slow"), BarrierTimeoutError, id="network_timeout"),
        pytest.param(
            ExecutionTimeout("slow", code=50), BarrierTimeoutError, id="execution"
        ),
        pytest.param(
            OperationFailure("gone", code=CHANGE_STREAM_HISTORY_LOST_CODE),
            BarrierContinuityError,
            id="history_lost",
        ),
        pytest.param(
            OperationFailure("denied", code=13), BarrierUnavailableError, id="other"
        ),
        pytest.param(
            ConnectionFailure("down"), BarrierUnavailableError, id="connection"
        ),
    ],
)
def test_driver_failures_map_to_barrier_errors(
    driver_error: Exception, barrier_error: type[Exception]
) -> None:
    assert isinstance(barrier_error_for_driver_failure(driver_error), barrier_error)  # type: ignore[arg-type]


def test_a_startup_timeout_maps_to_a_barrier_timeout() -> None:
    startup_error = StreamStartupError("failed")
    startup_error.__cause__ = NetworkTimeout("slow")

    assert isinstance(
        barrier_error_for_startup_failure(startup_error), BarrierTimeoutError
    )


def test_an_unsupported_startup_maps_to_unavailable() -> None:
    startup_error = StreamStartupError("server 7.0 is not supported")

    error = barrier_error_for_startup_failure(startup_error)

    assert isinstance(error, BarrierUnavailableError)
    assert str(error) == "server 7.0 is not supported"


class _BarrierProgressMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.progress = BarrierProgress()
        self.position = 0
        self.frontier: int | None = None
        self.floor: int | None = None
        self.closed = False
        self.pending: dict[_RecordingWaiter, int] = {}
        self.expected: dict[_RecordingWaiter, list[BarrierOutcome]] = {}

    def _outcome_for(self, target: int) -> BarrierOutcome | None:
        if self.closed:
            return BarrierOutcome.CLOSED
        if self.floor is not None and target < self.floor:
            return BarrierOutcome.CONTINUITY_LOST
        if self.frontier is not None and self.frontier >= target:
            return BarrierOutcome.COMPLETED
        return None

    def _settle_pending(self) -> None:
        for waiter, target in list(self.pending.items()):
            outcome = self._outcome_for(target)
            if outcome is not None:
                del self.pending[waiter]
                self.expected[waiter].append(outcome)

    def _fail_pending(self, outcome: BarrierOutcome) -> None:
        for waiter in self.pending:
            self.expected[waiter].append(outcome)
        self.pending.clear()

    @rule(offset=st.integers(-_TOKEN_SPACE, _TOKEN_SPACE))
    def register(self, offset: int) -> None:
        target = max(self.position + offset, 0)
        waiter = _RecordingWaiter(_token(target))
        expected = self._outcome_for(target)
        self.expected[waiter] = []

        assert self.progress.register(waiter) is expected

        if expected is None:
            self.pending[waiter] = target

    @rule(step=st.integers(0, _TOKEN_SPACE))
    def advance(self, step: int) -> None:
        self.position += step
        self.frontier = self.position
        self.progress.advance(_token(self.position))
        self._settle_pending()

    @rule()
    def lose_continuity(self) -> None:
        self.frontier = None
        self.progress.lose_continuity()
        self._fail_pending(BarrierOutcome.CONTINUITY_LOST)

    @rule(step=st.integers(0, _TOKEN_SPACE))
    def restart(self, step: int) -> None:
        self.position += step
        self.floor = self.frontier = self.position
        self.progress.restart(_token(self.position))
        self._settle_pending()

    @rule()
    def close(self) -> None:
        self.closed = True
        self.progress.close()
        self._fail_pending(BarrierOutcome.CLOSED)

    @rule(draws=st.data())
    def discard(self, draws: st.DataObject) -> None:
        if self.pending:
            waiter = draws.draw(st.sampled_from(list(self.pending)))
            del self.pending[waiter]
            self.progress.discard(waiter)

    @invariant()
    def waiters_resolve_once_with_the_modelled_outcome(self) -> None:
        for waiter, outcomes in self.expected.items():
            assert waiter.outcomes == outcomes
        assert self.progress._waiters == set(self.pending)


def test_barrier_progress_resolves_waiters_in_any_operation_order() -> None:
    run_state_machine_as_test(  # type: ignore[no-untyped-call]
        _BarrierProgressMachine, settings=settings(derandomize=True)
    )


def test_lost_continuity_fails_pending_waiters_and_older_later_targets(
    progress: BarrierProgress,
) -> None:
    pending = _RecordingWaiter(_token(5))
    progress.advance(_token(3))
    progress.register(pending)

    progress.lose_continuity()
    progress.restart(_token(10))

    assert pending.outcomes == [BarrierOutcome.CONTINUITY_LOST]
    assert progress.register(_RecordingWaiter(_token(9))) is (
        BarrierOutcome.CONTINUITY_LOST
    )
    assert progress.register(_RecordingWaiter(_token(10))) is BarrierOutcome.COMPLETED
    assert not progress._waiters


def test_a_waiter_registered_while_continuity_is_lost_fails_if_it_precedes_the_restart(
    progress: BarrierProgress,
) -> None:
    progress.advance(_token(3))
    progress.lose_continuity()
    older = _RecordingWaiter(_token(5))
    newer = _RecordingWaiter(_token(12))

    assert progress.register(older) is None
    assert progress.register(newer) is None
    progress.restart(_token(10))
    progress.advance(_token(12))

    assert older.outcomes == [BarrierOutcome.CONTINUITY_LOST]
    assert newer.outcomes == [BarrierOutcome.COMPLETED]


def test_close_fails_pending_and_later_waiters(progress: BarrierProgress) -> None:
    pending = _RecordingWaiter(_token(5))
    progress.register(pending)

    progress.close()

    assert pending.outcomes == [BarrierOutcome.CLOSED]
    assert progress.register(_RecordingWaiter(_token(0))) is BarrierOutcome.CLOSED
    assert not progress._waiters


def test_discard_releases_a_pending_waiter(progress: BarrierProgress) -> None:
    waiter = _RecordingWaiter(_token(5))
    progress.register(waiter)

    progress.discard(waiter)
    progress.advance(_token(5))

    assert waiter.outcomes == []
    assert not progress._waiters
