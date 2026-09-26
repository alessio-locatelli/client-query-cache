from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self

from mongo_client_cache._core.collection_metadata import (
    CollectionMetadata,
    CollectionMetadataCache,
)
from mongo_client_cache._core.manager import CacheCore
from mongo_client_cache._core.unique_keys import (
    UniqueKeyMetadata,
    UniqueKeyMetadataCache,
    discover_unique_keys,
)
from mongo_client_cache.synchronous.database import CachedDatabase
from mongo_client_cache.synchronous.streams import ChangeStreamCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pymongo import MongoClient

    from mongo_client_cache._core.collection_metadata import CollectionProbeResult
    from mongo_client_cache._core.keys import NamespaceId
    from mongo_client_cache._core.manager import CacheCoreConfig
    from mongo_client_cache._core.unique_keys import UniqueKeyDefinition


class CacheManager[DocumentType: Mapping[str, Any]]:
    __slots__ = ("_cache", "_client", "_coordinator", "_metadata", "_unique_keys")

    def __init__(
        self,
        client: MongoClient[DocumentType],
        *,
        cache_config: CacheCoreConfig | None = None,
    ) -> None:
        self._client = client
        self._cache = CacheCore(cache_config)
        self._coordinator = ChangeStreamCoordinator(client, self._cache)
        self._metadata = CollectionMetadataCache()
        self._unique_keys = UniqueKeyMetadataCache()

    @property
    def client(self) -> MongoClient[DocumentType]:
        return self._client

    @property
    def cache_core(self) -> CacheCore:
        return self._cache

    def ensure_cache_eligible(
        self,
        namespace: NamespaceId,
        collection_probe: Callable[[], CollectionProbeResult | None],
    ) -> bool:
        self._coordinator.activate_database(namespace.database)
        if not self._cache.is_database_available(namespace.database):
            return False
        current_epoch = self._cache.current_epoch(namespace)
        cached = self._metadata.get(namespace)
        if cached is None or cached.checked_epoch != current_epoch:
            probe_result = collection_probe()
            if probe_result is None:
                return False
            cached = CollectionMetadata(
                checked_epoch=current_epoch,
                is_cacheable=probe_result.is_cacheable,
                default_collation=probe_result.default_collation,
            )
            self._metadata.put(namespace, cached)
        return cached.is_cacheable

    def default_collation_for(self, namespace: NamespaceId) -> Mapping[str, Any] | None:
        cached = self._metadata.get(namespace)
        return cached.default_collation if cached is not None else None

    def unique_keys_for(
        self,
        namespace: NamespaceId,
        list_indexes: Callable[[], Sequence[Mapping[str, Any]] | None],
    ) -> tuple[UniqueKeyDefinition, ...]:
        current_generation = self._cache.current_index_generation(namespace)
        cached = self._unique_keys.get(namespace)
        if cached is None or cached.checked_index_generation != current_generation:
            index_specs = list_indexes()
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

    def close(self) -> None:
        self._coordinator.close()
        self._cache.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()
