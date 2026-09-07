from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pymongo.asynchronous.collection import AsyncCollection

    from mongo_client_cache.asynchronous.database import CachedDatabase


class CachedCollection:
    __slots__ = ("_collection", "_database")

    def __init__(self, database: CachedDatabase, collection: AsyncCollection) -> None:
        self._database = database
        self._collection = collection

    @property
    def database(self) -> CachedDatabase:
        return self._database

    @property
    def name(self) -> str:
        return self._collection.name

    @property
    def raw(self) -> AsyncCollection:
        return self._collection
