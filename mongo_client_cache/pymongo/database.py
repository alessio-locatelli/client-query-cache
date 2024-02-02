from pymongo import database

from mongo_client_cache.pymongo.collection import CachedCollection


class CachedDatabase(database.Database):
    def __getitem__(self, name: str) -> CachedCollection:
        return CachedCollection(self, name)
