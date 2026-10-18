from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, override

from client_query_cache._shared.adapters import (
    SharedCachedCollection as _SharedCachedCollection,
)
from client_query_cache._shared.adapters import (
    SharedCachedDatabase as _SharedCachedDatabase,
)
from client_query_cache._shared.adapters import (
    SharedCacheManager as _SharedCacheManager,
)
from client_query_cache._shared.attachment import (
    LocalIndex,
    SyncEndpoint,
    attachment_unavailable,
)

if TYPE_CHECKING:
    from pymongo import MongoClient
    from pymongo.synchronous.collection import Collection

    from client_query_cache.shared import SharedCacheConnection


class SharedCachedCollection[DocumentType: Mapping[str, Any]](
    _SharedCachedCollection[DocumentType]
):
    __slots__ = ()


class SharedCacheManager[DocumentType: Mapping[str, Any]](
    _SharedCacheManager[DocumentType]
):
    """Attach a worker-owned client to a trusted same-host server."""

    __slots__ = ()

    def __init__(
        self, client: MongoClient[DocumentType], connection: SharedCacheConnection
    ) -> None:
        endpoint = SyncEndpoint(connection._attachment, require_owner=False)
        try:
            local = (
                LocalIndex.attach(connection._attachment)
                if endpoint.connected
                else None
            )
        except OSError as error:
            if not attachment_unavailable(error):
                endpoint.close()
                raise
            local = None
        except BaseException:
            endpoint.close()
            raise
        super().__init__(client, endpoint, local)
        self._reattach = local is None

    @override
    def __getitem__(self, name: str) -> SharedCachedDatabase[DocumentType]:
        self._check_open()
        return SharedCachedDatabase(self, self.client[name])

    @override
    def get_cached_collection(
        self, collection: Collection[DocumentType]
    ) -> SharedCachedCollection[DocumentType]:
        self._check_open()
        if collection.database.client is not self.client:
            raise ValueError("collection belongs to a different client")
        return SharedCachedCollection(
            SharedCachedDatabase(self, collection.database), collection
        )

    def __enter__(self) -> Self:
        self._check_open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class SharedCachedDatabase[DocumentType: Mapping[str, Any]](
    _SharedCachedDatabase[DocumentType]
):
    __slots__ = ()

    @override
    def __getitem__(self, name: str) -> SharedCachedCollection[DocumentType]:
        assert isinstance(self.shared, SharedCacheManager)
        return self.shared.get_cached_collection(self._database[name])
