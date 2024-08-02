from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, override

import pymongo
from bson.codec_options import TypeRegistry
from pymongo.typings import _DocumentType

from mongo_client_cache.cached_pymongo.database import CachedDatabase
from mongo_client_cache.core.exceptions import ReservedAttributeError
from mongo_client_cache.core.misc import LocalClient
from mongo_client_cache.types import ClientSideCacheConfig

if TYPE_CHECKING:
    MIXIN_BASE = pymongo.MongoClient
else:
    MIXIN_BASE = object


class CacheMixin(MIXIN_BASE):
    @override
    def __init__(
        self,
        host: str | Sequence[str] | None = None,
        port: int | None = None,
        document_class: type[_DocumentType] | None = None,
        tz_aware: bool | None = None,
        connect: bool | None = None,
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
        self._client_side_databases = LocalClient()
        self._client_side_cache_config = client_side_cache_config or {}

    @override
    def __getattr__(self, name: str) -> Any:
        if name == "_client_side_databases":
            return self._client_side_databases
        if name == "_client_side_cache_config":
            return self._client_side_cache_config

        # NOTE: The error and the message are copied from
        # the `MongoClient` to have a consistent interface.
        if name.startswith("_"):
            raise AttributeError(  # noqa: TRY003
                f"MongoClient has no attribute {name!r}. To access the {name}"
                f" database, use client[{name!r}]."
            )

        return self.__getitem__(name)

    @override
    def __getitem__(self, name: str) -> CachedDatabase:
        if name in {"_client_side_databases", "_client_side_cache_config"}:
            raise ReservedAttributeError(name)
        return CachedDatabase(self, name)


class CachedMongoClient(CacheMixin, pymongo.MongoClient): ...
