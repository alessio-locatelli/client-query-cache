from collections.abc import Mapping
from typing import Any, cast

from pymongo.collection import Collection

from mongo_client_cache.backends.base import MongoCommand
from mongo_client_cache.backends.memory import MemoryBackend, NotCachedError


class CachedCollection(Collection):
    def find_one(
        self,
        filter: Any | None = None,
        *args: Any,
        projection: list[str] | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Mapping[str, Any] | None:
        cache_backend = cast(MemoryBackend, self._Collection__database.cache_backend)
        if cache_backend.collection_can_be_cached(self.name):
            try:
                return cache_backend.get_one(
                    collection_name=self.name,
                    mongo_command=MongoCommand(
                        "findOne", filter=filter, projection=projection
                    ),
                )
            except NotCachedError:
                document = super().find_one(filter, *args, **kwargs)
                cache_backend.set_one(
                    collection_name=self.name,
                    document=document,
                    mongo_command=MongoCommand("findOne", filter, projection),
                )
                return document
        return super().find_one(filter, *args, **kwargs)
