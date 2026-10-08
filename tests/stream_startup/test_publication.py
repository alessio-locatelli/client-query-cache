from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from client_query_cache import StreamHealthStatus
from client_query_cache._core.errors import StreamLifecycleError
from client_query_cache._core.stream_health import StreamHealthRegistry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from tests.stream_startup.helpers import Publication, StartupHarness


pytestmark = pytest.mark.unit


async def test_unpublished_native_success_remains_connecting(
    before_publication: Publication,
) -> None:
    harness = before_publication["startup"]
    assert harness.cache.is_database_available("pending")
    assert (
        harness.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.CONNECTING
    )
    assert await harness.activate() is None
    harness.release.set()
    await before_publication["activation"]
    assert (
        harness.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.HEALTHY
    )


async def test_close_wins_after_native_success_before_publication(
    before_publication: Publication,
) -> None:
    harness = before_publication["startup"]
    closing = asyncio.create_task(harness.close())
    await asyncio.sleep(0.01)
    assert (
        harness.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.CLOSED
    )
    assert not harness.cache.is_database_available("pending")
    harness.release.set()
    with pytest.raises(StreamLifecycleError):
        await before_publication["activation"]
    await closing
    assert all(stream.closed for stream in harness.streams)


@pytest.fixture
def publication_callback(
    startup: StartupHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[StartupHarness]:
    original = StreamHealthRegistry.record_starting

    def record(
        registry: StreamHealthRegistry,
        name: str,
        health: Callable[[], StreamHealthStatus],
    ) -> None:
        startup.entered.set()
        assert startup.release.wait(5)
        original(registry, name, health)

    monkeypatch.setattr(StreamHealthRegistry, "record_starting", record)
    startup.client.__getitem__ = Mock(
        return_value=startup.database("pending", [startup.stream()])
    )
    yield startup
    startup.release.set()


def _inspect_publication(harness: StartupHarness) -> StreamHealthStatus:
    assert harness.entered.wait(5)
    try:
        assert "pending" in harness.coordinator._supervisors
        return harness.coordinator.stream_health_snapshot("pending").status
    finally:
        harness.release.set()


async def test_health_remains_connecting_between_registration_and_callback(
    publication_callback: StartupHarness,
) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        observation = executor.submit(_inspect_publication, publication_callback)
        assert await publication_callback.activate() is not None
        assert observation.result(timeout=5) is StreamHealthStatus.CONNECTING
    assert (
        publication_callback.coordinator.stream_health_snapshot("pending").status
        is StreamHealthStatus.HEALTHY
    )
