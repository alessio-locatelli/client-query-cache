from pymongo import database
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mongo_client_cache.collection import CachedCollection


class CachedDatabase(database.Database):
    def __getattr__(self, name: str) -> CachedCollection:
        assert not name.startswith("_")
        return self.__getitem__(name)

    def __getitem__(self, name: str) -> CachedCollection:
        return CachedCollection(self, name)
