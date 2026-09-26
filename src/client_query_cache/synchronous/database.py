from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pymongo.synchronous.collection import Collection
from pymongo.synchronous.database import Database

from client_query_cache.synchronous.collection import CachedCollection

if TYPE_CHECKING:
    from client_query_cache.synchronous.manager import CacheManager


class CachedDatabase[DocumentType: Mapping[str, Any]]:
    __slots__ = ("_database", "_manager")

    def __init__(
        self, manager: CacheManager[DocumentType], database: Database[DocumentType]
    ) -> None:
        self._manager = manager
        self._database = database

    @property
    def manager(self) -> CacheManager[DocumentType]:
        return self._manager

    @property
    def name(self) -> str:
        return self._database.name

    @property
    def raw(self) -> Database[DocumentType]:
        return self._database

    def __getitem__(self, name: str) -> CachedCollection[DocumentType]:
        return CachedCollection(self, self._database[name])

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return self._wrap_delegated(getattr(self._database, name))

    def _wrap_delegated(self, value: Any) -> Any:  # noqa: ANN401
        if isinstance(value, Collection):
            return CachedCollection(self, value)
        if isinstance(value, Database):
            return CachedDatabase(self._manager, value)
        if not callable(value):
            return value

        def _delegate(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            return self._wrap_delegated(value(*args, **kwargs))

        return _delegate
