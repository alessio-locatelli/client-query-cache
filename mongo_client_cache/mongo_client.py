from typing import TYPE_CHECKING, Any

from collections.abc import Sequence
from bson.codec_options import TypeRegistry

from pymongo.typings import _DocumentType
import pymongo

from mongo_client_cache.backend.memory import MemoryCacheBackend
from mongo_client_cache.database import CachedDatabase


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
        cache: MemoryCacheBackend | None = None,
        **kwargs: Any,
    ) -> None:
        self._cache = cache or MemoryCacheBackend()

        super().__init__(
            host, port, document_class, tz_aware, connect, type_registry, **kwargs
        )

    def __getattr__(self, name: str) -> CachedDatabase:
        assert not name.startswith("_")
        return self.__getitem__(name)

    def __getitem__(self, name: str) -> CachedDatabase:
        return CachedDatabase(self, name)


class CachedMongoClient(CacheMixin, pymongo.MongoClient):
    ...
