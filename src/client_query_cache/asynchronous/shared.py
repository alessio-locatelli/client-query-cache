from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, override

from client_query_cache._core.errors import CacheClosedError
from client_query_cache._shared.adapters import (
    AsyncSharedCachedCollection as _SharedCachedCollection,
)
from client_query_cache._shared.adapters import (
    AsyncSharedCachedDatabase as _SharedCachedDatabase,
)
from client_query_cache._shared.adapters import (
    AsyncSharedCacheManager as _SharedCacheManager,
)
from client_query_cache._shared.attachment import (
    AsyncEndpoint,
    AsyncLocalIndex,
    attachment_unavailable,
)
from client_query_cache.asynchronous.streams import _join_cleanup

if TYPE_CHECKING:
    from pymongo import AsyncMongoClient
    from pymongo.asynchronous.collection import AsyncCollection

    from client_query_cache.shared import SharedCacheConnection


class SharedCachedCollection[DocumentType: Mapping[str, Any]](
    _SharedCachedCollection[DocumentType]
):
    __slots__ = ()


class SharedCacheManager[DocumentType: Mapping[str, Any]](
    _SharedCacheManager[DocumentType]
):
    """Use an async context or await ``attach`` before reading."""

    __slots__ = ("_attached", "_cleanup", "_loop")

    def __init__(
        self, client: AsyncMongoClient[DocumentType], connection: SharedCacheConnection
    ) -> None:
        super().__init__(client, AsyncEndpoint(connection._attachment))
        self._attached = False
        self._cleanup: asyncio.Task[None] | None = None
        self._loop = asyncio.get_running_loop()

    @classmethod
    async def attach(
        cls, client: AsyncMongoClient[DocumentType], connection: SharedCacheConnection
    ) -> Self:
        return await cls(client, connection).__aenter__()

    @override
    def _check_open(self) -> None:
        super()._check_open()
        self._check_loop()
        if not self._attached:
            raise CacheClosedError(
                "enter the async context or await attach before reading"
            )

    def _check_loop(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise CacheClosedError("shared manager belongs to another event loop")

    @override
    def __getitem__(self, name: str) -> SharedCachedDatabase[DocumentType]:
        self._check_open()
        return SharedCachedDatabase(self, self.client[name])

    @override
    def get_cached_collection(
        self, collection: AsyncCollection[DocumentType]
    ) -> SharedCachedCollection[DocumentType]:
        self._check_open()
        if collection.database.client is not self.client:
            raise ValueError("collection belongs to a different client")
        return SharedCachedCollection(
            SharedCachedDatabase(self, collection.database), collection
        )

    async def __aenter__(self) -> Self:
        self._check_loop()
        super()._check_open()
        if not self._attached:
            try:  # noqa: PLW0717 - Close every partial attachment on failure or cancellation.
                self.endpoint = await AsyncEndpoint.attach(
                    self.endpoint.config, require_owner=False
                )
                try:
                    if self.endpoint.connected:
                        self.local = await AsyncLocalIndex.attach(self.endpoint.config)
                except OSError as error:
                    if not attachment_unavailable(error):
                        raise
                self._reattach = self.local is None
            except BaseException:
                await self.close()
                raise
            self._attached = True
        return self

    @override
    async def close(self) -> None:
        self._check_loop()
        self.endpoint._check_owner()
        if self._cleanup is None:
            self._closed = True
            self._cleanup = asyncio.create_task(super().close())
        await _join_cleanup(self._cleanup)

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()


class SharedCachedDatabase[DocumentType: Mapping[str, Any]](
    _SharedCachedDatabase[DocumentType]
):
    __slots__ = ()

    @override
    def __getitem__(self, name: str) -> SharedCachedCollection[DocumentType]:
        assert isinstance(self.shared, SharedCacheManager)
        return self.shared.get_cached_collection(self._database[name])
