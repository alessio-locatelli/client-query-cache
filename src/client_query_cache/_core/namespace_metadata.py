from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from client_query_cache._types import PositiveInt

if TYPE_CHECKING:
    from client_query_cache._core.keys import NamespaceId


class NamespaceMetadataCache[Metadata]:
    __slots__ = ("_capacity", "_entries", "_lock")

    def __init__(self, capacity: PositiveInt) -> None:
        self._capacity = capacity
        self._entries: dict[NamespaceId, Metadata] = {}
        self._lock = threading.Lock()

    def get(self, namespace: NamespaceId) -> Metadata | None:
        with self._lock:
            try:
                return self._entries[namespace]
            except KeyError:
                return None

    find = get

    def put(self, namespace: NamespaceId, metadata: Metadata) -> None:
        with self._lock:
            if namespace in self._entries:
                del self._entries[namespace]
            self._entries[namespace] = metadata
            if len(self._entries) > self._capacity:
                oldest = next(iter(self._entries))
                del self._entries[oldest]

    store = put

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
