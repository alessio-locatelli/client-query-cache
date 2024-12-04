from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, override

import pymongo
from bson.codec_options import TypeRegistry
from pymongo.synchronous.database import Database
from pymongo.typings import _DocumentType

from mongo_client_cache.cache import DatabaseCache
from mongo_client_cache.synchronous.database import CachedDatabase
from mongo_client_cache.types import ClientSideCacheConfig, DatabaseName

if TYPE_CHECKING:
    MIXIN_BASE = pymongo.MongoClient
else:
    MIXIN_BASE = object


class CacheMixin(MIXIN_BASE):
    @override
    def __init__(
        self,
        host: str | Sequence[str] | None = None,
        port: int | None = None,
        document_class: type[_DocumentType] | None = None,
        tz_aware: bool | None = None,
        connect: bool | None = None,
        type_registry: TypeRegistry | None = None,
        *,
        cache_config: ClientSideCacheConfig,
        **kwargs: Any,
    ) -> None:
        """
        By default, all collections are cached and watched for changes.
        Use `CollectionConfig` to change the options for specific collections.
        """
        super().__init__(
            host, port, document_class, tz_aware, connect, type_registry, **kwargs
        )
        self.__cache_config = cache_config
        self.__client_side_databases: dict[DatabaseName, DatabaseCache] = {}

    @property
    def _client_side_databases(self):
        return self.__client_side_databases

    @property
    def _cache_config(self):
        return self.__cache_config

    @override
    def __getitem__(self, name: str) -> CachedDatabase | Database:
        if name not in self._cache_config:
            return Database(self, name)
        return CachedDatabase(self, name)


class CachedMongoClient(CacheMixin, pymongo.MongoClient): ...
