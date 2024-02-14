from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import pymongo
from bson.codec_options import TypeRegistry
from pymongo.typings import _DocumentType

from mongo_client_cache.cached_pymongo.database import CachedDatabase
from mongo_client_cache.core.exceptions import ReservedAttributeError
from mongo_client_cache.core.local_database import ClientSideCacheConfig, LocalClient

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
        client_side_cache_config: ClientSideCacheConfig | None = None,
        **kwargs: Any,
    ) -> None:
        """
        By default, all collections are cached and watched for changes.
        Use `CollectionConfig` to change options for specific collections.
        """
        super().__init__(
            host, port, document_class, tz_aware, connect, type_registry, **kwargs
        )
        self.client_side_databases = LocalClient()
        self.client_side_cache_config = client_side_cache_config

    def __getitem__(self, name: str) -> CachedDatabase:
        if name in {"client_side_databases", "client_side_cache_config"}:
            raise ReservedAttributeError(name)
        return CachedDatabase(self, name)


class CachedMongoClient(CacheMixin, pymongo.MongoClient):
    ...
