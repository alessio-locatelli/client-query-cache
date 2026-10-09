from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from client_query_cache import CacheManager
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from client_query_cache.asynchronous.streams import (
    ChangeStreamCoordinator as AsyncCoordinator,
)
from client_query_cache.synchronous.streams import (
    ChangeStreamCoordinator,
)
from tests.stream_fakes import AsyncScriptedDatabase as AsyncDatabase
from tests.stream_fakes import AsyncScriptedStream as AsyncStream
from tests.stream_fakes import ScriptedDatabase, ScriptedStream

if TYPE_CHECKING:
    import threading
    from unittest.mock import Mock

    from client_query_cache._core.manager import CacheCore

type ShutdownOwner = (
    CacheManager[dict[str, object]]
    | AsyncCacheManager[dict[str, object]]
    | ChangeStreamCoordinator
    | AsyncCoordinator
)


@dataclass(slots=True)
class StartupHarness:
    coordinator: ChangeStreamCoordinator | AsyncCoordinator
    owner: ShutdownOwner
    cache: CacheCore
    client: Mock
    entered: threading.Event
    release: threading.Event
    cleanup_entered: threading.Event
    cleanup_release: threading.Event
    streams: list[ScriptedStream | AsyncStream]

    @property
    def is_async(self) -> bool:
        return isinstance(self.coordinator, AsyncCoordinator)

    async def activate(self, name: str = "pending") -> object:
        if isinstance(self.coordinator, AsyncCoordinator):
            return await self.coordinator.activate_database(name)
        return await asyncio.to_thread(self.coordinator.activate_database, name)

    async def close(self) -> None:
        if isinstance(self.owner, AsyncCacheManager | AsyncCoordinator):
            await self.owner.close()
        else:
            await asyncio.to_thread(self.owner.close)

    def database(
        self, name: str, script: list[object], *, paused: bool = False
    ) -> object:
        if self.is_async:

            async def pause(_index: int) -> None:
                self.entered.set()
                await asyncio.to_thread(self.release.wait)

            return AsyncDatabase(name, script, before_watch=pause if paused else None)

        def pause_sync(_index: int) -> None:
            self.entered.set()
            assert self.release.wait(5)

        return ScriptedDatabase(
            name, script, before_watch=pause_sync if paused else None
        )

    def stream(self, *, gated_cleanup: bool = False) -> ScriptedStream | AsyncStream:
        stream: ScriptedStream | AsyncStream
        if self.is_async:
            stream = GatedAsyncStream(self) if gated_cleanup else AsyncStream([])
        else:
            stream = GatedSyncStream(self) if gated_cleanup else ScriptedStream([])
        self.streams.append(stream)
        return stream


class GatedSyncStream(ScriptedStream):
    __slots__ = ("close_calls", "harness")

    def __init__(self, harness: StartupHarness) -> None:
        super().__init__([])
        self.harness = harness
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        self.harness.cleanup_entered.set()
        assert self.harness.cleanup_release.wait(5)
        super().close()


class GatedAsyncStream(AsyncStream):
    __slots__ = ("close_calls", "harness")

    def __init__(self, harness: StartupHarness) -> None:
        super().__init__([])
        self.harness = harness
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1
        self.harness.cleanup_entered.set()
        await asyncio.to_thread(self.harness.cleanup_release.wait)
        await super().close()


class Publication(TypedDict):
    startup: StartupHarness
    activation: asyncio.Task[object]
