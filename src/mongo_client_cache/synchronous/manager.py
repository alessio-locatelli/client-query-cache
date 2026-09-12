from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from mongo_client_cache.synchronous.database import CachedDatabase

if TYPE_CHECKING:
    from pymongo import MongoClient


class CacheManager[DocumentType: Mapping[str, Any]]:
    __slots__ = ("_client",)

    def __init__(self, client: MongoClient[DocumentType]) -> None:
        self._client = client

    @property
    def client(self) -> MongoClient[DocumentType]:
        return self._client

    def __getitem__(self, name: str) -> CachedDatabase[DocumentType]:
        return CachedDatabase(self, self._client[name])
