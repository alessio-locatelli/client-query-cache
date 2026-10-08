from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypedDict

import pytest

from client_query_cache import StreamHealthStatus
from client_query_cache._core.errors import StreamLifecycleError
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from client_query_cache.asynchronous.streams import (
    ChangeStreamCoordinator as AsyncCoordinator,
)
from client_query_cache.asynchronous.streams import (
    DatabaseStreamSupervisor as AsyncSupervisor,
)
from tests.stream_fakes import AsyncScriptedDatabase as AsyncDatabase
from tests.stream_fakes import AsyncScriptedStream as AsyncStream
from tests.stream_fakes import as_async_database

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from tests.stream_startup.helpers import (
        GatedAsyncStream,
        Publication,
        StartupHarness,
    )


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "startup",
    [(True, False), (True, True)],
    indirect=True,
    ids=["coordinator", "manager"],
)
async def test_async_close_defers_repeated_cancellation_and_shares_cleanup(
    startup: StartupHarness,
    gated_cleanup: GatedAsyncStream,
) -> None:
    closing = asyncio.create_task(startup.close())
    assert await asyncio.to_thread(startup.cleanup_entered.wait, 5)
    assert not startup.cache.is_database_available("healthy")
    closing.cancel()
    await asyncio.sleep(0)
    closing.cancel()
    concurrent = asyncio.create_task(startup.close())
    await asyncio.sleep(0)
    assert not closing.done()
    assert not concurrent.done()
    assert not gated_cleanup._closed_event.is_set()
    startup.cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await concurrent
    await startup.close()
    assert gated_cleanup.closed
    assert gated_cleanup.close_calls == 1
    assert all(stream.closed for stream in startup.streams)
    assert isinstance(startup.coordinator, AsyncCoordinator)
    assert startup.coordinator._shutdown_task is not None
    assert startup.coordinator._shutdown_task.done()
    if isinstance(startup.owner, AsyncCacheManager):
        assert startup.owner.snapshot().lifecycle == "closed"


@pytest.fixture
def interrupted_cleanup(
    before_publication: Publication,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Publication]:
    harness = before_publication["startup"]
    original_close = AsyncStream.close

    async def close(stream: AsyncStream) -> None:
        harness.cleanup_entered.set()
        await asyncio.to_thread(harness.cleanup_release.wait)
        await original_close(stream)

    monkeypatch.setattr(AsyncStream, "close", close)
    yield before_publication
    harness.cleanup_release.set()


@pytest.mark.parametrize(
    "startup",
    [(True, False), (True, True)],
    indirect=True,
    ids=["coordinator", "manager"],
)
async def test_cancelled_owner_finishes_opened_stream_cleanup_before_release(
    interrupted_cleanup: Publication,
) -> None:
    harness = interrupted_cleanup["startup"]
    activation = interrupted_cleanup["activation"]
    activation.cancel()
    assert await asyncio.to_thread(harness.cleanup_entered.wait, 5)
    activation.cancel()
    await asyncio.sleep(0)
    activation.cancel()
    closing = asyncio.create_task(harness.close())
    await asyncio.sleep(0)
    assert not activation.done()
    assert not closing.done()
    harness.cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await activation
    await closing
    assert all(stream.closed for stream in harness.streams)
    assert (
        harness.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.CLOSED
    )


class SupervisorStartup(TypedDict):
    harness: StartupHarness
    supervisor: AsyncSupervisor
    activation: asyncio.Task[None]


@pytest.fixture
async def early_supervisor_stop(
    startup: StartupHarness,
) -> AsyncIterator[SupervisorStartup]:
    database = startup.database("pending", [startup.stream()], paused=True)
    assert isinstance(database, AsyncDatabase)
    supervisor = AsyncSupervisor(as_async_database(database), startup.cache)
    activation = asyncio.create_task(supervisor.start())
    assert await asyncio.to_thread(startup.entered.wait, 5)
    yield SupervisorStartup(
        harness=startup, supervisor=supervisor, activation=activation
    )
    startup.release.set()
    try:
        await activation
    except StreamLifecycleError:
        pass
    await supervisor.stop()


@pytest.mark.parametrize(
    "startup", [(True, False)], indirect=True, ids=["async-supervisor"]
)
async def test_supervisor_cleans_late_stream_after_early_stop_completed(
    early_supervisor_stop: SupervisorStartup,
) -> None:
    supervisor = early_supervisor_stop["supervisor"]
    harness = early_supervisor_stop["harness"]
    await supervisor.stop()
    harness.release.set()
    with pytest.raises(StreamLifecycleError):
        await early_supervisor_stop["activation"]
    assert all(stream.closed for stream in harness.streams)
    assert not harness.cache.is_database_available("pending")
