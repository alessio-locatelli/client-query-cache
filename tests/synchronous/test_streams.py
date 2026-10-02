from __future__ import annotations

import datetime
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, TypedDict, cast
from unittest.mock import Mock

import pytest
from bson.binary import UuidRepresentation
from bson.codec_options import CodecOptions
from pymongo.errors import ConnectionFailure, OperationFailure

from client_query_cache import StreamHealthStatus
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.errors import StreamLifecycleError, StreamStartupError
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore
from client_query_cache._core.stream_health import RetryBackoff, StreamHealth
from client_query_cache.synchronous.streams import (
    ChangeStreamCoordinator,
    DatabaseStreamSupervisor,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from concurrent.futures import Future

    from pymongo.synchronous.database import Database


class PausedCoordinator(TypedDict):
    coordinator: ChangeStreamCoordinator
    release: threading.Event
    activation: Future[DatabaseStreamSupervisor | None]
    phase: int  # Zero means initial startup; one means reconnect.


pytestmark = pytest.mark.unit

_FAST_BACKOFF = RetryBackoff(base_seconds=0.001, max_seconds=0.002)
_WALL_TIME = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)


class _FixedDelayBackoff:
    __slots__ = ("_delay",)

    def __init__(self, delay: float) -> None:
        self._delay = delay

    def next_delay(self) -> float:
        return self._delay


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
        try:
            resume_token = item["_id"]
        except KeyError:
            resume_token = self.resume_token
        self.resume_token = resume_token
        return item

    def close(self) -> None:
        self.closed = True
        self._closed_event.set()


class _BlockingCloseStream(_ScriptedStream):
    __slots__ = ("close_started", "release_close")

    def __init__(self, events: list[object]) -> None:
        super().__init__(events)
        self.close_started = threading.Event()
        self.release_close = threading.Event()

    def close(self) -> None:
        self.close_started.set()
        self.release_close.wait(timeout=2)
        super().close()


class _CloseRaisesStream:
    __slots__ = ("close_started", "release_next", "resume_token")

    def __init__(self) -> None:
        self.close_started = threading.Event()
        self.release_next = threading.Event()
        self.resume_token: dict[str, object] | None = None

    def next(self) -> dict[str, object]:
        self.release_next.wait(timeout=2)
        raise StopIteration

    def close(self) -> None:
        self.close_started.set()
        raise ConnectionFailure("cursor close failed")


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
        before_watch: Callable[[int], None] | None = None,
    ) -> None:
        self.name = name
        self.codec_options: CodecOptions[Any] = CodecOptions()
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


def _mock_cache() -> Mock:
    cache = Mock()
    cache.namespaces_for_database.return_value = []
    return cache


def _is_healthy(supervisor: DatabaseStreamSupervisor) -> bool:
    return supervisor.healthy


def _insert_event(marker: str = "tok-1") -> dict[str, object]:
    return {
        "_id": {"tok": marker},
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
        "wallTime": _WALL_TIME,
    }


def _attempt_admission(cache: CacheCore, database: str) -> AdmissionOutcome:
    namespace = NamespaceId(database, "coll")
    capture = cache.begin_identity_admission(namespace, "doc-1")
    return cache.admit_identity(capture, "full", {"v": "x"})


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail(  # pragma: no cover (test timeout diagnostic)
        "condition was not met within the timeout"
    )


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
    supervisor = make_supervisor(_as_database(database), _mock_cache())

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
    supervisor = make_supervisor(_as_database(database), _mock_cache())

    with pytest.raises(StreamStartupError):
        supervisor.start()

    assert supervisor.healthy is False


def test_start_raises_and_closes_the_stream_when_stop_races_it(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream = _ScriptedStream([])
    database = _FakeDatabase("db", [stream])
    supervisor = make_supervisor(_as_database(database), _mock_cache())

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
        supervisor = make_supervisor(_as_database(database), _mock_cache())

        def run_start(supervisor: DatabaseStreamSupervisor = supervisor) -> None:
            try:
                with suppress(StreamLifecycleError):
                    supervisor.start()
            except BaseException as exc:  # noqa: BLE001  # pragma: no cover (worker failure reporting)
                errors.append(exc)

        def run_stop(supervisor: DatabaseStreamSupervisor = supervisor) -> None:
            try:
                supervisor.stop()
            except BaseException as exc:  # noqa: BLE001  # pragma: no cover (worker failure reporting)
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
    supervisor = make_supervisor(_as_database(database), _mock_cache())
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
    coordinator = make_coordinator(client, _mock_cache())
    coordinator.activate_database("first")
    coordinator.close()

    with pytest.raises(StreamLifecycleError):
        coordinator.activate_database("first")


def test_start_becomes_healthy_and_routes_events(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = _mock_cache()
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
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )
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
    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db",
        [stream1, OperationFailure("still down", code=1), _ScriptedStream([])],
    )
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )
    watch_calls_after_recovery = 3

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
    _wait_until(lambda: supervisor.healthy)


def test_a_stop_racing_a_successful_reopen_does_not_report_healthy(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )

    def before_watch(index: int) -> None:
        if index == 1:
            supervisor._stop_event.set()

    database._before_watch = before_watch
    watch_calls_after_reopen = 2

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reopen)
    assert supervisor._thread is not None
    supervisor._thread.join(timeout=2)

    assert supervisor.healthy is False


def test_stop_racing_a_successful_reopen_leaves_cache_unavailable(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = CacheCore()
    supervisor = make_supervisor(_as_database(_FakeDatabase("db", [])), cache)
    healthy_update_started = threading.Event()
    release_healthy_update = threading.Event()
    closed_update_started = threading.Event()
    original_set_database_available = CacheCore.set_database_available

    def delayed_set_database_available(
        self: CacheCore, database: str, *, available: bool
    ) -> None:
        if available:
            healthy_update_started.set()
            release_healthy_update.wait(timeout=2)
        else:
            closed_update_started.set()
        original_set_database_available(self, database, available=available)

    monkeypatch.setattr(
        CacheCore, "set_database_available", delayed_set_database_available
    )
    healthy_thread = threading.Thread(
        target=supervisor._set_health, args=(StreamHealth.HEALTHY,)
    )
    closed_thread = threading.Thread(
        target=supervisor._set_health, args=(StreamHealth.CLOSED,)
    )

    healthy_thread.start()
    assert healthy_update_started.wait(timeout=2)
    closed_thread.start()
    closed_update_started.wait(timeout=0.1)
    release_healthy_update.set()
    healthy_thread.join(timeout=2)
    closed_thread.join(timeout=2)

    assert supervisor.healthy is False
    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE


def test_stop_prevents_recovery_from_restoring_cache_eligibility(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    supervisor = make_supervisor(_as_database(_FakeDatabase("db", [])), cache)
    supervisor._stop_event.set()

    supervisor._set_health(StreamHealth.HEALTHY)

    assert supervisor.healthy is False
    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE


def test_stop_interrupts_an_in_progress_backoff_wait(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
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
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_long_backoff()
    )

    supervisor.start()
    _wait_until(entered_backoff.is_set)
    supervisor.stop()

    assert supervisor.healthy is False


def test_stop_event_set_during_an_unresumable_clear_exits_the_retry_loop(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream1 = _ScriptedStream([OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db", [stream1, OperationFailure("history lost", code=286)]
    )
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )

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
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )
    database._script.append(
        _StreamStopsThenFails(supervisor._stop_event, OperationFailure("blip", code=1))
    )

    supervisor.start()

    assert len(database.watch_calls) == 1


def test_start_raises_when_called_more_than_once(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), _mock_cache())

    supervisor.start()
    with pytest.raises(StreamLifecycleError):
        supervisor.start()


def test_unexpected_stream_closure_triggers_reconnect_instead_of_staying_healthy(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream1 = _ScriptedStream([StopIteration()])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )
    watch_calls_after_recovery = 2

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
    _wait_until(lambda: supervisor.healthy)


def test_stream_poll_is_counted_even_when_next_raises(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    stream1 = _ScriptedStream([StopIteration()])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)

    supervisor.start()
    _wait_until(lambda: cache.stream_cost_snapshot("db").stream_polls >= 1)


def test_stream_survives_events_with_non_default_codec_values(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    event = {
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

    supervisor.start()
    _wait_until(lambda: cache.stream_cost_snapshot("db").logical_event_bytes > 0)
    assert supervisor.healthy


class _Unencodable:
    __slots__ = ()


def test_invalidation_survives_unencodable_logical_bytes(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": 1})
    event = {
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1", "unencodable": _Unencodable()},
        "wallTime": _WALL_TIME,
    }
    database = _FakeDatabase("db", [_ScriptedStream([event]), _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)

    supervisor.start()
    _wait_until(lambda: cache.stream_cost_snapshot("db").invalidations >= 1)
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


def test_clears_the_cache_when_reconnecting_without_a_resume_token(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = _mock_cache()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    stream1 = _ScriptedStream([OperationFailure("blip before any event", code=1)])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    watch_calls_after_reconnect = 2

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reconnect)
    calls_to_clear = 2
    assert cache.clear_namespace.call_count == calls_to_clear
    cache.clear_namespace.assert_any_call(NamespaceId("db", "coll"))
    assert "resume_after" not in database.watch_calls[1]
    assert "start_after" not in database.watch_calls[1]
    _wait_until(lambda: supervisor.healthy)


def test_clears_known_namespaces_when_resume_history_is_lost(
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

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
    calls_to_clear = 2
    assert cache.clear_namespace.call_count == calls_to_clear
    cache.clear_namespace.assert_any_call(NamespaceId("db", "coll"))
    assert "resume_after" not in database.watch_calls[2]
    assert "start_after" not in database.watch_calls[2]
    _wait_until(lambda: supervisor.healthy)


@pytest.mark.parametrize(
    "invalidate_event",
    [
        pytest.param(
            {
                "_id": {"tok": "drop"},
                "operationType": "dropDatabase",
                "wallTime": _WALL_TIME,
            },
            id="drop_database",
        ),
        pytest.param(
            {
                "_id": {"tok": "inv"},
                "operationType": "invalidate",
                "wallTime": _WALL_TIME,
            },
            id="invalidate",
        ),
    ],
)
def test_reopens_with_start_after_following_a_database_invalidation_event(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    invalidate_event: dict[str, object],
) -> None:
    cache = _mock_cache()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    stream1 = _ScriptedStream([_insert_event("tok-1"), invalidate_event])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)
    watch_calls_after_reopen = 2

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reopen)
    assert database.watch_calls[1]["start_after"] == invalidate_event["_id"]
    assert "resume_after" not in database.watch_calls[1]
    calls_to_clear = 2
    assert cache.clear_namespace.call_count == calls_to_clear
    cache.clear_namespace.assert_any_call(NamespaceId("db", "coll"))
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
    supervisor = make_supervisor(
        _as_database(database), _mock_cache(), backoff=_FAST_BACKOFF
    )

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
    coordinator = make_coordinator(client, _mock_cache())

    first = coordinator.activate_database("first")
    second = coordinator.activate_database("second")
    same_first = coordinator.activate_database("first")

    assert first is not None
    assert second is not None
    assert first is not second
    assert first is same_first
    assert (
        coordinator.stream_health_snapshot("first").status is StreamHealthStatus.HEALTHY
    )
    assert _is_healthy(first) is True
    assert _is_healthy(second) is True

    coordinator.close()

    assert (
        coordinator.stream_health_snapshot("first").status is StreamHealthStatus.CLOSED
    )
    assert (
        coordinator.stream_health_snapshot("untouched").status
        is StreamHealthStatus.CLOSED
    )
    assert _is_healthy(first) is False
    assert _is_healthy(second) is False


def test_activate_database_bypasses_when_startup_is_unsupported(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> None:
    database = _FakeDatabase("db", [], version_array=[5, 0, 9])
    client = Mock()
    client.__getitem__ = Mock(return_value=_as_database(database))
    cache = CacheCore()
    coordinator = make_coordinator(client, cache)

    coordinator.activate_database("db")

    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE
    assert (
        coordinator.stream_health_snapshot("db").status
        is StreamHealthStatus.STARTUP_FAILED
    )
    assert coordinator._supervisors == {}


def test_cache_use_is_bypassed_until_start_completes(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    release = threading.Event()

    def before_watch(_index: int) -> None:
        release.wait(timeout=2)

    database = _FakeDatabase("db", [_ScriptedStream([])], before_watch=before_watch)
    cache = CacheCore()
    supervisor = make_supervisor(_as_database(database), cache)

    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE

    thread = threading.Thread(target=supervisor.start)
    thread.start()
    _wait_until(lambda: len(database.watch_calls) == 1)
    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE

    release.set()
    thread.join()

    assert _attempt_admission(cache, "db") is AdmissionOutcome.ADMITTED


def test_cache_use_is_bypassed_while_reconnecting_and_restored_once_healthy(
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
    cache = CacheCore()
    supervisor = make_supervisor(_as_database(database), cache, backoff=_FAST_BACKOFF)

    supervisor.start()
    _wait_until(lambda: len(database.watch_calls) == watch_calls_before_release)
    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE

    release.set()
    _wait_until(lambda: supervisor.healthy)

    assert _attempt_admission(cache, "db") is AdmissionOutcome.ADMITTED


def test_cache_use_is_bypassed_after_stop(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache)

    supervisor.start()
    assert _attempt_admission(cache, "db") is AdmissionOutcome.ADMITTED

    supervisor.stop()

    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE


def test_cache_use_is_bypassed_while_stop_waits_for_stream_cleanup(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    stream = _BlockingCloseStream([])
    supervisor = make_supervisor(_as_database(_FakeDatabase("db", [stream])), cache)
    supervisor.start()
    stop_thread = threading.Thread(target=supervisor.stop)

    stop_thread.start()
    assert stream.close_started.wait(timeout=2)
    outcome = _attempt_admission(cache, "db")
    stream.release_close.set()
    stop_thread.join(timeout=2)

    assert not stop_thread.is_alive()
    assert outcome is AdmissionOutcome.DECLINED_UNAVAILABLE


def test_stop_joins_the_worker_when_stream_close_raises(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    stream = _CloseRaisesStream()
    supervisor = make_supervisor(
        _as_database(_FakeDatabase("db", [stream])), CacheCore()
    )
    supervisor.start()
    with ThreadPoolExecutor(max_workers=1) as executor:
        stop = executor.submit(supervisor.stop)
        assert stream.close_started.wait(timeout=2)
        completed_before_worker_exit = stop.done()
        stream.release_next.set()

        assert stop.result(timeout=2) is None

    assert not completed_before_worker_exit
    assert supervisor._thread is not None
    assert not supervisor._thread.is_alive()


def test_cache_use_stays_bypassed_when_startup_fails(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    database = _FakeDatabase("db", [ConnectionFailure("down")])
    supervisor = make_supervisor(_as_database(database), cache)

    with pytest.raises(StreamStartupError):
        supervisor.start()

    assert _attempt_admission(cache, "db") is AdmissionOutcome.DECLINED_UNAVAILABLE


def test_a_fresh_start_clears_cache_state_left_over_from_before_it_existed(
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": "stale"})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit

    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = make_supervisor(_as_database(database), cache)

    supervisor.start()
    _wait_until(lambda: supervisor.healthy)

    assert cache.lookup_identity(namespace, "doc-1", "full").hit is False


def test_coordinator_health_replaces_startup_failure_on_retry(
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> None:
    database = _FakeDatabase(
        "db", [ConnectionFailure("startup unavailable"), _ScriptedStream([])]
    )
    client = Mock()
    client.__getitem__ = Mock(return_value=_as_database(database))
    coordinator = make_coordinator(client, CacheCore())
    assert (
        coordinator.stream_health_snapshot("db").status
        is StreamHealthStatus.NOT_STARTED
    )
    assert database.watch_calls == []
    assert coordinator.activate_database("db") is None
    assert (
        coordinator.stream_health_snapshot("db").status
        is StreamHealthStatus.STARTUP_FAILED
    )
    assert coordinator.activate_database("db") is not None
    assert coordinator.stream_health_snapshot("db").status is StreamHealthStatus.HEALTHY
    assert len(database.watch_calls) == 2


@pytest.fixture(params=[0, 1], ids=["startup", "reconnect"])
def paused_coordinator(
    request: pytest.FixtureRequest,
    make_coordinator: Callable[..., ChangeStreamCoordinator],
) -> Iterator[PausedCoordinator]:
    release = threading.Event()
    entered = threading.Event()

    def before_watch(index: int) -> None:
        if index == request.param:
            entered.set()
            assert release.wait(5)

    script: list[object] = (
        [_ScriptedStream([])]
        if request.param == 0
        else [_ScriptedStream([ConnectionFailure("reconnect")]), _ScriptedStream([])]
    )
    database = _FakeDatabase("db", script, before_watch=before_watch)
    client = Mock()
    client.__getitem__ = Mock(return_value=_as_database(database))
    coordinator = make_coordinator(client, CacheCore())
    with ThreadPoolExecutor(max_workers=1) as executor:
        activation = executor.submit(coordinator.activate_database, "db")
        assert entered.wait(5)
        yield PausedCoordinator(
            coordinator=coordinator,
            release=release,
            activation=activation,
            phase=request.param,
        )
        release.set()
        activation.result(timeout=5)


def test_coordinator_health_inspection_during_io_does_not_deadlock(
    paused_coordinator: PausedCoordinator,
) -> None:
    coordinator = paused_coordinator["coordinator"]
    release = paused_coordinator["release"]
    activation = paused_coordinator["activation"]
    phase = paused_coordinator["phase"]
    expected = (
        StreamHealthStatus.CONNECTING if phase == 0 else StreamHealthStatus.RECONNECTING
    )
    assert coordinator.stream_health_snapshot("db").status is expected
    assert (
        coordinator.stream_health_snapshot("untouched").status
        is StreamHealthStatus.NOT_STARTED
    )
    release.set()
    assert activation.result(timeout=5) is not None
    _wait_until(
        lambda: (
            coordinator.stream_health_snapshot("db").status
            is StreamHealthStatus.HEALTHY
        )
    )
