from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from pymongo.errors import ConnectionFailure, OperationFailure

from client_query_cache import StreamHealthStatus
from client_query_cache._core import stream_activation
from client_query_cache.asynchronous.streams import (
    DatabaseStreamSupervisor as AsyncSupervisor,
)
from client_query_cache.synchronous.streams import (
    DatabaseStreamSupervisor,
)
from tests.stream_fakes import AsyncScriptedDatabase as AsyncDatabase
from tests.stream_fakes import ScriptedDatabase

if TYPE_CHECKING:
    from tests.stream_startup.helpers import StartupHarness

pytestmark = pytest.mark.unit


async def test_pending_startup_does_not_block_other_databases_or_competing_reads(
    startup: StartupHarness, pending_startup: asyncio.Task[object]
) -> None:
    assert (
        startup.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.CONNECTING
    )
    for _ in range(5):
        assert await asyncio.wait_for(startup.activate(), 1) is None
    healthy = await asyncio.wait_for(startup.activate("healthy"), 1)
    assert healthy is not None
    assert await asyncio.wait_for(startup.activate("healthy"), 1) is healthy
    assert startup.cache.is_database_available("healthy")
    assert startup.client.__getitem__.call_count == 2
    assert not pending_startup.done()


@pytest.mark.parametrize(
    "failure",
    ["permission", "version", "transient"],
    ids=["permission", "version", "transient"],
)
async def test_initial_failures_have_read_driven_cooldown(
    startup: StartupHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    clock = Mock(return_value=10.0)
    monkeypatch.setattr(stream_activation, "monotonic", clock)
    error = (
        OperationFailure("watch denied", code=13)
        if failure == "permission"
        else ConnectionFailure("startup unavailable")
    )
    database = startup.database("pending", [error, error, startup.stream()])
    if failure == "version":
        database = (
            AsyncDatabase("pending", [], version_array=[7, 0])
            if startup.is_async
            else ScriptedDatabase("pending", [], version_array=[7, 0])
        )
    startup.client.__getitem__ = Mock(return_value=database)
    assert await startup.activate() is None
    first_deadline = startup.coordinator._activations["pending"].retry.deadline
    for _ in range(10):
        assert await startup.activate() is None
    assert startup.client.__getitem__.call_count == 1
    assert (
        startup.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.STARTUP_FAILED
    )
    assert len(caplog.records) == 1
    clock.return_value = first_deadline
    assert await startup.activate() is None
    second_deadline = startup.coordinator._activations["pending"].retry.deadline
    assert 0.1 <= second_deadline - first_deadline <= 0.2
    clock.return_value = second_deadline
    startup.client.__getitem__.return_value = startup.database(
        "pending", [startup.stream()]
    )
    assert await startup.activate() is not None
    assert startup.coordinator._activations == {}
    assert len(caplog.records) == 2


async def test_unexpected_startup_exception_releases_reservation(
    startup: StartupHarness,
) -> None:
    startup.client.__getitem__ = Mock(
        return_value=startup.database(
            "pending", [ValueError("unexpected startup failure"), startup.stream()]
        )
    )
    with pytest.raises(ValueError, match="unexpected startup failure"):
        await startup.activate()
    assert not startup.coordinator._activations["pending"].pending
    assert startup.coordinator._activations["pending"].retry.deadline == 0
    assert (
        startup.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.STARTUP_FAILED
    )
    assert await startup.activate() is not None


@pytest.mark.parametrize(
    "startup",
    [(True, False), (True, True)],
    indirect=True,
    ids=["coordinator", "manager"],
)
async def test_cancelled_activation_can_retry_immediately(
    startup: StartupHarness,
    pending_startup: asyncio.Task[object],
) -> None:
    pending_startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_startup
    assert (
        startup.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.STARTUP_FAILED
    )
    assert startup.coordinator._activations["pending"].retry.deadline == 0
    startup.release.set()
    startup.client.__getitem__ = Mock(
        return_value=startup.database("pending", [startup.stream()])
    )
    assert await startup.activate() is not None


@pytest.fixture
def exception_after_open(
    startup: StartupHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> StartupHarness:
    startup.client.__getitem__ = Mock(
        return_value=startup.database("pending", [startup.stream()])
    )
    if startup.is_async:
        original_async = AsyncSupervisor.start

        async def start_async(supervisor: AsyncSupervisor) -> None:
            await original_async(supervisor)
            raise ValueError("failure after opening stream")

        monkeypatch.setattr(AsyncSupervisor, "start", start_async)
    else:
        original_sync = DatabaseStreamSupervisor.start

        def start_sync(supervisor: DatabaseStreamSupervisor) -> None:
            original_sync(supervisor)
            raise ValueError("failure after opening stream")

        monkeypatch.setattr(DatabaseStreamSupervisor, "start", start_sync)
    return startup


async def test_unexpected_exception_after_open_releases_worker_and_stream(
    exception_after_open: StartupHarness,
) -> None:
    with pytest.raises(ValueError, match="failure after opening stream"):
        await exception_after_open.activate()
    assert all(stream.closed for stream in exception_after_open.streams)
    activation = exception_after_open.coordinator._activations["pending"]
    assert not activation.pending
    assert activation.completion.is_set()
    assert activation.retry.ready()
    supervisor = activation.supervisor
    if isinstance(supervisor, AsyncSupervisor):
        assert supervisor._task is not None
        assert supervisor._task.done()
    else:
        assert supervisor._thread is not None
        assert not supervisor._thread.is_alive()
