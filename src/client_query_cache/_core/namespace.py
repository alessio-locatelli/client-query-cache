from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from client_query_cache._types import NonNegativeInt

if TYPE_CHECKING:
    from client_query_cache._core.canonical import Canonical
    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import (
        AliasKey,
        CacheKey,
        NamespaceCacheKey,
        NamespaceId,
    )
    from client_query_cache._core.locking import NamespaceLock


_NO_ALIASES: frozenset[AliasKey] = frozenset()


@dataclass(slots=True)
class IdentityState:
    generation: NonNegativeInt = 0
    cached_ref_count: NonNegativeInt = 0
    inflight_ref_count: NonNegativeInt = 0
    alias_keys: frozenset[AliasKey] = _NO_ALIASES

    @property
    def is_referenced(self) -> bool:
        return self.cached_ref_count > 0 or self.inflight_ref_count > 0

    def add_alias(self, alias: AliasKey) -> None:
        if alias not in self.alias_keys:
            self.alias_keys |= {alias}

    def discard_alias(self, alias: AliasKey) -> None:
        self.alias_keys = (self.alias_keys - {alias}) or _NO_ALIASES

    def clear_aliases(self) -> None:
        self.alias_keys = _NO_ALIASES


@dataclass(slots=True)
class NamespaceState:
    namespace: NamespaceId
    lock: NamespaceLock
    generation: NonNegativeInt = 0
    epoch: NonNegativeInt = 0
    index_generation: NonNegativeInt = 0
    identities: dict[Canonical, IdentityState] = field(default_factory=dict)
    aliases: dict[AliasKey, Canonical] = field(default_factory=dict)
    entry_index: dict[CacheEntry, CacheKey] = field(default_factory=dict)
    find_families: dict[int, dict[CacheEntry, NamespaceCacheKey]] = field(
        default_factory=dict
    )
    identity_generation_watermark: NonNegativeInt = 0
