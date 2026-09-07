from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pymongo.asynchronous.collection import AsyncCollection

    from mongo_client_cache.asynchronous.database import CachedDatabase


class CachedCollection[DocumentType: Mapping[str, Any]]:
    __slots__ = ("_collection", "_database")

    def __init__(
        self,
        database: CachedDatabase[DocumentType],
        collection: AsyncCollection[DocumentType],
    ) -> None:
        self._database = database
        self._collection = collection

    @property
    def database(self) -> CachedDatabase[DocumentType]:
        return self._database

    @property
    def name(self) -> str:
        return self._collection.name

    @property
    def raw(self) -> AsyncCollection[DocumentType]:
        return self._collection
