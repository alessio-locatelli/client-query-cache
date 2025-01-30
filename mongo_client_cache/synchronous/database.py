from __future__ import annotations

from typing import TYPE_CHECKING, override

from pymongo import MongoClient, WriteConcern, database
from pymongo.synchronous.collection import Collection

from mongo_client_cache.synchronous.collection import CachedCollection

if TYPE_CHECKING:
    import bson
    from pymongo.read_concern import ReadConcern
    from pymongo.read_preferences import _ServerMode
    from pymongo.typings import _DocumentType, _DocumentTypeArg

    from mongo_client_cache._types import CollectionName


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
        self.__cached_collections: dict[CollectionName, CachedCollection] = {}

    @property
    def _cached_collections(self) -> dict[CollectionName, CachedCollection]:
        return self.__cached_collections

    @override
    def __getitem__(self, name: str) -> CachedCollection | Collection:
        try:
            self._cached_collections[name] = CachedCollection(
                self,
                name,
                watch_change_stream=self.client._cache_config[self.name][  # type: ignore[arg-type]
                    name
                ].watch_change_stream,
            )
            return self._cached_collections[name]
        except KeyError:
            return Collection(self, name)
