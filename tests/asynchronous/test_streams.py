from __future__ import annotations

import asyncio
import contextvars
import datetime
import threading
import time
import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock

import pymongo
import pytest
from bson import Timestamp
from bson.binary import UuidRepresentation
from bson.codec_options import CodecOptions
from pymongo.errors import ConnectionFailure, NetworkTimeout, OperationFailure

from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.errors import (
    BarrierClosedError,
    BarrierContinuityError,
    BarrierTimeoutError,
    BarrierUnavailableError,
    StreamLifecycleError,
    StreamStartupError,
)
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore
from client_query_cache._core.stream_events import CHANGE_STREAM_HISTORY_LOST_CODE
from client_query_cache._core.stream_health import RetryBackoff, StreamHealth
from client_query_cache.asynchronous.streams import (
    ChangeStreamCoordinator,
    DatabaseStreamSupervisor,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from pymongo.asynchronous.database import AsyncDatabase

pytestmark = pytest.mark.unit

_FAST_BACKOFF = RetryBackoff(base_seconds=0.001, max_seconds=0.002)
_BOUNDARY = Timestamp(1_700_000_000, 7)
_WALL_TIME = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)


class _FixedDelayBackoff:
    __slots__ = ("_delay",)

    def __init__(self, delay: float) -> None:
        self._delay = delay

    def next_delay(self) -> float:
        return self._delay


def _long_backoff(delay: float = 5.0) -> RetryBackoff:
    return cast("RetryBackoff", _FixedDelayBackoff(delay))


class _EmptyBatch:
    __slots__ = ("token",)

    def __init__(self, token: str) -> None:
        self.token: dict[str, object] = {"_data": token}


class _ScriptedStream:
    __slots__ = ("_changed", "_events", "alive", "closed", "resume_token")

    def __init__(self, events: list[object]) -> None:
        self._events = list(events)
        self.resume_token: dict[str, object] | None = None
        self.alive = True
        self.closed = False
        self._changed = asyncio.Event()

    def push(self, item: object) -> None:
        self._events.append(item)
        self._changed.set()

    async def try_next(self) -> dict[str, object] | None:
        while not self._events:
            await self._changed.wait()
            self._changed.clear()
        item = self._events.pop(0)
        if isinstance(item, StopAsyncIteration):
            self.alive = False
            return None
        if isinstance(item, Exception):
            raise item
        if isinstance(item, _EmptyBatch):
            self.resume_token = item.token
            return None
        assert isinstance(item, dict)
        self.resume_token = item["_id"]
        return item

    async def close(self) -> None:
        self.closed = True
        self._changed.set()


class _TargetStream:
    __slots__ = ("closed", "resume_token")

    def __init__(self, position: str) -> None:
        self.resume_token = {"_data": position}
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _BlockingCloseStream(_ScriptedStream):
    __slots__ = ("close_started", "release_close")

    def __init__(self, events: list[object]) -> None:
        super().__init__(events)
        self.close_started = asyncio.Event()
        self.release_close = asyncio.Event()

    async def close(self) -> None:
        self.close_started.set()
        await self.release_close.wait()
        await super().close()


class _CloseRaisesStream(_ScriptedStream):
    __slots__ = ("close_started",)

    def __init__(self, events: list[object]) -> None:
        super().__init__(events)
        self.close_started = asyncio.Event()

    async def close(self) -> None:
        self.close_started.set()
        raise ConnectionFailure("cursor close failed")


class _StreamStopsThenFails:
    __slots__ = ("_error", "_stop_event", "resume_token")

    def __init__(self, stop_event: asyncio.Event, error: Exception) -> None:
        self._stop_event = stop_event
        self._error = error
        self.resume_token = {"_data": "0"}

    async def try_next(self) -> dict[str, object]:
        self._stop_event.set()
        raise self._error

    async def close(self) -> None:
        pass


class _FakeDatabase:
    __slots__ = (
        "_before_watch",
        "_script",
        "client",
        "codec_options",
        "name",
        "watch_calls",
    )

    def __init__(
        self,
        name: str,
        script: list[object],
        *,
        version_array: list[int] | None = None,
        before_watch: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self.name = name
        self.codec_options: CodecOptions[Any] = CodecOptions()
        self.client = SimpleNamespace(
            server_info=self._make_server_info(version_array or [8, 0, 4])
        )
        self._script = list(script)
        self.watch_calls: list[dict[str, object]] = []
        self._before_watch = before_watch

    @staticmethod
    def _make_server_info(
        version_array: list[int],
    ) -> Callable[[], object]:
        async def server_info() -> dict[str, object]:  # noqa: RUF029
            return {
                "version": ".".join(str(part) for part in version_array),
                "versionArray": version_array,
            }

        return server_info

    async def watch(self, _pipeline: object = None, **kwargs: object) -> object:
        index = len(self.watch_calls)
        self.watch_calls.append(kwargs)
        if self._before_watch is not None:
            await self._before_watch(index)
        item = self._script[index]
        if isinstance(item, Exception):
            raise item
        return item


def _as_database(fake: _FakeDatabase) -> AsyncDatabase[Any]:
    return cast("AsyncDatabase[Any]", fake)


def _mock_cache() -> Mock:
    cache = Mock()
    cache.namespaces_for_database.return_value = []
    return cache


def _is_healthy(supervisor: DatabaseStreamSupervisor) -> bool:
    return supervisor.healthy


def _deadline(seconds: float = 2.0) -> float:
    return time.monotonic() + seconds


async def _start_barrier(
    supervisor: DatabaseStreamSupervisor, *, seconds: float = 2.0
) -> asyncio.Task[None]:
    waiters_before = len(supervisor._progress._waiters)
    barrier = asyncio.ensure_future(
        supervisor.wait_for_boundary(_BOUNDARY, _deadline(seconds))
    )
    await _wait_until(
        lambda: barrier.done() or len(supervisor._progress._waiters) > waiters_before
    )
    return barrier


def _insert_event(marker: str = "tok-1") -> dict[str, object]:
    return {
        "_id": {"_data": marker},
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
        "wallTime": _WALL_TIME,
    }


def _attempt_admission(cache: CacheCore, database: str) -> AdmissionOutcome:
    namespace = NamespaceId(database, "coll")
    capture = cache.begin_identity_admission(namespace, "doc-1")
    return cache.admit_identity(capture, "full", {"v": "x"})


async def _wait_until(
    predicate: Callable[[], bool], *, timeout_seconds: float = 2.0
) -> None:
    async def _poll() -> None:
        while not predicate():  # noqa: ASYNC110 (generic predicate, no single Event)
            await asyncio.sleep(0.005)

    try:
        async with asyncio.timeout(timeout_seconds):
            await _poll()
    except TimeoutError:  # pragma: no cover (test timeout diagnostic)
        pytest.fail("condition was not met within the timeout")


@pytest.fixture
def caller_marker() -> Iterator[contextvars.ContextVar[str]]:
    marker: contextvars.ContextVar[str] = contextvars.ContextVar(
        "marker", default="fresh"
    )
    token = marker.set("caller")
    yield marker
    marker.reset(token)


@pytest.fixture
async def make_supervisor() -> AsyncIterator[Callable[..., DatabaseStreamSupervisor]]:
    supervisors: list[DatabaseStreamSupervisor] = []

    def _make(
        database: AsyncDatabase[Any],
        cache: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> DatabaseStreamSupervisor:
        supervisor = DatabaseStreamSupervisor(database, cache, **kwargs)
        supervisors.append(supervisor)
        return supervisor

    yield _make
    for supervisor in supervisors:
        await supervisor.stop()


@pytest.fixture
async def make_coordinator() -> AsyncIterator[Callable[..., ChangeStreamCoordinator]]:
    coordinators: list[ChangeStreamCoordinator] = []

    def _make(client: Any, cache: Any) -> ChangeStreamCoordinator:  # noqa: ANN401
        coordinator = ChangeStreamCoordinator(client, cache)
        coordinators.append(coordinator)
        return coordinator

    yield _make
    for coordinator in coordinators:
        await coordinator.close()


@pytest.mark.parametrize(
    ("version_array", "script", "expected_watch_calls"),
    [
        pytest.param([5, 0, 9], [], 0, id="server_below_minimum_version"),
        pytest.param(
            [8, 0, 4],
            [OperationFailure("showExpandedEvents rejected")],
            1,
            id="server_rejects_expanded_events",
        ),
    ],
)
async def test_start_fails_closed(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    version_array: list[int],
    script: list[object],
    expected_watch_calls: int,
) -> None:
    database = _FakeDatabase("db", script, version_array=version_array)
    supervisor = make_supervisor(_as_database(database), _mock_cache())

    with pytest.raises(StreamStartupError):
        await supervisor.start()

    assert len(database.watch_calls) == expected_watch_calls
    assert supervisor.healthy is False


async def test_start_fails_closed_when_server_info_itself_fails(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase("db", [])

    async def failing_server_info() -> dict[str, object]:  # noqa: RUF029
        raise ConnectionFailure("no primary available")

    database.client = SimpleNamespace(server_info=failing_server_info)
    supervisor = make_supervisor(_as_database(database), _mock_cache())

    with pytest.raises(StreamStartupError):
        await supervisor.start()

    assert supervisor.healthy is False


async def test_start_raises_and_closes_the_stream_when_stop_races_it(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream = _ScriptedStream([])
    database = _FakeDatabase("db", [stream])
    supervisor = make_supervisor(_as_database(database), _mock_cache())

    async def before_watch(_index: int) -> None:  # noqa: RUF029
        supervisor._stop_event.set()

    database._before_watch = before_watch

    with pytest.raises(StreamLifecycleError):
        await supervisor.start()

    assert stream.closed is True
    assert supervisor.healthy is False


async def test_concurrent_starts_let_only_one_caller_publish_a_worker(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), _mock_cache())
    caller_count = 5

    async def run_start() -> str:
        try:
            await supervisor.start()
        except StreamLifecycleError:
            return "rejected"
        return "started"

    outcomes = await asyncio.gather(*(run_start() for _ in range(caller_count)))

    assert outcomes.count("started") == 1
    assert outcomes.count("rejected") == caller_count - 1
    assert len(database.watch_calls) == 1


async def test_activate_database_bypasses_when_startup_is_unsupported(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> None:
    database = _FakeDatabase("db", [], version_array=[5, 0, 9])
    client = Mock()
    client.__getitem__ = Mock(return_value=_as_database(database))
    cache = CacheCore()
    coordinator = make_coordinator(client, cache)

    await coordinator.activate_database("db")

    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE


async def test_coordinator_rejects_activation_after_close(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> None:
    databases = {"first": _FakeDatabase("first", [_ScriptedStream([])])}
    client = Mock()
    client.__getitem__ = Mock(side_effect=databases.__getitem__)
    coordinator = make_coordinator(client, _mock_cache())
    await coordinator.activate_database("first")
    await coordinator.close()

    with pytest.raises(StreamLifecycleError):
        await coordinator.activate_database("first")


async def test_start_becomes_healthy_and_routes_events(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = _mock_cache()
    stream = _ScriptedStream([_insert_event()])
    database = _FakeDatabase("db", [stream])
    supervisor = make_supervisor(_as_database(database), cache)

    await supervisor.start()
    assert _is_healthy(supervisor) is True
    await _wait_until(lambda: cache.record_write.called)
    cache.record_write.assert_called_once_with(NamespaceId("db", "coll"), "doc-1")

    await supervisor.stop()

    assert _is_healthy(supervisor) is False
    assert stream.closed is True


async def test_stop_cancels_the_background_task_and_closes_the_stream(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream = _ScriptedStream([])
    database = _FakeDatabase("db", [stream])
    supervisor = make_supervisor(_as_database(database), _mock_cache())

    await supervisor.start()
    task = supervisor._task
    assert task is not None
    assert not task.done()

    await supervisor.stop()

    assert task.done()
    assert task.cancelled()
    assert stream.closed is True


async def test_reconnects_using_the_saved_resume_token(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream1 = _ScriptedStream(
        [_insert_event("tok-1"), OperationFailure("blip", code=1)]
    )
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )
    watch_calls_after_reconnect = 2

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reconnect)
    assert database.watch_calls[1]["resume_after"] == {"_data": "tok-1"}
    assert "start_after" not in database.watch_calls[1]
    await _wait_until(lambda: supervisor.healthy)
    await _wait_until(lambda: stream1.closed)


async def test_retries_with_backoff_after_a_transient_reopen_failure(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db",
        [stream1, OperationFailure("still down", code=1), _ScriptedStream([])],
    )
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )
    watch_calls_after_recovery = 3

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
    await _wait_until(lambda: supervisor.healthy)


async def test_a_stop_racing_a_successful_reopen_does_not_report_healthy(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )

    async def before_watch(index: int) -> None:  # noqa: RUF029
        if index == 1:
            supervisor._stop_event.set()

    database._before_watch = before_watch
    reopen_calls = 2

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == reopen_calls)
    assert supervisor._task is not None
    await supervisor._task

    assert supervisor.healthy is False


def test_stop_prevents_recovery_from_restoring_cache_eligibility(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    supervisor = make_supervisor(_as_database(_FakeDatabase("db", [])), cache)
    supervisor._stop_event.set()

    supervisor._set_health(StreamHealth.HEALTHY)

    assert supervisor.healthy is False
    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE


async def test_stop_interrupts_an_in_progress_backoff_wait(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    entered_backoff = asyncio.Event()

    async def before_watch(index: int) -> None:  # noqa: RUF029
        if index == 1:
            entered_backoff.set()

    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db",
        [stream1, OperationFailure("still down", code=1)],
        before_watch=before_watch,
    )
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_long_backoff()
    )
    watch_calls_before_stop = 2

    await supervisor.start()
    await _wait_until(entered_backoff.is_set)
    supervisor._stop_event.set()

    await _wait_until(lambda: supervisor._task is not None and supervisor._task.done())
    assert supervisor._task is not None
    assert not supervisor._task.cancelled()
    assert len(database.watch_calls) == watch_calls_before_stop


async def test_stop_event_set_during_an_unresumable_clear_exits_the_retry_loop(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db", [stream1, OperationFailure("history lost", code=286)]
    )
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )

    async def before_watch(index: int) -> None:  # noqa: RUF029
        if index == 1:
            supervisor._stop_event.set()

    database._before_watch = before_watch
    watch_calls_before_stop = 2

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == watch_calls_before_stop)


async def test_handle_stream_failure_is_a_no_op_once_stop_was_already_requested(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase("db", [])
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )
    database._script.append(
        _StreamStopsThenFails(supervisor._stop_event, OperationFailure("blip", code=1))
    )

    await supervisor.start()
    await _wait_until(supervisor._stop_event.is_set)

    assert len(database.watch_calls) == 1


async def test_start_raises_when_called_more_than_once(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), _mock_cache())

    await supervisor.start()
    with pytest.raises(StreamLifecycleError):
        await supervisor.start()


async def test_unexpected_stream_closure_triggers_reconnect(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream1 = _ScriptedStream([StopAsyncIteration()])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )
    watch_calls_after_recovery = 2

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
    await _wait_until(lambda: supervisor.healthy)


async def test_stream_poll_is_counted_even_when_iteration_raises(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    stream1 = _ScriptedStream([StopAsyncIteration()])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)

    await supervisor.start()
    await _wait_until(lambda: cache.stream_cost_snapshot("db").stream_polls >= 1)


async def test_stream_survives_events_with_non_default_codec_values(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    event = {
        "_id": {"_data": "01"},
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": uuid.uuid4()},
        "wallTime": _WALL_TIME,
    }
    database = _FakeDatabase("db", [_ScriptedStream([event]), _ScriptedStream([])])
    database.codec_options = CodecOptions(
        uuid_representation=UuidRepresentation.STANDARD
    )
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)

    await supervisor.start()
    await _wait_until(lambda: cache.stream_cost_snapshot("db").logical_event_bytes > 0)
    assert supervisor.healthy


class _Unencodable:
    __slots__ = ()


async def test_invalidation_survives_unencodable_logical_bytes(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": 1})
    event = {
        "_id": {"_data": "01"},
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1", "unencodable": _Unencodable()},
        "wallTime": _WALL_TIME,
    }
    database = _FakeDatabase("db", [_ScriptedStream([event]), _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)

    await supervisor.start()
    await _wait_until(lambda: cache.stream_cost_snapshot("db").invalidations >= 1)
    assert supervisor.healthy
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is False
    assert cache.stream_cost_snapshot("db").logical_event_bytes == 0


def test_clearing_namespaces_resets_stream_cost_statistics() -> None:
    cache = CacheCore()
    cache.record_stream_poll("db")
    cache.record_invalidation_applied("db", 1.0, 1.0, 2.0)
    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = DatabaseStreamSupervisor(
        _as_database(database), cache, backoff=_FAST_BACKOFF
    )

    supervisor._clear_namespaces_for_database()

    snapshot = cache.stream_cost_snapshot("db")
    assert snapshot.stream_polls == 0
    assert snapshot.invalidations == 0


async def test_clears_the_cache_when_reconnecting_without_a_resume_token(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = _mock_cache()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    stream1 = _ScriptedStream([OperationFailure("blip before any event", code=1)])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    watch_calls_after_reconnect = 2

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reconnect)
    calls_to_clear = 2
    assert cache.clear_namespace.call_count == calls_to_clear
    cache.clear_namespace.assert_any_call(NamespaceId("db", "coll"))
    assert "resume_after" not in database.watch_calls[1]
    assert "start_after" not in database.watch_calls[1]
    await _wait_until(lambda: supervisor.healthy)


async def test_clears_known_namespaces_when_resume_history_is_lost(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = _mock_cache()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    stream1 = _ScriptedStream(
        [_insert_event("tok-1"), OperationFailure("blip", code=1)]
    )
    database = _FakeDatabase(
        "db",
        [stream1, OperationFailure("history lost", code=286), _ScriptedStream([])],
    )
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    watch_calls_after_recovery = 3

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
    calls_to_clear = 2
    assert cache.clear_namespace.call_count == calls_to_clear
    cache.clear_namespace.assert_any_call(NamespaceId("db", "coll"))
    assert "resume_after" not in database.watch_calls[2]
    assert "start_after" not in database.watch_calls[2]
    await _wait_until(lambda: supervisor.healthy)


@pytest.mark.parametrize(
    "invalidate_event",
    [
        pytest.param(
            {
                "_id": {"_data": "drop"},
                "operationType": "dropDatabase",
                "wallTime": _WALL_TIME,
            },
            id="drop_database",
        ),
        pytest.param(
            {
                "_id": {"_data": "inv"},
                "operationType": "invalidate",
                "wallTime": _WALL_TIME,
            },
            id="invalidate",
        ),
    ],
)
async def test_reopens_with_start_after_following_a_database_invalidation_event(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    invalidate_event: dict[str, object],
) -> None:
    cache = _mock_cache()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    stream1 = _ScriptedStream([_insert_event("tok-1"), invalidate_event])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    reopen_calls = 2

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == reopen_calls)
    assert database.watch_calls[1]["start_after"] == invalidate_event["_id"]
    assert "resume_after" not in database.watch_calls[1]
    calls_to_clear = 2
    assert cache.clear_namespace.call_count == calls_to_clear
    cache.clear_namespace.assert_any_call(NamespaceId("db", "coll"))
    await _wait_until(lambda: supervisor.healthy)


async def test_supervisor_is_unhealthy_while_reconnecting(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    release = asyncio.Event()
    reached_second_watch = asyncio.Event()

    async def before_watch(index: int) -> None:
        if index == 1:
            reached_second_watch.set()
            await release.wait()

    stream1 = _ScriptedStream([_insert_event(), OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db", [stream1, _ScriptedStream([])], before_watch=before_watch
    )
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )

    await supervisor.start()
    await _wait_until(reached_second_watch.is_set)
    assert supervisor.healthy is False

    release.set()
    await _wait_until(lambda: supervisor.healthy)


def test_unhealthy_transition_disables_cache_before_publishing_health(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = CacheCore()
    supervisor = make_supervisor(_as_database(_FakeDatabase("db", [])), cache)
    supervisor._set_health(StreamHealth.HEALTHY)
    availability_published = threading.Event()
    release_health_publication = threading.Event()
    original_set_database_available = CacheCore.set_database_available

    def delayed_set_database_available(
        self: CacheCore, database: str, *, available: bool
    ) -> None:
        original_set_database_available(self, database, available=available)
        if not available:
            availability_published.set()
            release_health_publication.wait(timeout=2)

    monkeypatch.setattr(
        CacheCore, "set_database_available", delayed_set_database_available
    )
    transition_thread = threading.Thread(
        target=supervisor._set_health, args=(StreamHealth.RECONNECTING,)
    )

    transition_thread.start()
    assert availability_published.wait(timeout=2)
    health_during_cache_transition: list[bool] = []
    health_during_cache_transition.append(supervisor.healthy)
    outcome = _attempt_admission(cache, "db")
    release_health_publication.set()
    transition_thread.join(timeout=2)
    supervisor._set_health(StreamHealth.HEALTHY)

    assert not transition_thread.is_alive()
    assert health_during_cache_transition == [True]
    assert outcome is AdmissionOutcome.DECLINED_UNAVAILABLE
    assert supervisor.healthy is True


async def test_coordinator_starts_one_independent_stream_per_active_database(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> None:
    databases = {
        "first": _FakeDatabase("first", [_ScriptedStream([])]),
        "second": _FakeDatabase("second", [_ScriptedStream([])]),
    }
    client = Mock()
    client.__getitem__ = Mock(side_effect=databases.__getitem__)
    coordinator = make_coordinator(client, _mock_cache())

    first = await coordinator.activate_database("first")
    second = await coordinator.activate_database("second")
    same_first = await coordinator.activate_database("first")

    assert first is not None
    assert second is not None
    assert first is not second
    assert first is same_first
    assert _is_healthy(first) is True
    assert _is_healthy(second) is True

    await coordinator.close()

    assert _is_healthy(first) is False
    assert _is_healthy(second) is False


async def test_cache_use_is_bypassed_until_start_completes(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    release = asyncio.Event()

    async def before_watch(_index: int) -> None:
        await release.wait()

    database = _FakeDatabase("db", [_ScriptedStream([])], before_watch=before_watch)
    cache = CacheCore()
    supervisor = make_supervisor(_as_database(database), cache)

    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE

    task = asyncio.ensure_future(supervisor.start())
    await _wait_until(lambda: len(database.watch_calls) == 1)
    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE

    release.set()
    await task

    assert _attempt_admission(cache, "db") is AdmissionOutcome.ADMITTED


async def test_cache_use_is_bypassed_while_reconnecting_and_restored_once_healthy(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    release = asyncio.Event()
    reached_second_watch = asyncio.Event()

    async def before_watch(index: int) -> None:
        if index == 1:
            reached_second_watch.set()
            await release.wait()

    stream1 = _ScriptedStream([_insert_event(), OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db", [stream1, _ScriptedStream([])], before_watch=before_watch
    )
    cache = CacheCore()
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)

    await supervisor.start()
    await _wait_until(reached_second_watch.is_set)
    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE

    release.set()
    await _wait_until(lambda: supervisor.healthy)

    assert _attempt_admission(cache, "db") is AdmissionOutcome.ADMITTED


async def test_cache_use_is_bypassed_after_stop(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache)

    await supervisor.start()
    assert _attempt_admission(cache, "db") is AdmissionOutcome.ADMITTED

    await supervisor.stop()

    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE


async def test_cache_use_is_bypassed_while_stop_waits_for_stream_cleanup(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    stream = _BlockingCloseStream([])
    supervisor = make_supervisor(_as_database(_FakeDatabase("db", [stream])), cache)
    await supervisor.start()
    stop_task = asyncio.create_task(supervisor.stop())

    await stream.close_started.wait()
    outcome = _attempt_admission(cache, "db")
    stream.release_close.set()
    await stop_task

    assert outcome is AdmissionOutcome.DECLINED_UNAVAILABLE


async def test_stop_continues_when_stream_close_raises(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream = _CloseRaisesStream([])
    supervisor = make_supervisor(
        _as_database(_FakeDatabase("db", [stream])), CacheCore()
    )
    await supervisor.start()

    await supervisor.stop()

    assert stream.close_started.is_set()
    assert supervisor.healthy is False


async def test_cache_use_stays_bypassed_when_startup_fails(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    database = _FakeDatabase("db", [ConnectionFailure("down")])
    supervisor = make_supervisor(_as_database(database), cache)

    with pytest.raises(StreamStartupError):
        await supervisor.start()

    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE


async def test_start_closes_and_fails_when_cancelled_while_connecting(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    entered_server_info = asyncio.Event()
    block = asyncio.Event()

    async def hanging_server_info() -> dict[str, object]:
        entered_server_info.set()
        await block.wait()
        raise AssertionError(  # pragma: no cover (unreachable after cancellation)
            "server_info unexpectedly resumed after cancellation"
        )

    database = _FakeDatabase("db", [_ScriptedStream([])])
    database.client = SimpleNamespace(server_info=hanging_server_info)
    supervisor = make_supervisor(_as_database(database), _mock_cache())

    task = asyncio.ensure_future(supervisor.start())
    await _wait_until(entered_server_info.is_set)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert supervisor.healthy is False
    assert len(database.watch_calls) == 0


async def test_start_closes_the_stream_when_cancelled_racing_a_concurrent_stop(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    entered_first_close = asyncio.Event()

    class _StreamThatHangsOnFirstClose:
        def __init__(self) -> None:
            self.close_calls = 0

        async def next(
            self,
        ) -> dict[str, object]:  # pragma: no cover (test invariant guard)
            message = (
                f"next() must not run after stop is requested ({self.close_calls=})"
            )
            raise AssertionError(message)

        async def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                entered_first_close.set()
                await asyncio.Event().wait()

    stream = _StreamThatHangsOnFirstClose()
    database = _FakeDatabase("db", [stream])
    supervisor = make_supervisor(_as_database(database), _mock_cache())
    supervisor._stop_event.set()

    task = asyncio.ensure_future(supervisor.start())
    await _wait_until(entered_first_close.is_set)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    expected_close_calls = 2
    assert supervisor.healthy is False
    assert stream.close_calls == expected_close_calls


async def test_a_fresh_start_clears_cache_state_left_over_from_before_it_existed(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": "stale"})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit

    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache)

    await supervisor.start()
    await _wait_until(lambda: supervisor.healthy)

    assert cache.lookup_identity(namespace, "doc-1", "full").hit is False


async def test_a_barrier_waits_for_every_event_sharing_the_boundary_time(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = _mock_cache()
    stream = _ScriptedStream([])
    database = _FakeDatabase("db", [stream, _TargetStream("11")])
    supervisor = make_supervisor(_as_database(database), cache)
    await supervisor.start()
    barrier = await _start_barrier(supervisor)
    group_size = 3

    for marker in ("10a", "10b", "10c"):
        stream.push(_insert_event(marker))
    await _wait_until(lambda: cache.record_write.call_count == group_size)
    assert not barrier.done()
    stream.push(_EmptyBatch("11"))

    await asyncio.wait_for(barrier, 2)
    assert database.watch_calls[1]["start_at_operation_time"] == Timestamp(
        1_700_000_000, 8
    )
    assert database.watch_calls[1]["batch_size"] == 0


@pytest.mark.parametrize(
    ("pushed_before", "pushed_after"),
    [
        pytest.param([_EmptyBatch("12")], [], id="frontier_already_passed"),
        pytest.param([], [_EmptyBatch("11")], id="filtered_or_empty_batch"),
    ],
)
async def test_a_barrier_completes_from_resume_progress_without_a_relevant_event(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    pushed_before: list[object],
    pushed_after: list[object],
) -> None:
    cache = _mock_cache()
    stream = _ScriptedStream(pushed_before)
    database = _FakeDatabase("db", [stream, _TargetStream("11")])
    supervisor = make_supervisor(_as_database(database), cache)
    await supervisor.start()
    await _wait_until(
        lambda: supervisor._progress._frontier is not None or not pushed_before
    )
    barrier = await _start_barrier(supervisor)

    for item in pushed_after:
        stream.push(item)

    await asyncio.wait_for(barrier, 2)
    cache.record_write.assert_not_called()
    assert not supervisor._progress._waiters


@pytest.mark.parametrize(
    ("interruption", "reopen_option"),
    [
        pytest.param(
            [_insert_event("10"), OperationFailure("blip", code=1)],
            "resume_after",
            id="resumable_failure",
        ),
        pytest.param(
            [
                {
                    "_id": {"_data": "10"},
                    "operationType": "invalidate",
                    "wallTime": _WALL_TIME,
                }
            ],
            "start_after",
            id="invalidation",
        ),
    ],
)
async def test_a_continuous_reopen_keeps_a_pending_barrier(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    interruption: list[object],
    reopen_option: str,
) -> None:
    stream1 = _ScriptedStream([])
    stream2 = _ScriptedStream([])
    database = _FakeDatabase("db", [stream1, _TargetStream("11"), stream2])
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )
    await supervisor.start()
    barrier = await _start_barrier(supervisor)
    reopen_calls = 3

    for item in interruption:
        stream1.push(item)
    await _wait_until(
        lambda: supervisor.healthy and len(database.watch_calls) == reopen_calls
    )
    assert not barrier.done()
    stream2.push(_EmptyBatch("11"))

    await asyncio.wait_for(barrier, 2)
    assert database.watch_calls[2][reopen_option] == {"_data": "10"}


async def test_losing_resume_history_fails_pending_and_older_barriers(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream1 = _ScriptedStream([])
    recovered = _ScriptedStream([_EmptyBatch("20")])
    database = _FakeDatabase(
        "db",
        [
            stream1,
            _TargetStream("11"),
            OperationFailure("history lost", code=CHANGE_STREAM_HISTORY_LOST_CODE),
            recovered,
            _TargetStream("15"),
            _TargetStream("25"),
        ],
    )
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )
    await supervisor.start()
    pending = await _start_barrier(supervisor)

    stream1.push(_EmptyBatch("05"))
    stream1.push(OperationFailure("blip", code=1))

    with pytest.raises(BarrierContinuityError):
        await asyncio.wait_for(pending, 2)
    await _wait_until(lambda: supervisor._progress._floor == "20")
    with pytest.raises(BarrierContinuityError):
        await supervisor.wait_for_boundary(_BOUNDARY, _deadline())
    newer = await _start_barrier(supervisor)
    recovered.push(_EmptyBatch("25"))
    await asyncio.wait_for(newer, 2)
    assert database.watch_calls[2]["resume_after"] == {"_data": "05"}
    assert "resume_after" not in database.watch_calls[3]


async def test_stopping_the_supervisor_fails_pending_and_later_barriers(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase(
        "db", [_ScriptedStream([]), _TargetStream("11"), _TargetStream("11")]
    )
    supervisor = make_supervisor(_as_database(database), _mock_cache())
    await supervisor.start()
    pending = await _start_barrier(supervisor)

    await supervisor.stop()

    with pytest.raises(BarrierClosedError):
        await asyncio.wait_for(pending, 2)
    with pytest.raises(BarrierClosedError):
        await supervisor.wait_for_boundary(_BOUNDARY, _deadline())


async def test_cancelling_one_barrier_keeps_other_barriers_and_the_stream(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream = _ScriptedStream([])
    database = _FakeDatabase(
        "db", [stream, _TargetStream("11"), _TargetStream("11"), _TargetStream("11")]
    )
    supervisor = make_supervisor(_as_database(database), _mock_cache())
    await supervisor.start()
    cancelled = await _start_barrier(supervisor)
    survivors = [await _start_barrier(supervisor) for _ in range(2)]

    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    remaining_waiters = len(supervisor._progress._waiters)
    stream.push(_EmptyBatch("11"))

    assert await asyncio.wait_for(asyncio.gather(*survivors), 2) == [None, None]
    assert remaining_waiters == len(survivors)
    assert not supervisor._progress._waiters
    assert supervisor.healthy


async def test_publishing_progress_tolerates_a_barrier_cancelled_in_the_same_step(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase("db", [_ScriptedStream([]), _TargetStream("11")])
    supervisor = make_supervisor(_as_database(database), _mock_cache())
    await supervisor.start()
    barrier = await _start_barrier(supervisor)

    barrier.cancel()
    supervisor._progress.advance("11")

    with pytest.raises(asyncio.CancelledError):
        await barrier
    assert not supervisor._progress._waiters


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        pytest.param(NetworkTimeout("slow"), BarrierTimeoutError, id="timeout"),
        pytest.param(
            OperationFailure("gone", code=CHANGE_STREAM_HISTORY_LOST_CODE),
            BarrierContinuityError,
            id="history_lost",
        ),
        pytest.param(ConnectionFailure("down"), BarrierUnavailableError, id="other"),
    ],
)
async def test_a_failed_target_acquisition_raises_an_explicit_barrier_error(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    failure: Exception,
    error: type[Exception],
) -> None:
    database = _FakeDatabase("db", [_ScriptedStream([]), failure])
    supervisor = make_supervisor(_as_database(database), _mock_cache())
    await supervisor.start()

    with pytest.raises(error):
        await supervisor.wait_for_boundary(_BOUNDARY, _deadline())

    assert not supervisor._progress._waiters


async def test_the_stream_task_does_not_inherit_the_starting_callers_context(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    caller_marker: contextvars.ContextVar[str],
) -> None:
    seen: list[str] = []

    class _RecordingStream(_ScriptedStream):
        __slots__ = ()

        async def try_next(self) -> dict[str, object] | None:
            seen.append(caller_marker.get())
            return await super().try_next()

    database = _FakeDatabase("db", [_RecordingStream([_insert_event()])])
    supervisor = make_supervisor(_as_database(database), _mock_cache())
    assert caller_marker.get() == "caller"

    with pymongo.timeout(5):
        await supervisor.start()

    await _wait_until(lambda: len(seen) >= 1)
    assert seen[0] == "fresh"


async def test_barrier_activation_reuses_the_permanent_stream(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> None:
    database = _FakeDatabase("db", [_ScriptedStream([])])
    client = Mock()
    client.__getitem__ = Mock(return_value=_as_database(database))
    coordinator = make_coordinator(client, _mock_cache())

    activated = await coordinator.activate_database_until("db", _deadline())

    assert await coordinator.activate_database("db") is activated
    assert await coordinator.activate_database_until("db", _deadline()) is activated
    assert len(database.watch_calls) == 1


@pytest.mark.parametrize(
    ("script", "version_array", "error"),
    [
        pytest.param([], [5, 0, 9], BarrierUnavailableError, id="unsupported_server"),
        pytest.param(
            [ConnectionFailure("down")], None, BarrierUnavailableError, id="failure"
        ),
        pytest.param(
            [NetworkTimeout("slow")], None, BarrierTimeoutError, id="driver_timeout"
        ),
    ],
)
async def test_barrier_activation_failures_raise_explicit_errors_and_leave_no_stream(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
    script: list[object],
    version_array: list[int] | None,
    error: type[Exception],
) -> None:
    database = _FakeDatabase("db", script, version_array=version_array)
    client = Mock()
    client.__getitem__ = Mock(return_value=_as_database(database))
    coordinator = make_coordinator(client, CacheCore())

    with pytest.raises(error):
        await coordinator.activate_database_until("db", _deadline())

    assert not coordinator._supervisors


async def test_barrier_activation_after_close_raises_closed(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> None:
    coordinator = make_coordinator(Mock(), _mock_cache())
    await coordinator.close()

    with pytest.raises(BarrierClosedError):
        await coordinator.activate_database_until("db", _deadline())
