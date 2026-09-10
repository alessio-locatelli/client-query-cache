from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock

import pytest
from pymongo.errors import OperationFailure

from mongo_client_cache._core.errors import StreamLifecycleError, StreamStartupError
from mongo_client_cache._core.keys import NamespaceId
from mongo_client_cache._core.stream_health import RetryBackoff
from mongo_client_cache.asynchronous.streams import (
    ChangeStreamCoordinator,
    DatabaseStreamSupervisor,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pymongo.asynchronous.database import AsyncDatabase

pytestmark = pytest.mark.unit

_FAST_BACKOFF = RetryBackoff(base_seconds=0.001, max_seconds=0.002)


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
            raise StopAsyncIteration
        item = self._events.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, dict)
        self.resume_token = item.get("_id", self.resume_token)
        return item

    async def close(self) -> None:
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
    # See the sync test module's `_is_healthy` for why this indirection
    # avoids a false-positive mypy "unreachable" on a later opposite assert.
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
    except TimeoutError:
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
async def test_start_fails_closed(
    version_array: list[int], script: list[object], expected_watch_calls: int
) -> None:
    database = _FakeDatabase("db", script, version_array=version_array)
    supervisor = DatabaseStreamSupervisor(_as_database(database), Mock())

    with pytest.raises(StreamStartupError):
        await supervisor.start()

    assert len(database.watch_calls) == expected_watch_calls
    assert supervisor.healthy is False


async def test_start_becomes_healthy_and_routes_events() -> None:
    cache = Mock()
    stream = _ScriptedStream([_insert_event()])
    database = _FakeDatabase("db", [stream])
    supervisor = DatabaseStreamSupervisor(_as_database(database), cache)

    await supervisor.start()
    try:
        assert _is_healthy(supervisor) is True
        await _wait_until(lambda: cache.record_write.called)
        cache.record_write.assert_called_once_with(NamespaceId("db", "coll"), "doc-1")
    finally:
        await supervisor.stop()

    assert _is_healthy(supervisor) is False
    assert stream.closed is True


async def test_stop_cancels_the_background_task_and_closes_the_stream() -> None:
    stream = _ScriptedStream([])
    database = _FakeDatabase("db", [stream])
    supervisor = DatabaseStreamSupervisor(_as_database(database), Mock())

    await supervisor.start()
    task = supervisor._task
    assert task is not None
    assert not task.done()

    await supervisor.stop()

    assert task.done()
    assert task.cancelled()
    assert stream.closed is True


async def test_reconnects_using_the_saved_resume_token() -> None:
    stream1 = _ScriptedStream(
        [_insert_event("tok-1"), OperationFailure("blip", code=1)]
    )
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = DatabaseStreamSupervisor(
        _as_database(database), Mock(), backoff=_FAST_BACKOFF
    )
    watch_calls_after_reconnect = 2

    await supervisor.start()
    try:
        await _wait_until(
            lambda: len(database.watch_calls) == watch_calls_after_reconnect
        )
        assert database.watch_calls[1]["resume_after"] == {"tok": "tok-1"}
        assert "start_after" not in database.watch_calls[1]
        await _wait_until(lambda: supervisor.healthy)
        await _wait_until(lambda: stream1.closed)
    finally:
        await supervisor.stop()


async def test_start_raises_when_called_more_than_once() -> None:
    database = _FakeDatabase("db", [_ScriptedStream([])])
    supervisor = DatabaseStreamSupervisor(_as_database(database), Mock())

    await supervisor.start()
    try:
        with pytest.raises(StreamLifecycleError):
            await supervisor.start()
    finally:
        await supervisor.stop()


async def test_unexpected_stream_closure_triggers_reconnect() -> None:
    stream1 = _ScriptedStream([StopAsyncIteration()])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = DatabaseStreamSupervisor(
        _as_database(database), Mock(), backoff=_FAST_BACKOFF
    )
    watch_calls_after_recovery = 2

    await supervisor.start()
    try:
        await _wait_until(
            lambda: len(database.watch_calls) == watch_calls_after_recovery
        )
        await _wait_until(lambda: supervisor.healthy)
    finally:
        await supervisor.stop()


async def test_clears_known_namespaces_when_resume_history_is_lost() -> None:
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

    await supervisor.start()
    try:
        await _wait_until(
            lambda: len(database.watch_calls) == watch_calls_after_recovery
        )
        cache.namespaces_for_database.assert_called_once_with("db")
        cache.clear_namespace.assert_called_once_with(NamespaceId("db", "coll"))
        assert "resume_after" not in database.watch_calls[2]
        assert "start_after" not in database.watch_calls[2]
        await _wait_until(lambda: supervisor.healthy)
    finally:
        await supervisor.stop()


async def test_reopens_with_start_after_following_an_invalidate_event() -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    invalidate_event = {"_id": {"tok": "inv"}, "operationType": "invalidate"}
    stream1 = _ScriptedStream([_insert_event("tok-1"), invalidate_event])
    database = _FakeDatabase("db", [stream1, _ScriptedStream([])])
    supervisor = DatabaseStreamSupervisor(
        _as_database(database), cache, backoff=_FAST_BACKOFF
    )
    watch_calls_after_reopen = 2

    await supervisor.start()
    try:
        await _wait_until(lambda: len(database.watch_calls) == watch_calls_after_reopen)
        assert database.watch_calls[1]["start_after"] == {"tok": "inv"}
        assert "resume_after" not in database.watch_calls[1]
        cache.namespaces_for_database.assert_called_once_with("db")
        cache.clear_namespace.assert_called_once_with(NamespaceId("db", "coll"))
        await _wait_until(lambda: supervisor.healthy)
    finally:
        await supervisor.stop()


async def test_supervisor_is_unhealthy_while_reconnecting() -> None:
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
    supervisor = DatabaseStreamSupervisor(
        _as_database(database), Mock(), backoff=_FAST_BACKOFF
    )

    await supervisor.start()
    try:
        await _wait_until(reached_second_watch.is_set)
        assert supervisor.healthy is False

        release.set()
        await _wait_until(lambda: supervisor.healthy)
    finally:
        release.set()
        await supervisor.stop()


async def test_coordinator_starts_one_independent_stream_per_active_database() -> None:
    databases = {
        "first": _FakeDatabase("first", [_ScriptedStream([])]),
        "second": _FakeDatabase("second", [_ScriptedStream([])]),
    }
    client = Mock()
    client.__getitem__ = Mock(side_effect=databases.__getitem__)
    coordinator = ChangeStreamCoordinator(client, Mock())

    first = await coordinator.activate_database("first")
    second = await coordinator.activate_database("second")
    same_first = await coordinator.activate_database("first")

    try:
        assert first is not second
        assert first is same_first
        assert _is_healthy(first) is True
        assert _is_healthy(second) is True
    finally:
        await coordinator.close()

    assert _is_healthy(first) is False
    assert _is_healthy(second) is False
