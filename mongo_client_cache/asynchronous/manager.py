from __future__ import annotations

from typing import TYPE_CHECKING

from mongo_client_cache.asynchronous.database import CachedDatabase

if TYPE_CHECKING:
    from pymongo import AsyncMongoClient


class CacheManager:
    __slots__ = ("_client",)

    def __init__(self, client: AsyncMongoClient) -> None:
        self._client = client

    @property
    def client(self) -> AsyncMongoClient:
        return self._client

    def __getitem__(self, name: str) -> CachedDatabase:
        return CachedDatabase(self, self._client[name])
