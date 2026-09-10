from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock

import pytest
from pymongo.errors import ConnectionFailure, OperationFailure

from mongo_client_cache._core.errors import StreamLifecycleError, StreamStartupError
from mongo_client_cache._core.keys import NamespaceId
from mongo_client_cache._core.stream_health import RetryBackoff
from mongo_client_cache.synchronous.streams import (
    ChangeStreamCoordinator,
    DatabaseStreamSupervisor,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from pymongo.synchronous.database import Database

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
        self._closed_event = threading.Event()

    def next(self) -> dict[str, object]:
        if not self._events:
            self._closed_event.wait()
            raise StopIteration
        item = self._events.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, dict)
        self.resume_token = item.get("_id", self.resume_token)
        return item

    def close(self) -> None:
        self.closed = True
        self._closed_event.set()


class _StreamStopsThenFails:
    __slots__ = ("_error", "_stop_event", "resume_token")

    def __init__(self, stop_event: threading.Event, error: Exception) -> None:
        self._stop_event = stop_event
        self._error = error
        self.resume_token: dict[str, object] | None = None

    def next(self) -> dict[str, object]:
        self._stop_event.set()
        raise self._error

    def close(self) -> None:
        pass


class _FakeDatabase:
    __slots__ = ("_before_watch", "_script", "client", "name", "watch_calls")

    def __init__(
        self,
        name: str,
        script: list[object],
        *,
        version_array: list[int] | None = None,
        before_watch: Callable[[int], None] | None = None,
    ) -> None:
        self.name = name
        self.client = SimpleNamespace(
            server_info=lambda: {
                "version": ".".join(str(part) for part in (version_array or [8, 0, 4])),
                "versionArray": version_array or [8, 0, 4, 0],
            }
        )
        self._script = list(script)
        self.watch_calls: list[dict[str, object]] = []
        self._before_watch = before_watch

    def watch(self, _pipeline: object, **kwargs: object) -> object:
        index = len(self.watch_calls)
        self.watch_calls.append(kwargs)
        if self._before_watch is not None:
            self._before_watch(index)
        item = self._script[index]
        if isinstance(item, Exception):
            raise item
        return item


def _as_database(fake: _FakeDatabase) -> Database[Any]:
    return cast("Database[Any]", fake)


def _is_healthy(supervisor: DatabaseStreamSupervisor) -> bool:
    return supervisor.healthy


def _insert_event(marker: str = "tok-1") -> dict[str, object]:
    return {
        "_id": {"tok": marker},
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
    }


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail("condition was not met within the timeout")  # pragma: lax no cover


@pytest.fixture
def make_supervisor() -> Iterator[Callable[..., DatabaseStreamSupervisor]]:
    supervisors: list[DatabaseStreamSupervisor] = []

    def _make(
        database: Database[Any],
        cache: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> DatabaseStreamSupervisor:
        supervisor = DatabaseStreamSupervisor(database, cache, **kwargs)
        supervisors.append(supervisor)
        return supervisor

    yield _make
    for supervisor in supervisors:
        supervisor.stop()


@pytest.fixture
def make_coordinator() -> Iterator[Callable[..., ChangeStreamCoordinator]]:
    coordinators: list[ChangeStreamCoordinator] = []

    def _make(client: Any, cache: Any) -> ChangeStreamCoordinator:  # noqa: ANN401
        coordinator = ChangeStreamCoordinator(client, cache)
        coordinators.append(coordinator)
        return coordinator

    yield _make
    for coordinator in coordinators:
        coordinator.close()


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
def test_start_fails_closed(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    version_array: list[int],
    script: list[object],
    expected_watch_calls: int,
) -> None:
    database = _FakeDatabase("db", script, version_array=version_array)
    supervisor = make_supervisor(_as_database(database), Mock())

    with pytest.raises(StreamStartupError):
        supervisor.start()

    assert len(database.watch_calls) == expected_watch_calls
    assert supervisor.healthy is False


def test_start_fails_closed_when_server_info_itself_fails(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase("db", [])

    def failing_server_info() -> dict[str, object]:
        raise ConnectionFailure("no primary available")

    database.client = SimpleNamespace(server_info=failing_server_info)
    supervisor = make_supervisor(_as_database(database), Mock())

    with pytest.raises(StreamStartupError):
        supervisor.start()

    assert supervisor.healthy is False


def test_start_raises_and_closes_the_stream_when_stop_races_it(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream = _ScriptedStream([])
    database = _FakeDatabase("db", [stream])
    supervisor = make_supervisor(_as_database(database), Mock())

    def before_watch(_index: int) -> None:
        supervisor._stop_event.set()

    database._before_watch = before_watch

    with pytest.raises(StreamLifecycleError):
        supervisor.start()

    assert stream.closed is True
    assert supervisor.healthy is False


def test_concurrent_start_and_stop_never_crash_or_leave_healthy(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    errors: list[BaseException] = []
    iterations = 50

    for _ in range(iterations):
        database = _FakeDatabase("db", [_ScriptedStream([])])
        supervisor = make_supervisor(_as_database(database), Mock())

        def run_start(supervisor: DatabaseStreamSupervisor = supervisor) -> None:
            try:
                supervisor.start()
            except StreamStartupError, StreamLifecycleError:  # pragma: lax no cover
                pass
            except BaseException as exc:  # noqa: BLE001  # pragma: lax no cover
                errors.append(exc)

        def run_stop(supervisor: DatabaseStreamSupervisor = supervisor) -> None:
            try:
                supervisor.stop()
            except BaseException as exc:  # noqa: BLE001  # pragma: lax no cover
                errors.append(exc)

        start_thread = threading.Thread(target=run_start)
        stop_thread = threading.Thread(target=run_stop)
        start_thread.start()
        stop_thread.start()
        start_thread.join()
        stop_thread.join()

        assert supervisor.healthy is False

    assert errors == []


def test_concurrent_starts_let_only_one_caller_publish_a_worker(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), Mock())
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()
    caller_count = 5

    def run_start() -> None:
        try:
            supervisor.start()
        except StreamLifecycleError:
            with outcomes_lock:
                outcomes.append("rejected")
        else:
            with outcomes_lock:
                outcomes.append("started")

    threads = [threading.Thread(target=run_start) for _ in range(caller_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("started") == 1
    assert outcomes.count("rejected") == caller_count - 1
    assert len(database.watch_calls) == 1


def test_coordinator_rejects_activation_after_close(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> None:
    databases = {"first": _FakeDatabase("first", [_ScriptedStream([])])}
    client = Mock()
    client.__getitem__ = Mock(side_effect=databases.__getitem__)
    coordinator = make_coordinator(client, Mock())
    coordinator.activate_database("first")
    coordinator.close()

    with pytest.raises(StreamLifecycleError):
        coordinator.activate_database("first")


def test_start_becomes_healthy_and_routes_events(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
    stream = _ScriptedStream([_insert_event()])
    database = _FakeDatabase("db", [stream])
    supervisor = make_supervisor(_as_database(database), cache)

    supervisor.start()
    assert _is_healthy(supervisor) is True
    _wait_until(lambda: cache.record_write.called)
    cache.record_write.assert_called_once_with(NamespaceId("db", "coll"), "doc-1")

    supervisor.stop()

    assert _is_healthy(supervisor) is False
    assert stream.closed is True


def test_reconnects_using_the_saved_resume_token(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream1 = _ScriptedStream(
        [_insert_event("tok-1"), OperationFailure("blip", code=1)]
    )
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), Mock(), backoff=_FAST_BACKOFF)
    watch_calls_after_reconnect = 2

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reconnect)
    assert database.watch_calls[1]["resume_after"] == {"tok": "tok-1"}
    assert "start_after" not in database.watch_calls[1]
    _wait_until(lambda: supervisor.healthy)
    _wait_until(lambda: stream1.closed)


def test_retries_with_backoff_after_a_transient_reopen_failure(
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

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
    _wait_until(lambda: supervisor.healthy)


def test_stop_interrupts_an_in_progress_backoff_wait(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = []
    entered_backoff = threading.Event()

    def before_watch(index: int) -> None:
        if index == 1:
            entered_backoff.set()

    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db",
        [stream1, OperationFailure("still down", code=1)],
        before_watch=before_watch,
    )
    supervisor = make_supervisor(_as_database(database), cache, backoff=_long_backoff())

    supervisor.start()
    _wait_until(entered_backoff.is_set)
    supervisor.stop()

    assert supervisor.healthy is False


def test_stop_event_set_during_an_unresumable_clear_exits_the_retry_loop(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = []
    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db", [stream1, OperationFailure("history lost", code=286)]
    )
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)

    def before_watch(index: int) -> None:
        if index == 1:
            supervisor._stop_event.set()

    database._before_watch = before_watch
    watch_calls_before_stop = 2

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_before_stop)


def test_handle_stream_failure_is_a_no_op_once_stop_was_already_requested(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase("db", [])
    supervisor = make_supervisor(_as_database(database), Mock(), backoff=_FAST_BACKOFF)
    database._script.append(
        _StreamStopsThenFails(supervisor._stop_event, OperationFailure("blip", code=1))
    )

    supervisor.start()

    assert len(database.watch_calls) == 1


def test_start_raises_when_called_more_than_once(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), Mock())

    supervisor.start()
    with pytest.raises(StreamLifecycleError):
        supervisor.start()


def test_unexpected_stream_closure_triggers_reconnect_instead_of_staying_healthy(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = []
    stream1 = _ScriptedStream([StopIteration()])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    watch_calls_after_recovery = 2

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
    _wait_until(lambda: supervisor.healthy)


def test_clears_the_cache_when_reconnecting_without_a_resume_token(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    stream1 = _ScriptedStream([OperationFailure("blip before any event", code=1)])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    watch_calls_after_reconnect = 2

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reconnect)
    cache.namespaces_for_database.assert_called_once_with("db")
    cache.clear_namespace.assert_called_once_with(NamespaceId("db", "coll"))
    assert "resume_after" not in database.watch_calls[1]
    assert "start_after" not in database.watch_calls[1]
    _wait_until(lambda: supervisor.healthy)


def test_clears_known_namespaces_when_resume_history_is_lost(
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

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
    cache.namespaces_for_database.assert_called_once_with("db")
    cache.clear_namespace.assert_called_once_with(NamespaceId("db", "coll"))
    assert "resume_after" not in database.watch_calls[2]
    assert "start_after" not in database.watch_calls[2]
    _wait_until(lambda: supervisor.healthy)


def test_reopens_with_start_after_following_an_invalidate_event(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    invalidate_event = {"_id": {"tok": "inv"}, "operationType": "invalidate"}
    stream1 = _ScriptedStream([_insert_event("tok-1"), invalidate_event])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    watch_calls_after_reopen = 2

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reopen)
    assert database.watch_calls[1]["start_after"] == {"tok": "inv"}
    assert "resume_after" not in database.watch_calls[1]
    cache.namespaces_for_database.assert_called_once_with("db")
    cache.clear_namespace.assert_called_once_with(NamespaceId("db", "coll"))
    _wait_until(lambda: supervisor.healthy)


def test_supervisor_is_unhealthy_while_reconnecting(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    release = threading.Event()
    watch_calls_before_release = 2

    def before_watch(index: int) -> None:
        if index == 1:
            release.wait(timeout=2)

    stream1 = _ScriptedStream([_insert_event(), OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db", [stream1, _ScriptedStream([])], before_watch=before_watch
    )
    supervisor = make_supervisor(_as_database(database), Mock(), backoff=_FAST_BACKOFF)

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_before_release)
    assert supervisor.healthy is False

    release.set()
    _wait_until(lambda: supervisor.healthy)


def test_coordinator_starts_one_independent_stream_per_active_database(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> None:
    databases = {
        "first": _FakeDatabase("first", [_ScriptedStream([])]),
        "second": _FakeDatabase("second", [_ScriptedStream([])]),
    }
    client = Mock()
    client.__getitem__ = Mock(side_effect=databases.__getitem__)
    coordinator = make_coordinator(client, Mock())

    first = coordinator.activate_database("first")
    second = coordinator.activate_database("second")
    same_first = coordinator.activate_database("first")

    assert first is not second
    assert first is same_first
    assert _is_healthy(first) is True
    assert _is_healthy(second) is True

    coordinator.close()

    assert _is_healthy(first) is False
    assert _is_healthy(second) is False
