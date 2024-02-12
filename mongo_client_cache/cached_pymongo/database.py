import bson
from pymongo import MongoClient, WriteConcern, database
from pymongo.read_concern import ReadConcern
from pymongo.typings import _DocumentType, _DocumentTypeArg
from pymongo.read_preferences import _ServerMode
from mongo_client_cache.backends.base import ClientSideDatabase, CollectionConfig
from mongo_client_cache.backends.exceptions import ReservedAttributeError

from mongo_client_cache.cached_pymongo.collection import CachedCollection


class CachedDatabase(database.Database):
    def __init__(
        self,
        client: MongoClient[_DocumentType],
        name: str,
        codec_options: bson.CodecOptions[_DocumentTypeArg] | None = None,
        read_preference: _ServerMode | None = None,
        write_concern: WriteConcern | None = None,
        read_concern: ReadConcern | None = None,
        *,
        cache_config_per_collection: list[CollectionConfig] | None = None,
    ) -> None:
        super().__init__(
            client, name, codec_options, read_preference, write_concern, read_concern
        )
        self.local_database = ClientSideDatabase(name, cache_config_per_collection)

    def __getitem__(self, name: str) -> CachedCollection:
        if name == "local_database":
            raise ReservedAttributeError(name)
        return CachedCollection(self, name)
