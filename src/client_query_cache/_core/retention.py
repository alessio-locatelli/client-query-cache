from __future__ import annotations

import sys
import threading
from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from client_query_cache._core.canonical import _CanonicalTag
from client_query_cache._core.locking import CapacitySection
from client_query_cache._core.snapshots import RetentionDeclineReason
from client_query_cache._types import NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from client_query_cache._core.canonical import Canonical
    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import AliasKey, CacheKey, NamespaceId
    from client_query_cache._core.locking import LockOrderGuard
    from client_query_cache._core.lru import LruPlanningView, WeightedLru
    from client_query_cache._core.namespace import IdentityState, NamespaceState


class AliasRegistry:
    __slots__ = (
        "_count_lock",
        "capacity",
        "count",
        "identities",
        "maximum",
        "order",
        "section",
    )

    def __init__(
        self, maximum: PositiveInt | None, lock: threading.RLock, guard: LockOrderGuard
    ) -> None:
        self.maximum = maximum
        self.count: NonNegativeInt = 0
        self._count_lock = threading.Lock()
        self.capacity = None if maximum is None else CapacitySection(lock, guard)
        self.section = nullcontext() if self.capacity is None else self.capacity
        self.order: (
            OrderedDict[
                tuple[NonNegativeInt, AliasKey], tuple[NamespaceState, AliasKey]
            ]
            | None
        ) = None if maximum is None else OrderedDict()
        self.identities: (
            dict[tuple[NonNegativeInt, NonNegativeInt], Canonical] | None
        ) = None if maximum is None else {}

    def canonical_alias(self, state: NamespaceState, alias: AliasKey) -> AliasKey:
        if self.order is None:
            return alias
        try:
            return self.order[id(state), alias][1]
        except KeyError:
            return alias

    def added(self, state: NamespaceState, alias: AliasKey) -> None:
        if self.capacity is None:
            with self._count_lock:
                self.count += 1
        else:
            self.count += 1
        if self.order is not None:
            self.order[id(state), alias] = (state, alias)

    def republished(self, state: NamespaceState, alias: AliasKey) -> None:
        if self.order is not None:
            self.order.move_to_end((id(state), alias))

    def removed(self, state: NamespaceState, alias: AliasKey) -> None:
        if self.capacity is None:
            with self._count_lock:
                self.count -= 1
        else:
            self.count -= 1
        if self.order is not None:
            record = self.order.pop((id(state), alias))
            assert self.capacity is not None
            self.capacity.retire(record)

    def identity_added(
        self, state: NamespaceState, identity: Canonical, owner: IdentityState
    ) -> None:
        if self.identities is not None:
            self.identities[id(state), id(owner)] = identity

    def identity_removed(self, state: NamespaceState, owner: IdentityState) -> None:
        if self.identities is not None:
            identity = self.identities.pop((id(state), id(owner)))
            assert self.capacity is not None
            self.capacity.retire(identity, owner)

    def retire(self, *objects: object) -> None:
        if self.capacity is not None:
            self.capacity.retire(*objects)

    def clear(self) -> None:
        self.count = 0
        if self.order is not None:
            self.retire(self.order, self.identities)
            self.order = OrderedDict()
            self.identities = {}


@dataclass(slots=True)
class RetentionPlan:
    registry: AliasRegistry
    lru: WeightedLru
    namespace_state: Callable[[NamespaceId], NamespaceState | None]
    view: LruPlanningView
    records: NonNegativeInt
    used: NonNegativeInt
    protected: IdentityState | None
    alias_candidates: Iterator[tuple[NamespaceState, AliasKey]]
    victims: list[tuple[CacheKey, CacheEntry]] = field(default_factory=list)
    aliases: dict[tuple[NonNegativeInt, AliasKey], tuple[NamespaceState, AliasKey]] = (
        field(default_factory=dict)
    )
    removed: set[CacheEntry] = field(default_factory=set)
    identity_removals: dict[NonNegativeInt, NonNegativeInt] = field(
        default_factory=dict
    )

    def remove_alias(self, state: NamespaceState, alias: AliasKey) -> None:
        token = (id(state), alias)  # pytriage: TR5 (reuse for lookup and insertion)
        if token not in self.aliases:
            self.aliases[token] = (state, alias)
            self.records -= 1

    def remove_value(self, key: CacheKey, entry: CacheEntry) -> None:
        if entry in self.removed:
            return
        self.removed.add(entry)
        self.victims.append((key, entry))
        self.records -= 1
        self.used -= entry.weight
        if entry.identity is None:
            return
        state = self.namespace_state(entry.namespace)
        assert state is not None
        with state.lock:
            owner = state.identities[entry.identity]
            token = id(owner)  # pytriage: TR5 (reuse for lookup and update)
            try:
                removed = self.identity_removals[token] + 1
            except KeyError:
                removed = 1
            self.identity_removals[token] = removed
            if (
                owner is not self.protected
                and not owner.inflight_ref_count
                and removed == owner.cached_ref_count
            ):
                for alias in owner.alias_keys or ():
                    self.remove_alias(state, alias)

    def fit_value(self) -> None:
        maximum = self.registry.maximum
        assert maximum is not None
        assert self.registry.order is not None
        while self.records > maximum:
            oldest = next(self.alias_candidates, None)
            if oldest is None:
                break
            self.remove_alias(*oldest)
        while self.records > maximum or self.used > self.lru.budget_bytes:
            victim = self.lru.next_planned(self.view)
            assert victim is not None
            key, entry = victim
            self.remove_value(key, entry)

    def fit_alias(self, state: NamespaceState, alias: AliasKey) -> bool:
        maximum = self.registry.maximum
        order = self.registry.order
        assert maximum is not None
        assert order is not None
        token = (id(state), alias)
        delta = 1 if token not in order or token in self.aliases else 0
        while self.records + delta > maximum:
            oldest = next(self.alias_candidates, None)
            if oldest is None:
                break
            self.remove_alias(*oldest)
        return self.records + delta <= maximum


def key_decline(maximum: PositiveInt, *roots: object) -> RetentionDeclineReason | None:
    try:
        return _measure_key(maximum, roots)
    except Exception:  # noqa: BLE001 -- caller-defined __sizeof__ errors decline retention.
        return RetentionDeclineReason.KEY_SIZE_UNAVAILABLE


def _measure_key(
    maximum: PositiveInt, roots: tuple[object, ...]
) -> RetentionDeclineReason | None:
    pending = list(roots)
    seen: set[NonNegativeInt] = set()
    charge: NonNegativeInt = 0
    while pending:
        node = pending.pop()
        if type(node) is _CanonicalTag:
            continue
        identity = id(node)
        if identity in seen:
            continue
        seen.add(identity)
        charge += sys.getsizeof(node)
        if charge > maximum:
            return RetentionDeclineReason.KEY_SIZE_LIMIT
        if isinstance(node, tuple):
            pending.extend(node)
    return None
