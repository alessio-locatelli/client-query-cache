from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from client_query_cache._core.canonical import Canonical
    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import (
        AliasKey,
        CacheKey,
        NamespaceCacheKey,
        NamespaceId,
    )


@dataclass(slots=True)
class IdentityState:
    generation: int = 0
    cached_ref_count: int = 0
    inflight_ref_count: int = 0
    alias_keys: set[AliasKey] = field(default_factory=set)

    @property
    def is_referenced(self) -> bool:
        return self.cached_ref_count > 0 or self.inflight_ref_count > 0


@dataclass(slots=True)
class NamespaceState:
    namespace: NamespaceId
    lock: threading.Lock = field(default_factory=threading.Lock)
    generation: int = 0
    epoch: int = 0
    index_generation: int = 0
    identities: dict[Canonical, IdentityState] = field(default_factory=dict)
    aliases: dict[AliasKey, Canonical] = field(default_factory=dict)
    entry_index: dict[CacheEntry, CacheKey] = field(default_factory=dict)
    find_families: dict[int, dict[CacheEntry, NamespaceCacheKey]] = field(
        default_factory=dict
    )
    identity_generation_watermark: int = 0
