from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock

import pytest
from pymongo.errors import ConnectionFailure, OperationFailure

from mongo_client_cache._core.errors import StreamLifecycleError, StreamStartupError
from mongo_client_cache._core.keys import NamespaceId
from mongo_client_cache._core.stream_health import RetryBackoff
from mongo_client_cache.asynchronous.streams import (
    ChangeStreamCoordinator,
    DatabaseStreamSupervisor,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from pymongo.asynchronous.database import AsyncDatabase

pytestmark = pytest.mark.unit

_FAST_BACKOFF = RetryBackoff(base_seconds=0.001, max_seconds=0.002)


class _FixedDelayBackoff:
    __slots__ = ("_delay",)

    def __init__(self, delay: float) -> None:
        self._delay = delay

    def next_delay(self) -> float:
        return self._delay

    def reset(self) -> None:
        pass


def _long_backoff(delay: float = 5.0) -> RetryBackoff:
    return cast("RetryBackoff", _FixedDelayBackoff(delay))


class _ScriptedStream:
    __slots__ = ("_closed_event", "_events", "closed", "resume_token")

    def __init__(self, events: list[object]) -> None:
        self._events = list(events)
        self.resume_token: dict[str, object] | None = None
        self.closed = False
        self._closed_event = asyncio.Event()

    async def next(self) -> dict[str, object]:
        if not self._events:
            await self._closed_event.wait()
            raise StopAsyncIteration  # pragma: lax no cover
        item = self._events.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, dict)
        self.resume_token = item.get("_id", self.resume_token)
        return item

    async def close(self) -> None:
        self.closed = True
        self._closed_event.set()


class _StreamStopsThenFails:
    __slots__ = ("_error", "_stop_event", "resume_token")

    def __init__(self, stop_event: asyncio.Event, error: Exception) -> None:
        self._stop_event = stop_event
        self._error = error
        self.resume_token: dict[str, object] | None = None

    async def next(self) -> dict[str, object]:
        self._stop_event.set()
        raise self._error

    async def close(self) -> None:
        pass


class _FakeDatabase:
    __slots__ = ("_before_watch", "_script", "client", "name", "watch_calls")

    def __init__(
        self,
        name: str,
        script: list[object],
        *,
        version_array: list[int] | None = None,
        before_watch: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self.name = name
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
        async def server_info() -> dict[str, object]:
            return {
                "version": ".".join(str(part) for part in version_array),
                "versionArray": version_array,
            }

        return server_info

    async def watch(self, _pipeline: object, **kwargs: object) -> object:
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


def _is_healthy(supervisor: DatabaseStreamSupervisor) -> bool:
    return supervisor.healthy


def _insert_event(marker: str = "tok-1") -> dict[str, object]:
    return {
        "_id": {"tok": marker},
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
    }


async def _wait_until(
    predicate: Callable[[], bool], *, timeout_seconds: float = 2.0
) -> None:
    async def _poll() -> None:
        while not predicate():  # noqa: ASYNC110 (generic predicate, no single Event)
            await asyncio.sleep(0.005)

    try:
        async with asyncio.timeout(timeout_seconds):
            await _poll()
    except TimeoutError:  # pragma: lax no cover
        pytest.fail("condition was not met within the timeout")


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


def test_fixed_delay_backoff_returns_the_configured_delay_and_ignores_reset() -> None:
    delay = 2.5
    backoff = _FixedDelayBackoff(delay)

    assert backoff.next_delay() == delay
    backoff.reset()
    assert backoff.next_delay() == delay


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
    supervisor = make_supervisor(_as_database(database), Mock())

    with pytest.raises(StreamStartupError):
        await supervisor.start()

    assert len(database.watch_calls) == expected_watch_calls
    assert supervisor.healthy is False


async def test_start_fails_closed_when_server_info_itself_fails(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase("db", [])

    async def failing_server_info() -> dict[str, object]:
        message = "no primary available"  # pytriage: TR5
        raise ConnectionFailure(message)

    database.client = SimpleNamespace(server_info=failing_server_info)
    supervisor = make_supervisor(_as_database(database), Mock())

    with pytest.raises(StreamStartupError):
        await supervisor.start()

    assert supervisor.healthy is False


async def test_start_raises_and_closes_the_stream_when_stop_races_it(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream = _ScriptedStream([])
    database = _FakeDatabase("db", [stream])
    supervisor = make_supervisor(_as_database(database), Mock())

    async def before_watch(_index: int) -> None:
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
    supervisor = make_supervisor(_as_database(database), Mock())
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


async def test_coordinator_rejects_activation_after_close(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> None:
    databases = {"first": _FakeDatabase("first", [_ScriptedStream([])])}
    client = Mock()
    client.__getitem__ = Mock(side_effect=databases.__getitem__)
    coordinator = make_coordinator(client, Mock())
    await coordinator.activate_database("first")
    await coordinator.close()

    with pytest.raises(StreamLifecycleError):
        await coordinator.activate_database("first")


async def test_start_becomes_healthy_and_routes_events(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
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
    supervisor = make_supervisor(_as_database(database), Mock())

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
    supervisor = make_supervisor(_as_database(database), Mock(), backoff=_FAST_BACKOFF)
    watch_calls_after_reconnect = 2

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reconnect)
    assert database.watch_calls[1]["resume_after"] == {"tok": "tok-1"}
    assert "start_after" not in database.watch_calls[1]
    await _wait_until(lambda: supervisor.healthy)
    await _wait_until(lambda: stream1.closed)


async def test_retries_with_backoff_after_a_transient_reopen_failure(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = []
    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db",
        [stream1, OperationFailure("still down", code=1), _ScriptedStream([])],
    )
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    watch_calls_after_recovery = 3

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
    await _wait_until(lambda: supervisor.healthy)


async def test_stop_interrupts_an_in_progress_backoff_wait(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = []
    entered_backoff = asyncio.Event()

    async def before_watch(index: int) -> None:
        if index == 1:
            entered_backoff.set()

    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db",
        [stream1, OperationFailure("still down", code=1)],
        before_watch=before_watch,
    )
    supervisor = make_supervisor(_as_database(database), cache, backoff=_long_backoff())
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
    cache = Mock()
    cache.namespaces_for_database.return_value = []
    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db", [stream1, OperationFailure("history lost", code=286)]
    )
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)

    async def before_watch(index: int) -> None:
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
    supervisor = make_supervisor(_as_database(database), Mock(), backoff=_FAST_BACKOFF)
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
    supervisor = make_supervisor(_as_database(database), Mock())

    await supervisor.start()
    with pytest.raises(StreamLifecycleError):
        await supervisor.start()


async def test_unexpected_stream_closure_triggers_reconnect(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = []
    stream1 = _ScriptedStream([StopAsyncIteration()])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    watch_calls_after_recovery = 2

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
    await _wait_until(lambda: supervisor.healthy)


async def test_clears_the_cache_when_reconnecting_without_a_resume_token(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    stream1 = _ScriptedStream([OperationFailure("blip before any event", code=1)])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    watch_calls_after_reconnect = 2

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reconnect)
    cache.namespaces_for_database.assert_called_once_with("db")
    cache.clear_namespace.assert_called_once_with(NamespaceId("db", "coll"))
    assert "resume_after" not in database.watch_calls[1]
    assert "start_after" not in database.watch_calls[1]
    await _wait_until(lambda: supervisor.healthy)


async def test_clears_known_namespaces_when_resume_history_is_lost(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
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
    cache.namespaces_for_database.assert_called_once_with("db")
    cache.clear_namespace.assert_called_once_with(NamespaceId("db", "coll"))
    assert "resume_after" not in database.watch_calls[2]
    assert "start_after" not in database.watch_calls[2]
    await _wait_until(lambda: supervisor.healthy)


async def test_reopens_with_start_after_following_an_invalidate_event(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    invalidate_event = {"_id": {"tok": "inv"}, "operationType": "invalidate"}
    stream1 = _ScriptedStream([_insert_event("tok-1"), invalidate_event])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    watch_calls_after_reopen = 2

    await supervisor.start()
    await _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reopen)
    assert database.watch_calls[1]["start_after"] == {"tok": "inv"}
    assert "resume_after" not in database.watch_calls[1]
    cache.namespaces_for_database.assert_called_once_with("db")
    cache.clear_namespace.assert_called_once_with(NamespaceId("db", "coll"))
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
    supervisor = make_supervisor(_as_database(database), Mock(), backoff=_FAST_BACKOFF)

    await supervisor.start()
    await _wait_until(reached_second_watch.is_set)
    assert supervisor.healthy is False

    release.set()
    await _wait_until(lambda: supervisor.healthy)


async def test_coordinator_starts_one_independent_stream_per_active_database(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> None:
    databases = {
        "first": _FakeDatabase("first", [_ScriptedStream([])]),
        "second": _FakeDatabase("second", [_ScriptedStream([])]),
    }
    client = Mock()
    client.__getitem__ = Mock(side_effect=databases.__getitem__)
    coordinator = make_coordinator(client, Mock())

    first = await coordinator.activate_database("first")
    second = await coordinator.activate_database("second")
    same_first = await coordinator.activate_database("first")

    assert first is not second
    assert first is same_first
    assert _is_healthy(first) is True
    assert _is_healthy(second) is True

    await coordinator.close()

    assert _is_healthy(first) is False
    assert _is_healthy(second) is False
