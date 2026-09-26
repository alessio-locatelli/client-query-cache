from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from client_query_cache.asynchronous.collection import CachedCollection

if TYPE_CHECKING:
    from pymongo.asynchronous.database import AsyncDatabase

    from client_query_cache.asynchronous.manager import CacheManager


class CachedDatabase[DocumentType: Mapping[str, Any]]:
    __slots__ = ("_database", "_manager")

    def __init__(
        self, manager: CacheManager[DocumentType], database: AsyncDatabase[DocumentType]
    ) -> None:
        self._manager = manager
        self._database = database

    @property
    def manager(self) -> CacheManager[DocumentType]:
        return self._manager

    @property
    def name(self) -> str:
        return self._database.name

    @property
    def raw(self) -> AsyncDatabase[DocumentType]:
        return self._database

    def __getitem__(self, name: str) -> CachedCollection[DocumentType]:
        return CachedCollection(self, self._database[name])
