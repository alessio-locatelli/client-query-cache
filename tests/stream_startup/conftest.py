from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from client_query_cache import CacheManager
from client_query_cache._core.errors import StreamLifecycleError
from client_query_cache._core.manager import CacheCore
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from client_query_cache.asynchronous.streams import (
    ChangeStreamCoordinator as AsyncCoordinator,
)
from client_query_cache.asynchronous.streams import (
    DatabaseStreamSupervisor as AsyncSupervisor,
)
from client_query_cache.synchronous.streams import (
    ChangeStreamCoordinator,
    DatabaseStreamSupervisor,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from tests.stream_startup.helpers import (
    GatedAsyncStream,
    GatedSyncStream,
    Publication,
    ShutdownOwner,
    StartupHarness,
)


@pytest.fixture(
    params=[(False, False), (True, False), (False, True), (True, True)],
    ids=["sync-coordinator", "async-coordinator", "sync-manager", "async-manager"],
)
async def startup(
    request: pytest.FixtureRequest,
) -> AsyncIterator[StartupHarness]:
    client = Mock()
    cache = CacheCore()
    is_async, is_manager = request.param
    owner: ShutdownOwner
    if is_manager:
        owner = AsyncCacheManager(client) if is_async else CacheManager(client)
        coordinator = owner._coordinator
        cache = owner.cache_core
    else:
        coordinator = (
            AsyncCoordinator(client, cache)
            if is_async
            else ChangeStreamCoordinator(client, cache)
        )
        owner = coordinator
    harness = StartupHarness(
        coordinator,
        owner,
        cache,
        client,
        threading.Event(),
        threading.Event(),
        threading.Event(),
        threading.Event(),
        [],
    )
    yield harness
    harness.release.set()
    harness.cleanup_release.set()
    await harness.close()


@pytest.fixture
async def pending_startup(
    startup: StartupHarness,
) -> AsyncIterator[asyncio.Task[object]]:
    pending = startup.database("pending", [startup.stream()], paused=True)
    healthy = startup.database("healthy", [startup.stream()])
    startup.client.__getitem__ = Mock(
        side_effect={"pending": pending, "healthy": healthy}.__getitem__
    )
    activation = asyncio.create_task(startup.activate())
    assert await asyncio.to_thread(startup.entered.wait, 5)
    yield activation
    startup.release.set()
    try:
        await activation
    except StreamLifecycleError:
        pass
    except asyncio.CancelledError:
        pass


@pytest.fixture
async def gated_cleanup(
    startup: StartupHarness,
) -> AsyncIterator[GatedSyncStream | GatedAsyncStream]:
    stream = startup.stream(gated_cleanup=True)
    assert isinstance(stream, GatedSyncStream | GatedAsyncStream)
    startup.client.__getitem__ = Mock(
        side_effect={
            "pending": startup.database("pending", [stream]),
            "healthy": startup.database("healthy", [startup.stream()]),
        }.__getitem__
    )
    await startup.activate()
    await startup.activate("healthy")
    yield stream
    startup.cleanup_release.set()


@pytest.fixture
async def before_publication(
    startup: StartupHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Publication]:
    startup.client.__getitem__ = Mock(
        return_value=startup.database("pending", [startup.stream()])
    )
    if startup.is_async:
        original_async = AsyncSupervisor.start

        async def start_async(supervisor: AsyncSupervisor) -> None:
            await original_async(supervisor)
            startup.entered.set()
            await asyncio.to_thread(startup.release.wait)

        monkeypatch.setattr(AsyncSupervisor, "start", start_async)
    else:
        original_sync = DatabaseStreamSupervisor.start

        def start_sync(supervisor: DatabaseStreamSupervisor) -> None:
            original_sync(supervisor)
            startup.entered.set()
            assert startup.release.wait(5)

        monkeypatch.setattr(DatabaseStreamSupervisor, "start", start_sync)
    activation = asyncio.create_task(startup.activate())
    assert await asyncio.to_thread(startup.entered.wait, 5)
    yield Publication(startup=startup, activation=activation)
    startup.release.set()
    try:
        await activation
    except StreamLifecycleError:
        pass
    except asyncio.CancelledError:
        pass
