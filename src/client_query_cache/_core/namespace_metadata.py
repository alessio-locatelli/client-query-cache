from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from client_query_cache._types import NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from client_query_cache._core.keys import NamespaceId


class NamespaceMetadataCache[Metadata]:
    __slots__ = ("_capacity", "_entries", "_lock", "_version")

    def __init__(self, capacity: PositiveInt) -> None:
        self._capacity = capacity
        self._entries: dict[NamespaceId, Metadata] = {}
        self._lock = threading.Lock()
        self._version: NonNegativeInt = 0

    @property
    def version(self) -> NonNegativeInt:
        with self._lock:
            return self._version

    def get(self, namespace: NamespaceId) -> Metadata | None:
        with self._lock:
            try:
                return self._entries[namespace]
            except KeyError:
                return None

    find = get

    def put(self, namespace: NamespaceId, metadata: Metadata) -> None:
        with self._lock:
            self._put_locked(namespace, metadata)

    def put_if_version(
        self,
        namespace: NamespaceId,
        metadata: Metadata,
        version: NonNegativeInt,
    ) -> bool:
        with self._lock:
            if self._version != version:
                return False
            self._put_locked(namespace, metadata)
            return True

    def _put_locked(self, namespace: NamespaceId, metadata: Metadata) -> None:
        if namespace in self._entries:
            del self._entries[namespace]
        self._entries[namespace] = metadata
        if len(self._entries) > self._capacity:
            oldest = next(iter(self._entries))
            del self._entries[oldest]

    def remove(self, namespace: NamespaceId) -> bool:
        with self._lock:
            self._version += 1
            try:
                del self._entries[namespace]
            except KeyError:
                return False
            return True

    def remove_database(self, database: str) -> None:
        with self._lock:
            self._version += 1
            for namespace in tuple(self._entries):
                if namespace.database == database:
                    del self._entries[namespace]

    store = put

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._version += 1

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
