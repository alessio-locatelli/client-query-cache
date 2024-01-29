from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import pymongo
from bson.codec_options import TypeRegistry
from pymongo.typings import _DocumentType

from mongo_client_cache.backend.memory import CacheBackend

client = pymongo.MongoClient()
db = client.test_database
collection = db.test_collection
collection.find_one()


if TYPE_CHECKING:
    MIXIN_BASE = pymongo.MongoClient
else:
    MIXIN_BASE = object


class CacheMixin(MIXIN_BASE):
    def __init__(
        self,
        host: str | Sequence[str] | None = None,
        port: int | None = None,
        document_class: type[_DocumentType] | None = None,
        tz_aware: bool | None = None,
        connect: bool | None = None,
        type_registry: TypeRegistry | None = None,
        *,
        cache: CacheBackend | None = None,
        **kwargs: Any,
    ) -> None:
        self.cache = cache or CacheBackend()

        super().__init__(
            host, port, document_class, tz_aware, connect, type_registry, **kwargs
        )

    def find_one(
        self, filter: Any | None = None, *args: Any, **kwargs: Any
    ) -> _DocumentType | None: ...


class CachedMongoClient(CacheMixin, pymongo.MongoClient): ...
