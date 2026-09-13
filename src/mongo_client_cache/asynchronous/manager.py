from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import TYPE_CHECKING, Any, Self

from mongo_client_cache._core.collection_metadata import (
    CollectionMetadata,
    CollectionMetadataCache,
)
from mongo_client_cache._core.manager import CacheCore
from mongo_client_cache.asynchronous.database import CachedDatabase
from mongo_client_cache.asynchronous.streams import ChangeStreamCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo import AsyncMongoClient

    from mongo_client_cache._core.keys import NamespaceId
    from mongo_client_cache._core.manager import CacheCoreConfig


class CacheManager[DocumentType: Mapping[str, Any]]:
    __slots__ = ("_cache", "_client", "_coordinator", "_metadata")

    def __init__(
        self,
        client: AsyncMongoClient[DocumentType],
        *,
        cache_config: CacheCoreConfig | None = None,
    ) -> None:
        self._client = client
        self._cache = CacheCore(cache_config)
        self._coordinator = ChangeStreamCoordinator(client, self._cache)
        self._metadata = CollectionMetadataCache()

    @property
    def client(self) -> AsyncMongoClient[DocumentType]:
        return self._client

    @property
    def cache_core(self) -> CacheCore:
        return self._cache

    async def ensure_cache_eligible(
        self,
        namespace: NamespaceId,
        is_view_check: Callable[[], Awaitable[bool | None]],
    ) -> bool:
        await self._coordinator.activate_database(namespace.database)
        if not self._cache.is_database_available(namespace.database):
            return False
        current_epoch = self._cache.current_epoch(namespace)
        cached = self._metadata.get(namespace)
        if cached is None or cached.checked_epoch != current_epoch:
            is_view = await is_view_check()
            if is_view is None:
                return False
            cached = CollectionMetadata(checked_epoch=current_epoch, is_view=is_view)
            self._metadata.put(namespace, cached)
        return not cached.is_view

    def __getitem__(self, name: str) -> CachedDatabase[DocumentType]:
        return CachedDatabase(self, self._client[name])

    async def close(self) -> None:
        await self._coordinator.close()
        self._cache.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()
