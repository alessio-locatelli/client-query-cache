from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from client_query_cache._types import NonNegativeInt

if TYPE_CHECKING:
    from client_query_cache._core.canonical import Canonical
    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import CacheKey, NamespaceId


class CacheObserver(Protocol):
    def admitted(self, key: CacheKey, entry: CacheEntry) -> None: ...

    def removed(self, key: CacheKey, entry: CacheEntry) -> None: ...

    def identity_written(self, namespace: NamespaceId, identity: Canonical) -> None: ...

    def epoch_changed(self, namespace: NamespaceId, epoch: NonNegativeInt) -> None: ...

    def availability_changed(self, database: str, *, available: bool) -> None: ...


class PayloadStore(Protocol):
    def store(self, encoded: bytes) -> object: ...

    def release(self, stored: object) -> None: ...

    def snapshot(self, stored: object) -> bytes | None: ...
