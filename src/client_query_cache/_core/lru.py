from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from client_query_cache._types import NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import CacheKey
    from client_query_cache._core.locking import LockOrderGuard

    type RemovalListener = Callable[[CacheKey, CacheEntry], None]


class LruPlanChangedError(RuntimeError):
    pass


@dataclass(slots=True)
class LruPlanningView:
    revision: NonNegativeInt
    entries: Iterator[tuple[CacheKey, CacheEntry]]


class WeightedLru:
    __slots__ = (
        "_budget_bytes",
        "_guard",
        "_lock",
        "_max_entry_bytes",
        "_on_removed",
        "_order",
        "_revision",
        "_track_revision",
        "_used_bytes",
    )

    def __init__(
        self,
        *,
        budget_bytes: PositiveInt,
        max_entry_bytes: PositiveInt,
        guard: LockOrderGuard,
        on_removed: RemovalListener | None = None,
        track_revision: bool = False,
    ) -> None:
        self._budget_bytes = budget_bytes
        self._max_entry_bytes = max_entry_bytes
        self._guard = guard
        self._on_removed = on_removed
        self._order: OrderedDict[CacheKey, CacheEntry] = OrderedDict()
        self._used_bytes = 0
        self._lock = threading.Lock()
        self._revision: NonNegativeInt = 0
        self._track_revision = track_revision

    @property
    def max_entry_bytes(self) -> PositiveInt:
        return self._max_entry_bytes

    @property
    def budget_bytes(self) -> PositiveInt:
        return self._budget_bytes

    def is_oversize(self, weight: NonNegativeInt) -> bool:
        return weight > self._max_entry_bytes

    def snapshot_usage(self) -> tuple[NonNegativeInt, NonNegativeInt]:
        with self._guard.lru_section(), self._lock:
            return self._used_bytes, len(self._order)

    def peek(self, key: CacheKey) -> CacheEntry | None:
        with self._guard.lru_section(), self._lock:
            try:
                return self._order[key]
            except KeyError:
                return None

    def touch(self, key: CacheKey) -> None:
        with self._guard.lru_section(), self._lock:
            if key in self._order:
                if self._track_revision and next(reversed(self._order)) != key:
                    self._revision += 1
                self._order.move_to_end(key)

    def planning_view(self) -> LruPlanningView:
        with self._guard.lru_section(), self._lock:
            return LruPlanningView(self._revision, iter(self._order.items()))

    def next_planned(self, view: LruPlanningView) -> tuple[CacheKey, CacheEntry] | None:
        with self._guard.lru_section(), self._lock:
            if view.revision != self._revision:
                raise LruPlanChangedError
            return next(view.entries, None)

    def commit_plan(
        self,
        view: LruPlanningView,
        victims: list[tuple[CacheKey, CacheEntry]],
        key: CacheKey,
        entry: CacheEntry | None,
    ) -> bool:
        with self._guard.lru_section(), self._lock:
            if view.revision != self._revision:
                return False
            for victim_key, victim in victims:
                del self._order[victim_key]
                self._used_bytes -= victim.weight
                if self._on_removed is not None:
                    self._on_removed(victim_key, victim)
            if entry is not None:
                self._order[key] = entry
                self._used_bytes += entry.weight
            self._revision += 1
            return True

    def conditional_put(
        self, key: CacheKey, entry: CacheEntry
    ) -> tuple[bool, CacheEntry | None, list[CacheEntry]]:
        evicted: list[CacheEntry] = []
        with self._guard.lru_section(), self._lock:
            try:
                current = self._order[key]
            except KeyError:
                current = None
            if current is not None and current.generation_key >= entry.generation_key:
                return False, None, evicted
            on_removed = self._on_removed
            if current is not None:
                self._used_bytes -= current.weight
                del self._order[key]
                if on_removed is not None:
                    on_removed(key, current)
            self._order[key] = entry
            self._used_bytes += entry.weight
            while self._used_bytes > self._budget_bytes:
                oldest_key, oldest_entry = next(iter(self._order.items()))
                del self._order[oldest_key]
                self._used_bytes -= oldest_entry.weight
                evicted.append(oldest_entry)
                if on_removed is not None:
                    on_removed(oldest_key, oldest_entry)
            return True, current, evicted

    def contains_exact(self, key: CacheKey, entry: CacheEntry) -> bool:
        with self._guard.lru_section(), self._lock:
            try:
                return self._order[key] is entry
            except KeyError:
                return False

    def remove_exact(self, key: CacheKey, entry: CacheEntry) -> bool:
        with self._guard.lru_section(), self._lock:
            try:
                current = self._order[key]
            except KeyError:
                return False
            if current is entry:
                if self._track_revision:
                    self._revision += 1
                del self._order[key]
                self._used_bytes -= entry.weight
                if self._on_removed is not None:
                    self._on_removed(key, entry)
                return True
            return False

    def clear_all(self) -> None:
        with self._guard.lru_section(), self._lock:
            if self._on_removed is not None:
                for key, entry in self._order.items():
                    self._on_removed(key, entry)
            self._order.clear()
            self._used_bytes = 0
            if self._track_revision:
                self._revision += 1
