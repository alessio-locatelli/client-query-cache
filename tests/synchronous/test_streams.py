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
    from collections.abc import Callable

    from pymongo.synchronous.database import Database

pytestmark = pytest.mark.unit

_FAST_BACKOFF = RetryBackoff(base_seconds=0.001, max_seconds=0.002)


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
    # A plain `supervisor.healthy` read narrows under mypy's property
    # narrowing and is not widened by an intervening `stop()`/`start()`
    # call, making a later opposite-value assert falsely "unreachable".
    # Routing the read through a function call sidesteps that narrowing.
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
    pytest.fail("condition was not met within the timeout")


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
    version_array: list[int], script: list[object], expected_watch_calls: int
) -> None:
    database = _FakeDatabase("db", script, version_array=version_array)
    supervisor = DatabaseStreamSupervisor(_as_database(database), Mock())

    with pytest.raises(StreamStartupError):
        supervisor.start()

    assert len(database.watch_calls) == expected_watch_calls
    assert supervisor.healthy is False


def test_start_fails_closed_when_server_info_itself_fails() -> None:
    database = _FakeDatabase("db", [])

    def failing_server_info() -> dict[str, object]:
        message = "no primary available"  # pytriage: TR5
        raise ConnectionFailure(message)

    database.client = SimpleNamespace(server_info=failing_server_info)
    supervisor = DatabaseStreamSupervisor(_as_database(database), Mock())

    with pytest.raises(StreamStartupError):
        supervisor.start()

    assert supervisor.healthy is False


def test_closes_a_stream_opened_after_stop_was_requested() -> None:
    stream = _ScriptedStream([])
    database = _FakeDatabase("db", [stream])
    supervisor = DatabaseStreamSupervisor(_as_database(database), Mock())

    def before_watch(_index: int) -> None:
        supervisor._stop_event.set()

    database._before_watch = before_watch

    try:
        supervisor.start()
        assert stream.closed is True
    finally:
        supervisor.stop()


def test_start_becomes_healthy_and_routes_events() -> None:
    cache = Mock()
    stream = _ScriptedStream([_insert_event()])
    database = _FakeDatabase("db", [stream])
    supervisor = DatabaseStreamSupervisor(_as_database(database), cache)

    supervisor.start()
    try:
        assert _is_healthy(supervisor) is True
        _wait_until(lambda: cache.record_write.called)
        cache.record_write.assert_called_once_with(NamespaceId("db", "coll"), "doc-1")
    finally:
        supervisor.stop()

    assert _is_healthy(supervisor) is False
    assert stream.closed is True


def test_reconnects_using_the_saved_resume_token() -> None:
    stream1 = _ScriptedStream(
        [_insert_event("tok-1"), OperationFailure("blip", code=1)]
    )
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = DatabaseStreamSupervisor(
        _as_database(database), Mock(), backoff=_FAST_BACKOFF
    )
    watch_calls_after_reconnect = 2

    supervisor.start()
    try:
        _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reconnect)
        assert database.watch_calls[1]["resume_after"] == {"tok": "tok-1"}
        assert "start_after" not in database.watch_calls[1]
        _wait_until(lambda: supervisor.healthy)
        _wait_until(lambda: stream1.closed)
    finally:
        supervisor.stop()


def test_start_raises_when_called_more_than_once() -> None:
    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = DatabaseStreamSupervisor(_as_database(database), Mock())

    supervisor.start()
    try:
        with pytest.raises(StreamLifecycleError):
            supervisor.start()
    finally:
        supervisor.stop()


def test_unexpected_stream_closure_triggers_reconnect_instead_of_staying_healthy() -> (
    None
):
    stream1 = _ScriptedStream([StopIteration()])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = DatabaseStreamSupervisor(
        _as_database(database), Mock(), backoff=_FAST_BACKOFF
    )
    watch_calls_after_recovery = 2

    supervisor.start()
    try:
        _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
        _wait_until(lambda: supervisor.healthy)
    finally:
        supervisor.stop()


def test_clears_known_namespaces_when_resume_history_is_lost() -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    stream1 = _ScriptedStream(
        [_insert_event("tok-1"), OperationFailure("blip", code=1)]
    )
    database = _FakeDatabase(
        "db",
        [stream1, OperationFailure("history lost", code=286), _ScriptedStream([])],
    )
    supervisor = DatabaseStreamSupervisor(
        _as_database(database), cache, backoff=_FAST_BACKOFF
    )
    watch_calls_after_recovery = 3

    supervisor.start()
    try:
        _wait_until(lambda: len(database.watch_calls) == watch_calls_after_recovery)
        cache.namespaces_for_database.assert_called_once_with("db")
        cache.clear_namespace.assert_called_once_with(NamespaceId("db", "coll"))
        assert "resume_after" not in database.watch_calls[2]
        assert "start_after" not in database.watch_calls[2]
        _wait_until(lambda: supervisor.healthy)
    finally:
        supervisor.stop()


def test_reopens_with_start_after_following_an_invalidate_event() -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    invalidate_event = {"_id": {"tok": "inv"}, "operationType": "invalidate"}
    stream1 = _ScriptedStream([_insert_event("tok-1"), invalidate_event])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = DatabaseStreamSupervisor(
        _as_database(database), cache, backoff=_FAST_BACKOFF
    )
    watch_calls_after_reopen = 2

    supervisor.start()
    try:
        _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reopen)
        assert database.watch_calls[1]["start_after"] == {"tok": "inv"}
        assert "resume_after" not in database.watch_calls[1]
        cache.namespaces_for_database.assert_called_once_with("db")
        cache.clear_namespace.assert_called_once_with(NamespaceId("db", "coll"))
        _wait_until(lambda: supervisor.healthy)
    finally:
        supervisor.stop()


def test_supervisor_is_unhealthy_while_reconnecting() -> None:
    release = threading.Event()
    watch_calls_before_release = 2

    def before_watch(index: int) -> None:
        if index == 1:
            release.wait(timeout=2)

    stream1 = _ScriptedStream([_insert_event(), OperationFailure("blip", code=1)])
    database = _FakeDatabase(
        "db", [stream1, _ScriptedStream([])], before_watch=before_watch
    )
    supervisor = DatabaseStreamSupervisor(
        _as_database(database), Mock(), backoff=_FAST_BACKOFF
    )

    supervisor.start()
    try:
        _wait_until(lambda: len(database.watch_calls) == watch_calls_before_release)
        assert supervisor.healthy is False

        release.set()
        _wait_until(lambda: supervisor.healthy)
    finally:
        release.set()
        supervisor.stop()


def test_coordinator_starts_one_independent_stream_per_active_database() -> None:
    databases = {
        "first": _FakeDatabase("first", [_ScriptedStream([])]),
        "second": _FakeDatabase("second", [_ScriptedStream([])]),
    }
    client = Mock()
    client.__getitem__ = Mock(side_effect=databases.__getitem__)
    coordinator = ChangeStreamCoordinator(client, Mock())

    first = coordinator.activate_database("first")
    second = coordinator.activate_database("second")
    same_first = coordinator.activate_database("first")

    try:
        assert first is not second
        assert first is same_first
        assert _is_healthy(first) is True
        assert _is_healthy(second) is True
    finally:
        coordinator.close()

    assert _is_healthy(first) is False
    assert _is_healthy(second) is False
