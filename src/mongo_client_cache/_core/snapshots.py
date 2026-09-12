from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CacheSnapshot:
    lifecycle: str
    used_bytes: int
    shared_budget_bytes: int
    max_entry_bytes: int
    entry_count: int
    hits: int
    misses: int
    evictions: int
    bypasses: int


class CacheStatistics:
    __slots__ = ("_bypasses", "_evictions", "_hits", "_lock", "_misses")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._bypasses = 0

    def record_hit(self) -> None:
        with self._lock:
            self._hits += 1

    def record_miss(self) -> None:
        with self._lock:
            self._misses += 1

    def record_evictions(self, count: int) -> None:
        with self._lock:
            self._evictions += count

    def record_bypass(self) -> None:
        with self._lock:
            self._bypasses += 1

    def snapshot(self) -> tuple[int, int, int, int]:
        with self._lock:
            return self._hits, self._misses, self._evictions, self._bypasses
