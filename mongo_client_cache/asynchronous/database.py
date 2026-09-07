from __future__ import annotations

from typing import TYPE_CHECKING

from mongo_client_cache.asynchronous.collection import CachedCollection

if TYPE_CHECKING:
    from pymongo.asynchronous.database import AsyncDatabase

    from mongo_client_cache.asynchronous.manager import CacheManager


class CachedDatabase:
    __slots__ = ("_database", "_manager")

    def __init__(self, manager: CacheManager, database: AsyncDatabase) -> None:
        self._manager = manager
        self._database = database

    @property
    def manager(self) -> CacheManager:
        return self._manager

    @property
    def name(self) -> str:
        return self._database.name

    @property
    def raw(self) -> AsyncDatabase:
        return self._database

    def __getitem__(self, name: str) -> CachedCollection:
        return CachedCollection(self, self._database[name])
