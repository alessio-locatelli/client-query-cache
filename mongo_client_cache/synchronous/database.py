from __future__ import annotations

from typing import override

import bson
from pymongo import MongoClient, WriteConcern, database
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import _ServerMode
from pymongo.synchronous.collection import Collection
from pymongo.typings import _DocumentType, _DocumentTypeArg

from mongo_client_cache.cache import DatabaseCache
from mongo_client_cache.synchronous.collection import CachedCollection


class CachedDatabase(database.Database):
    @override
    def __init__(
        self,
        client: MongoClient[_DocumentType],
        name: str,
        codec_options: bson.CodecOptions[_DocumentTypeArg] | None = None,
        read_preference: _ServerMode | None = None,
        write_concern: WriteConcern | None = None,
        read_concern: ReadConcern | None = None,
    ) -> None:
        super().__init__(
            client, name, codec_options, read_preference, write_concern, read_concern
        )
        db_cache_config = client._cache_config[name]
        self.client._client_side_databases[name] = DatabaseCache(
            self, db_cache_config
        )
        self.__cached_collections = {collection_config.collection_name for collection_config in db_cache_config}
    
    @property
    def _cached_collections(self) -> set[str]:
        return self.__cached_collections

    @override
    def __getitem__(self, name: str) -> CachedCollection | Collection:
        if name not in self._cached_collections:
            return Collection(self, name)
        return CachedCollection(self, name)
