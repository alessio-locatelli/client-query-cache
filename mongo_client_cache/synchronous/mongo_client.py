from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, override

import pymongo
from bson.codec_options import TypeRegistry
from pymongo.synchronous.database import Database
from pymongo.typings import _DocumentType

from mongo_client_cache.logger import logger
from mongo_client_cache.synchronous.database import CachedDatabase

if TYPE_CHECKING:
    from mongo_client_cache._types import ClientSideCacheConfig, DatabaseName

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
        self.__cached_databases: dict[DatabaseName, CachedDatabase] = {
            db_name: CachedDatabase(self, db_name) for db_name in cache_config
        }

    @property
    def _cached_databases(self) -> dict[DatabaseName, CachedDatabase]:
        return self.__cached_databases

    @property
    def _cache_config(self) -> ClientSideCacheConfig:
        return self.__cache_config

    @override
    def __getitem__(self, name: str) -> CachedDatabase | Database:
        try:
            return self._cached_databases[name]
        except KeyError:
            return Database(self, name)

    @override
    def close(self) -> None:
        logger.debug(f"Closing '{self}'...")
        for db in self._cached_databases.values():
            for coll in db._cached_collections.values():
                logger.debug(
                    f"Asking '{coll._cache._collection.name}' "
                    + "to stop watching the change stream..."
                )
                if not coll._cache.watch_change_stream:
                    continue
                coll._cache.stop_watching = True
                coll._cache.watch_stopped.wait(3)
        super().close()


class CachedMongoClient(CacheMixin, pymongo.MongoClient): ...
