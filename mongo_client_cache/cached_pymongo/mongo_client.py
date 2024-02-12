from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import pymongo
from bson.codec_options import TypeRegistry
from pymongo.typings import _DocumentType

from mongo_client_cache.backends.base import CollectionConfig
from mongo_client_cache.backends.exceptions import ReservedAttributeError
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
        cache_config_per_collection: list[CollectionConfig] | None = None,
        **kwargs: Any,
    ) -> None:
        """
        By default, all collections are cached and watched for changes.
        Use `CollectionConfig` to change options for specific collections.
        """
        super().__init__(
            host, port, document_class, tz_aware, connect, type_registry, **kwargs
        )
        self.cache_config_per_collection = cache_config_per_collection

    def __getitem__(self, name: str) -> CachedDatabase:
        if name == "cache_config_per_collection":
            raise ReservedAttributeError(name)
        return CachedDatabase(
            self, name, config_per_collection=self.cache_config_per_collection
        )


class CachedMongoClient(CacheMixin, pymongo.MongoClient): ...
