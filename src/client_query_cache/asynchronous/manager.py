from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import TYPE_CHECKING, Any, Self, overload

from client_query_cache._core.collection_metadata import (
    CollectionMetadata,
    CollectionMetadataCache,
)
from client_query_cache._core.manager import CacheCore
from client_query_cache._core.snapshots import BypassReason
from client_query_cache._core.stream_options import (
    DEFAULT_MAX_AWAIT_TIME_MS,
    validate_max_await_time_ms,
)
from client_query_cache._core.unique_keys import (
    UniqueKeyMetadata,
    UniqueKeyMetadataCache,
    discover_unique_keys,
)
from client_query_cache.asynchronous.collection import CachedCollection
from client_query_cache.asynchronous.database import CachedDatabase
from client_query_cache.asynchronous.streams import ChangeStreamCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pymongo import AsyncMongoClient
    from pymongo.asynchronous.collection import AsyncCollection

    from client_query_cache._core.collection_metadata import CollectionProbeResult
    from client_query_cache._core.keys import NamespaceId
    from client_query_cache._core.manager import CacheCoreConfig
    from client_query_cache._core.snapshots import CacheSnapshot
    from client_query_cache._core.stream_cost import StreamCostSnapshot
    from client_query_cache._core.stream_health import StreamHealthSnapshot
    from client_query_cache._core.unique_keys import UniqueKeyDefinition


class CacheManager[DocumentType: Mapping[str, Any]]:
    __slots__ = ("_cache", "_client", "_coordinator", "_metadata", "_unique_keys")

    def __init__(
        self,
        client: AsyncMongoClient[DocumentType],
        *,
        cache_config: CacheCoreConfig | None = None,
        max_await_time_ms: int = DEFAULT_MAX_AWAIT_TIME_MS,
    ) -> None:
        validate_max_await_time_ms(max_await_time_ms)
        self._client = client
        self._cache = CacheCore(cache_config)
        self._coordinator = ChangeStreamCoordinator(
            client, self._cache, max_await_time_ms=max_await_time_ms
        )
        self._metadata = CollectionMetadataCache()
        self._unique_keys = UniqueKeyMetadataCache()

    @property
    def client(self) -> AsyncMongoClient[DocumentType]:
        return self._client

    @property
    def cache_core(self) -> CacheCore:
        return self._cache

    def snapshot(self) -> CacheSnapshot:
        return self._cache.snapshot()

    def stream_health_snapshot(self, database_name: str) -> StreamHealthSnapshot:
        return self._coordinator.stream_health_snapshot(database_name)

    def stream_cost_snapshot(self, database_name: str) -> StreamCostSnapshot:
        return self._cache.stream_cost_snapshot(database_name)

    def active_stream_cost_databases(self) -> list[str]:
        return self._cache.active_stream_cost_databases()

    async def ensure_cache_eligible(
        self,
        namespace: NamespaceId,
        collection_probe: Callable[[], Awaitable[CollectionProbeResult | None]],
    ) -> bool:
        return (
            await self.cache_ineligibility_reason(namespace, collection_probe) is None
        )

    async def cache_ineligibility_reason(
        self,
        namespace: NamespaceId,
        collection_probe: Callable[[], Awaitable[CollectionProbeResult | None]],
    ) -> BypassReason | None:
        await self._coordinator.activate_database(namespace.database)
        if not self._cache.is_database_available(namespace.database):
            return BypassReason.STREAM_UNAVAILABLE
        current_epoch = self._cache.current_epoch(namespace)
        cached = self._metadata.get(namespace)
        if cached is None or cached.checked_epoch != current_epoch:
            probe_result = await collection_probe()
            if probe_result is None:
                return BypassReason.METADATA_UNAVAILABLE
            if probe_result.bypass_reason in {
                BypassReason.MISSING_COLLECTION,
                BypassReason.METADATA_UNAVAILABLE,
            }:
                return probe_result.bypass_reason
            cached = CollectionMetadata(
                checked_epoch=current_epoch,
                bypass_reason=probe_result.bypass_reason,
                default_collation=probe_result.default_collation,
            )
            self._metadata.put(namespace, cached)
        return cached.bypass_reason

    def default_collation_for(self, namespace: NamespaceId) -> Mapping[str, Any] | None:
        cached = self._metadata.get(namespace)
        return cached.default_collation if cached is not None else None

    @overload
    async def unique_keys_for(
        self,
        namespace: NamespaceId,
        list_indexes: Callable[[], Awaitable[Sequence[Mapping[str, Any]] | None]],
    ) -> tuple[UniqueKeyDefinition, ...]: ...

    @overload
    async def unique_keys_for(
        self, namespace: NamespaceId, list_indexes: None = None
    ) -> tuple[UniqueKeyDefinition, ...] | None: ...

    async def unique_keys_for(
        self,
        namespace: NamespaceId,
        list_indexes: Callable[[], Awaitable[Sequence[Mapping[str, Any]] | None]]
        | None = None,
    ) -> tuple[UniqueKeyDefinition, ...] | None:
        current_generation = self._cache.current_index_generation(namespace)
        cached = self._unique_keys.get(namespace)
        if cached is None or cached.checked_index_generation != current_generation:
            if list_indexes is None:
                return None
            index_specs = await list_indexes()
            if index_specs is None:
                return ()
            if self._cache.current_index_generation(namespace) != current_generation:
                return ()
            cached = UniqueKeyMetadata(
                checked_index_generation=current_generation,
                keys=discover_unique_keys(index_specs),
            )
            self._unique_keys.put(namespace, cached)
        return cached.keys

    def __getitem__(self, name: str) -> CachedDatabase[DocumentType]:
        return CachedDatabase(self, self._client[name])

    def cached(
        self, collection: AsyncCollection[DocumentType]
    ) -> CachedCollection[DocumentType]:
        if collection.database.client is not self._client:
            message = (
                f"Collection {collection.full_name!r} belongs to a different client "
                f"than this {type(self).__name__}."
            )
            raise ValueError(message)
        return CachedCollection(CachedDatabase(self, collection.database), collection)

    async def close(self) -> None:
        await self._coordinator.close()
        self._cache.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()
