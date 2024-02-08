from collections.abc import Iterator
from typing import Any, cast

from pymongo.collection import Collection
from pymongo.cursor import Cursor

from mongo_client_cache.backends.base import MongoCommand
from mongo_client_cache.backends.memory import MemoryBackend, NotCachedError
from mongo_client_cache.types import BsonDict


class CachedCollection(Collection):
    def find_one(
        self,
        filter: Any | None = None,
        *args: Any,
        projection: list[str] | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> BsonDict | None:
        cache_backend = cast(
            MemoryBackend, self._Collection__database.client.cache_backend
        )

        if not cache_backend.collection_can_be_cached(self.name):
            return super().find_one(filter, *args, **kwargs)

        try:
            return cache_backend.get_one(
                mongo_command=MongoCommand(self.name, "findOne", filter, projection),
            )
        except NotCachedError:
            document = super().find_one(filter, *args, **kwargs)
            cache_backend.set_one(
                document=document,
                mongo_command=MongoCommand(self.name, "findOne", filter, projection),
            )
            return document

    def find(self, *args: Any, **kwargs: Any) -> Iterator[BsonDict]:
        cache_backend = cast(
            MemoryBackend, self._Collection__database.client.cache_backend
        )

        if not cache_backend.collection_can_be_cached(self.name):
            return super().find(*args, **kwargs)

        mongo_command = MongoCommand(
            self.name,
            "find",
            filter=args[0] if args else kwargs.pop("filter"),
            projection=kwargs.pop("projection"),
        )
        try:
            cached_documents = cache_backend.get_many(mongo_command=mongo_command)
        except NotCachedError:
            documents = []
            for document in Cursor(self, *args, **kwargs):
                documents.append(document)
                yield document

            cache_backend.set_many(documents=documents, mongo_command=mongo_command)
        else:
            yield from cached_documents
