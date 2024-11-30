from __future__ import annotations

from typing import override

import bson
from pymongo import MongoClient, WriteConcern, database
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import _ServerMode
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
        client = self._Database__client
        client._client_side_databases[name] = DatabaseCache(
            self, client._client_side_cache_config.get(name)
        )

    @override
    def __getitem__(self, name: str) -> CachedCollection:
        return CachedCollection(self, name)
