from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from pymongo.errors import ConnectionFailure

from client_query_cache import CacheManager, StreamHealthStatus
from client_query_cache._core.errors import StreamLifecycleError
from client_query_cache.synchronous.streams import (
    DatabaseStreamSupervisor,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from tests.stream_startup.helpers import (
        GatedAsyncStream,
        GatedSyncStream,
        StartupHarness,
    )


pytestmark = pytest.mark.unit


async def test_close_owns_late_successful_startup(
    startup: StartupHarness, pending_startup: asyncio.Task[object]
) -> None:
    await startup.activate("healthy")
    closing = asyncio.create_task(startup.close())
    await asyncio.sleep(0.01)
    assert (
        startup.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.CLOSED
    )
    assert not startup.cache.is_database_available("healthy")
    assert not closing.done()
    startup.release.set()
    with pytest.raises(StreamLifecycleError):
        await pending_startup
    await closing
    assert all(stream.closed for stream in startup.streams)
    assert startup.coordinator._activations == {}
    assert startup.coordinator._supervisors == {}


@pytest.mark.parametrize(
    "startup",
    [(True, False), (True, True)],
    indirect=True,
    ids=["coordinator", "manager"],
)
async def test_async_close_rejects_already_ready_activation_before_cleanup_runs(
    startup: StartupHarness,
) -> None:
    startup.client.__getitem__ = Mock(
        return_value=startup.database("healthy", [startup.stream()])
    )
    await startup.activate("healthy")
    activation = asyncio.create_task(startup.activate())
    await startup.close()
    with pytest.raises(StreamLifecycleError, match="coordinator is closed"):
        await activation
    assert startup.client.__getitem__.call_count == 1
    assert (
        startup.coordinator.stream_health_snapshot("healthy").status
        is StreamHealthStatus.CLOSED
    )
    assert not startup.cache.is_database_available("healthy")


async def test_all_databases_are_unavailable_before_any_blocked_cleanup(
    startup: StartupHarness,
    gated_cleanup: GatedSyncStream | GatedAsyncStream,
) -> None:
    closing = asyncio.create_task(startup.close())
    assert await asyncio.to_thread(startup.cleanup_entered.wait, 5)
    assert not startup.cache.is_database_available("pending")
    assert not startup.cache.is_database_available("healthy")
    assert not closing.done()
    startup.cleanup_release.set()
    await closing
    assert gated_cleanup.closed


@pytest.fixture
async def late_cleanup(
    startup: StartupHarness,
) -> AsyncIterator[asyncio.Task[object]]:
    stream = startup.stream(gated_cleanup=True)
    startup.client.__getitem__ = Mock(
        return_value=startup.database("pending", [stream], paused=True)
    )
    activation = asyncio.create_task(startup.activate())
    assert await asyncio.to_thread(startup.entered.wait, 5)
    yield activation
    startup.release.set()
    startup.cleanup_release.set()
    try:
        await activation
    except StreamLifecycleError:
        pass


async def test_close_waits_for_late_native_cleanup(
    startup: StartupHarness,
    late_cleanup: asyncio.Task[object],
) -> None:
    closing = asyncio.create_task(startup.close())
    await asyncio.sleep(0.01)
    startup.release.set()
    assert await asyncio.to_thread(startup.cleanup_entered.wait, 5)
    assert not closing.done()
    assert not late_cleanup.done()
    startup.cleanup_release.set()
    with pytest.raises(StreamLifecycleError):
        await late_cleanup
    await closing
    assert all(stream.closed for stream in startup.streams)


@pytest.mark.parametrize(
    "startup",
    [(False, False), (False, True)],
    indirect=True,
    ids=["coordinator", "manager"],
)
async def test_sync_close_callers_join_pending_startup_cleanup(
    startup: StartupHarness,
    late_cleanup: asyncio.Task[object],
) -> None:
    first = asyncio.create_task(startup.close())
    await asyncio.sleep(0.01)
    second = asyncio.create_task(startup.close())
    await asyncio.sleep(0.01)
    assert not first.done()
    assert not second.done()
    assert startup.cache.snapshot().lifecycle == "active"
    startup.release.set()
    assert await asyncio.to_thread(startup.cleanup_entered.wait, 5)
    assert not first.done()
    assert not second.done()
    startup.cleanup_release.set()
    await asyncio.gather(first, second)
    with pytest.raises(StreamLifecycleError):
        await late_cleanup
    await startup.close()
    if isinstance(startup.owner, CacheManager):
        assert startup.owner.snapshot().lifecycle == "closed"


@pytest.fixture
async def failed_pending_startup(
    startup: StartupHarness,
) -> AsyncIterator[asyncio.Task[object]]:
    startup.client.__getitem__ = Mock(
        return_value=startup.database(
            "pending", [ConnectionFailure("watch unavailable")], paused=True
        )
    )
    activation = asyncio.create_task(startup.activate())
    assert await asyncio.to_thread(startup.entered.wait, 5)
    yield activation
    startup.release.set()
    await activation


async def test_failed_startup_after_close_keeps_health_terminal(
    startup: StartupHarness,
    failed_pending_startup: asyncio.Task[object],
) -> None:
    closing = asyncio.create_task(startup.close())
    await asyncio.sleep(0.01)
    startup.release.set()
    assert await failed_pending_startup is None
    await closing
    assert (
        startup.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.CLOSED
    )
    assert startup.coordinator._activations == {}


@pytest.fixture
async def interrupted_startup_during_cleanup(
    startup: StartupHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[asyncio.Task[object]]:
    startup.client.__getitem__ = Mock(
        side_effect={
            "healthy": startup.database("healthy", [startup.stream()]),
            "pending": startup.database(
                "pending", [startup.stream(gated_cleanup=True)]
            ),
        }.__getitem__
    )
    await startup.activate("healthy")
    original = DatabaseStreamSupervisor.start

    def start(supervisor: DatabaseStreamSupervisor) -> None:
        original(supervisor)
        raise ValueError("startup interrupted after allocation")

    monkeypatch.setattr(DatabaseStreamSupervisor, "start", start)
    activation = asyncio.create_task(startup.activate())
    assert await asyncio.to_thread(startup.cleanup_entered.wait, 5)
    yield activation
    startup.cleanup_release.set()
    with pytest.raises(ValueError, match="startup interrupted after allocation"):
        await activation


@pytest.mark.parametrize(
    "startup",
    [(False, False), (False, True)],
    indirect=True,
    ids=["coordinator", "manager"],
)
async def test_sync_close_signals_all_databases_during_owner_cleanup(
    startup: StartupHarness,
    interrupted_startup_during_cleanup: asyncio.Task[object],
) -> None:
    closing = asyncio.create_task(startup.close())
    await asyncio.sleep(0.01)
    assert (
        startup.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.CLOSED
    )
    assert not startup.cache.is_database_available("healthy")
    assert not closing.done()
    startup.cleanup_release.set()
    with pytest.raises(ValueError, match="startup interrupted after allocation"):
        await interrupted_startup_during_cleanup
    await closing
    assert all(stream.closed for stream in startup.streams)
