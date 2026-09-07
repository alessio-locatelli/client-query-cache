from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from mongo_client_cache.asynchronous.database import CachedDatabase

if TYPE_CHECKING:
    from pymongo import AsyncMongoClient


class CacheManager[DocumentType: Mapping[str, Any]]:
    __slots__ = ("_client",)

    def __init__(self, client: AsyncMongoClient[DocumentType]) -> None:
        self._client = client

    @property
    def client(self) -> AsyncMongoClient[DocumentType]:
        return self._client

    def __getitem__(self, name: str) -> CachedDatabase[DocumentType]:
        return CachedDatabase(self, self._client[name])
