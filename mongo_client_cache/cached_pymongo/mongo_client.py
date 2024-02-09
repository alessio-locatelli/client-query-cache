from collections.abc import Sequence
from threading import Thread
from typing import TYPE_CHECKING, Any

import pymongo
from bson.codec_options import TypeRegistry
from pymongo.typings import _DocumentType

from mongo_client_cache.backends.memory import MemoryBackend
from mongo_client_cache.cached_pymongo.change_stream import Watch
from mongo_client_cache.cached_pymongo.database import CachedDatabase

if TYPE_CHECKING:
    MIXIN_BASE = pymongo.MongoClient
else:
    MIXIN_BASE = object


class CacheMixin(MIXIN_BASE):
    def __init__(  # noqa: PLR0913,PLR0917
        self,
        host: str | Sequence[str] | None = None,
        port: int | None = None,
        document_class: type[_DocumentType] | None = None,
        tz_aware: bool | None = None,  # noqa: FBT001
        connect: bool | None = None,  # noqa: FBT001
        type_registry: TypeRegistry | None = None,
        *,
        cache_backend: MemoryBackend,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            host, port, document_class, tz_aware, connect, type_registry, **kwargs
        )
        self.cache_backend = cache_backend
        Thread(target=Watch, args=[self], daemon=True).start()

    def __getitem__(self, name: str) -> CachedDatabase:
        return CachedDatabase(self, name)


class CachedMongoClient(CacheMixin, pymongo.MongoClient): ...
