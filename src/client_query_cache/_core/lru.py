from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import CacheKey
    from client_query_cache._core.locking import LockOrderGuard


class WeightedLru:
    __slots__ = (
        "_guard",
        "_lock",
        "_max_entry_bytes",
        "_order",
        "_shared_budget_bytes",
        "_used_bytes",
    )

    def __init__(
        self,
        *,
        shared_budget_bytes: int,
        max_entry_bytes: int,
        guard: LockOrderGuard,
    ) -> None:
        self._shared_budget_bytes = shared_budget_bytes
        self._max_entry_bytes = max_entry_bytes
        self._guard = guard
        self._order: OrderedDict[CacheKey, CacheEntry] = OrderedDict()
        self._used_bytes = 0
        self._lock = threading.Lock()

    @property
    def max_entry_bytes(self) -> int:
        return self._max_entry_bytes

    @property
    def shared_budget_bytes(self) -> int:
        return self._shared_budget_bytes

    def is_oversize(self, weight: int) -> bool:
        return weight > self._max_entry_bytes

    def snapshot_usage(self) -> tuple[int, int]:
        with self._guard.lru_section(), self._lock:
            return self._used_bytes, len(self._order)

    def peek(self, key: CacheKey) -> CacheEntry | None:
        with self._guard.lru_section(), self._lock:
            return self._order.get(key)

    def touch(self, key: CacheKey) -> None:
        with self._guard.lru_section(), self._lock:
            if key in self._order:
                self._order.move_to_end(key)

    def conditional_put(
        self, key: CacheKey, entry: CacheEntry
    ) -> tuple[bool, CacheEntry | None, list[CacheEntry]]:
        evicted: list[CacheEntry] = []
        with self._guard.lru_section(), self._lock:
            current = self._order.get(key)
            if current is not None and current.generation_key >= entry.generation_key:
                return False, None, evicted
            if current is not None:
                self._used_bytes -= current.weight
                del self._order[key]
            self._order[key] = entry
            self._used_bytes += entry.weight
            while self._used_bytes > self._shared_budget_bytes:
                oldest_key, oldest_entry = next(iter(self._order.items()))
                del self._order[oldest_key]
                self._used_bytes -= oldest_entry.weight
                evicted.append(oldest_entry)
            return True, current, evicted

    def contains_exact(self, key: CacheKey, entry: CacheEntry) -> bool:
        with self._guard.lru_section(), self._lock:
            return self._order.get(key) is entry

    def remove_exact(self, key: CacheKey, entry: CacheEntry) -> bool:
        with self._guard.lru_section(), self._lock:
            if self._order.get(key) is entry:
                del self._order[key]
                self._used_bytes -= entry.weight
                return True
            return False

    def clear_all(self) -> None:
        with self._guard.lru_section(), self._lock:
            self._order.clear()
            self._used_bytes = 0
