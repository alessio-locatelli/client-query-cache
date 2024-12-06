from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import cast, override

import bson
from pymongo import MongoClient, WriteConcern, database
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import _ServerMode
from pymongo.synchronous.collection import Collection
from pymongo.typings import _DocumentType, _DocumentTypeArg

from mongo_client_cache._types import CollectionName
from mongo_client_cache.synchronous.collection import CachedCollection
from mongo_client_cache.synchronous.mongo_client import CachedMongoClient


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
        self.__cached_collections: dict[
            CollectionName, Callable[..., CachedCollection]
        ] = {
            collection_config.collection_name: partial(
                CachedCollection,
                self,
                name,
                watch_change_stream=collection_config.watch_change_stream,
            )
            for collection_config in cast(CachedMongoClient, client)._cache_config[name]
        }

    @property
    def _cached_collections(
        self,
    ) -> dict[CollectionName, Callable[..., CachedCollection]]:
        return self.__cached_collections

    @override
    def __getitem__(self, name: str) -> CachedCollection | Collection:
        try:
            return self._cached_collections[name]()
        except KeyError:
            return Collection(self, name)
