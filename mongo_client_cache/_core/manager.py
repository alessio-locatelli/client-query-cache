from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mongo_client_cache._core.canonical import canonicalize
from mongo_client_cache._core.codec import decode_value, encode_value
from mongo_client_cache._core.entries import AdmissionOutcome, CacheEntry, LookupResult
from mongo_client_cache._core.errors import (
    CacheClosedError,
    CacheConfigurationError,
    UnsupportedCacheRequestError,
)
from mongo_client_cache._core.keys import (
    IdentityCacheKey,
    NamespaceCacheKey,
    canonical_alias_key,
)
from mongo_client_cache._core.lifecycle import CacheLifecycleState
from mongo_client_cache._core.locking import LockOrderGuard
from mongo_client_cache._core.lru import WeightedLru
from mongo_client_cache._core.namespace import IdentityState, NamespaceState
from mongo_client_cache._core.snapshots import CacheSnapshot, CacheStatistics

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mongo_client_cache._core.canonical import Canonical
    from mongo_client_cache._core.keys import AliasKey, NamespaceId

DEFAULT_SHARED_BUDGET_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ENTRY_BYTES = 1 * 1024 * 1024

_NOT_INDEXED = object()

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CacheCoreConfig:
    shared_budget_bytes: int = DEFAULT_SHARED_BUDGET_BYTES
    max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES

    def __post_init__(self) -> None:
        if self.shared_budget_bytes <= 0:
            message = "shared_budget_bytes must be positive"
            raise CacheConfigurationError(message)
        if self.max_entry_bytes <= 0:
            message = "max_entry_bytes must be positive"
            raise CacheConfigurationError(message)
        if self.max_entry_bytes > self.shared_budget_bytes:
            message = "max_entry_bytes must not exceed shared_budget_bytes"
            raise CacheConfigurationError(message)


@dataclass(slots=True)
class IdentityCapture:
    namespace: NamespaceId
    identity: Canonical
    generation_key: tuple[int, int]
    released: bool = field(default=False)


@dataclass(slots=True)
class NamespaceCapture:
    namespace: NamespaceId
    generation: int


class _CacheCoreBase:
    __slots__ = (
        "_guard",
        "_lifecycle",
        "_lifecycle_lock",
        "_lru",
        "_namespaces",
        "_namespaces_lock",
        "_statistics",
    )

    def __init__(self, config: CacheCoreConfig | None = None) -> None:
        resolved_config = config if config is not None else CacheCoreConfig()
        self._guard = LockOrderGuard()
        self._lru = WeightedLru(
            shared_budget_bytes=resolved_config.shared_budget_bytes,
            max_entry_bytes=resolved_config.max_entry_bytes,
            guard=self._guard,
        )
        self._namespaces: dict[NamespaceId, NamespaceState] = {}
        self._namespaces_lock = threading.Lock()
        self._lifecycle = CacheLifecycleState.ACTIVE
        self._lifecycle_lock = threading.Lock()
        self._statistics = CacheStatistics()

    def _is_closed(self) -> bool:
        return self._lifecycle is CacheLifecycleState.CLOSED

    def _ensure_active(self) -> None:
        if self._is_closed():
            message = "cache manager is closed"
            raise CacheClosedError(message)

    def _namespace(self, namespace: NamespaceId) -> NamespaceState:
        with self._namespaces_lock:
            state = self._namespaces.get(namespace)
            if state is None:
                state = NamespaceState(namespace=namespace)
                self._namespaces[namespace] = state
            return state

    @contextmanager
    def _namespace_section(self, state: NamespaceState) -> Iterator[None]:
        with self._guard.namespace_section(), state.lock:
            yield

    @staticmethod
    def _identity_generation_matches(
        state: NamespaceState,
        identity_state: IdentityState | None,
        generation_key: tuple[int, int],
    ) -> bool:
        if identity_state is None:
            return False
        return (state.epoch, identity_state.generation) == generation_key

    def _maybe_prune_identity_locked(
        self, state: NamespaceState, identity: Canonical, identity_state: IdentityState
    ) -> None:
        if identity_state.is_referenced:
            return
        for alias_key in identity_state.alias_keys:
            state.aliases.pop(alias_key, None)
        state.identities.pop(identity, None)
        # A recreated IdentityState always starts from this watermark; keeping
        # it above every generation this identity ever reached (not just the
        # value at first creation) stops a future admission from being
        # rejected by, or a stale one from matching, a same-key entry that is
        # still resident but was never reclaimed (e.g. cancelled before index
        # publication).
        state.identity_generation_watermark = max(
            state.identity_generation_watermark, identity_state.generation + 1
        )

    def _discard_entry_locked(self, state: NamespaceState, entry: CacheEntry) -> None:
        was_indexed = state.entry_index.pop(entry, _NOT_INDEXED) is not _NOT_INDEXED
        if was_indexed and entry.identity is not None:
            identity_state = state.identities.get(entry.identity)
            if identity_state is not None:
                identity_state.cached_ref_count -= 1
                self._maybe_prune_identity_locked(state, entry.identity, identity_state)

    def _process_evicted(self, evicted: list[CacheEntry]) -> None:
        if not evicted:
            return
        self._statistics.record_evictions(len(evicted))
        logger.debug("cache entries evicted", extra={"evicted_count": len(evicted)})
        by_namespace: dict[NamespaceId, list[CacheEntry]] = {}
        for entry in evicted:
            by_namespace.setdefault(entry.namespace, []).append(entry)
        for namespace, entries in by_namespace.items():
            state = self._namespace(namespace)
            with self._namespace_section(state):
                for entry in entries:
                    self._discard_entry_locked(state, entry)


class _CacheCoreLifecycle(_CacheCoreBase):
    __slots__ = ()

    @property
    def lifecycle_state(self) -> CacheLifecycleState:
        return self._lifecycle

    def close(self) -> None:
        with self._lifecycle_lock:
            if self._is_closed():
                return
            self._lifecycle = CacheLifecycleState.CLOSED
        self._lru.clear_all()
        with self._namespaces_lock:
            self._namespaces.clear()
        logger.info("cache manager closed")

    def record_bypass(self) -> None:
        self._statistics.record_bypass()

    def snapshot(self) -> CacheSnapshot:
        used_bytes, entry_count = self._lru.snapshot_usage()
        hits, misses, evictions, bypasses = self._statistics.snapshot()
        return CacheSnapshot(
            lifecycle=self._lifecycle.value,
            used_bytes=used_bytes,
            shared_budget_bytes=self._lru.shared_budget_bytes,
            max_entry_bytes=self._lru.max_entry_bytes,
            entry_count=entry_count,
            hits=hits,
            misses=misses,
            evictions=evictions,
            bypasses=bypasses,
        )


class _CacheCoreNamespaceLifecycle(_CacheCoreBase):
    __slots__ = ()

    def record_write(self, namespace: NamespaceId, identity: object) -> None:
        self._ensure_active()
        canonical_identity = canonicalize(identity)
        state = self._namespace(namespace)
        with self._namespace_section(state):
            state.generation += 1
            identity_state = state.identities.get(canonical_identity)
            if identity_state is not None:
                identity_state.generation += 1
                for alias_key in identity_state.alias_keys:
                    state.aliases.pop(alias_key, None)
                identity_state.alias_keys.clear()

    def clear_namespace(self, namespace: NamespaceId) -> None:
        self._ensure_active()
        self._bump_epoch_and_reclaim(namespace)

    def create_namespace(self, namespace: NamespaceId) -> None:
        self._ensure_active()
        self._bump_epoch_and_reclaim(namespace)

    def _bump_epoch_and_reclaim(self, namespace: NamespaceId) -> None:
        state = self._namespace(namespace)
        with self._namespace_section(state):
            state.generation += 1
            state.epoch += 1
            state.aliases = {}
            reclaimed = list(state.entry_index.items())
            state.entry_index.clear()
            for entry, _key in reclaimed:
                if entry.identity is not None:
                    identity_state = state.identities.get(entry.identity)
                    if identity_state is not None:
                        identity_state.cached_ref_count -= 1
            for identity_state in state.identities.values():
                identity_state.alias_keys.clear()
            for identity, identity_state in list(state.identities.items()):
                if not identity_state.is_referenced:
                    del state.identities[identity]
        for entry, key in reclaimed:
            self._lru.remove_exact(key, entry)
        logger.debug(
            "cache namespace reclaimed",
            extra={
                "database": namespace.database,
                "collection": namespace.collection,
                "reclaimed_entries": len(reclaimed),
            },
        )


class _CacheCoreIdentityAdmission(_CacheCoreBase):
    __slots__ = ()

    def begin_identity_admission(
        self, namespace: NamespaceId, identity: object
    ) -> IdentityCapture:
        self._ensure_active()
        canonical_identity = canonicalize(identity)
        if canonical_identity is None:
            # None is the sentinel CacheEntry.identity uses to mean "this is a
            # namespace-guarded entry"; accepting it as a real identity value
            # would make an identity-guarded entry indistinguishable from that
            # sentinel, so eviction/clear reclamation could never find it.
            message = "identity must not be None"
            raise UnsupportedCacheRequestError(message)
        state = self._namespace(namespace)
        with self._namespace_section(state):
            identity_state = state.identities.get(canonical_identity)
            if identity_state is None:
                identity_state = IdentityState(
                    generation=state.identity_generation_watermark
                )
                state.identity_generation_watermark += 1
                state.identities[canonical_identity] = identity_state
            identity_state.inflight_ref_count += 1
            generation_key = (state.epoch, identity_state.generation)
        return IdentityCapture(
            namespace=namespace,
            identity=canonical_identity,
            generation_key=generation_key,
        )

    def discard_identity_admission(self, capture: IdentityCapture) -> None:
        self._release_identity_capture(capture)

    def admit_identity(
        self,
        capture: IdentityCapture,
        read_shape: object,
        value: object,
        *,
        alias: AliasKey | None = None,
    ) -> AdmissionOutcome:
        try:
            canonical_shape = canonicalize(read_shape)
            encoded = encode_value(value)
            weight = len(encoded)
            if self._lru.is_oversize(weight):
                return AdmissionOutcome.DECLINED_OVERSIZE
            key = IdentityCacheKey(capture.namespace, capture.identity, canonical_shape)
            state = self._namespace(capture.namespace)
            with self._namespace_section(state):
                identity_state = state.identities.get(capture.identity)
                if self._is_closed() or not self._identity_generation_matches(
                    state, identity_state, capture.generation_key
                ):
                    return AdmissionOutcome.DECLINED_STALE
                if alias is not None and identity_state is not None:
                    self._publish_alias_locked(state, alias, capture.identity)
            entry = CacheEntry(
                generation_key=capture.generation_key,
                weight=weight,
                value=encoded,
                namespace=capture.namespace,
                identity=capture.identity,
            )
            admitted, displaced, evicted = self._lru.conditional_put(key, entry)
            if not admitted:
                return AdmissionOutcome.DECLINED_STALE
            self._process_evicted(evicted)
            still_resident = self._lru.contains_exact(key, entry)
            rolled_back = False
            with self._namespace_section(state):
                identity_state = state.identities.get(capture.identity)
                if (
                    not still_resident
                    or self._is_closed()
                    or not self._identity_generation_matches(
                        state, identity_state, capture.generation_key
                    )
                ):
                    rolled_back = True
                elif identity_state is not None:
                    state.entry_index[entry] = key
                    identity_state.cached_ref_count += 1
                if displaced is not None:
                    self._discard_entry_locked(state, displaced)
            if rolled_back:
                self._lru.remove_exact(key, entry)
                return AdmissionOutcome.DECLINED_STALE
            return AdmissionOutcome.ADMITTED
        finally:
            self._release_identity_capture(capture)

    def _release_identity_capture(self, capture: IdentityCapture) -> None:
        if capture.released:
            return
        capture.released = True
        state = self._namespace(capture.namespace)
        with self._namespace_section(state):
            identity_state = state.identities.get(capture.identity)
            if identity_state is None:
                return
            identity_state.inflight_ref_count -= 1
            self._maybe_prune_identity_locked(state, capture.identity, identity_state)

    def _publish_alias_locked(
        self, state: NamespaceState, alias: AliasKey, identity: Canonical
    ) -> None:
        previous_identity = state.aliases.get(alias)
        if previous_identity is not None and previous_identity != identity:
            previous_identity_state = state.identities.get(previous_identity)
            if previous_identity_state is not None:
                previous_identity_state.alias_keys.discard(alias)
        state.aliases[alias] = identity
        state.identities[identity].alias_keys.add(alias)


class _CacheCoreNamespaceAdmission(_CacheCoreBase):
    __slots__ = ()

    def capture_namespace_generation(self, namespace: NamespaceId) -> NamespaceCapture:
        self._ensure_active()
        state = self._namespace(namespace)
        with self._namespace_section(state):
            return NamespaceCapture(namespace=namespace, generation=state.generation)

    def admit_namespace(
        self, capture: NamespaceCapture, discriminator: object, value: object
    ) -> AdmissionOutcome:
        self._ensure_active()
        canonical_discriminator = canonicalize(discriminator)
        encoded = encode_value(value)
        weight = len(encoded)
        if self._lru.is_oversize(weight):
            return AdmissionOutcome.DECLINED_OVERSIZE
        key = NamespaceCacheKey(capture.namespace, canonical_discriminator)
        state = self._namespace(capture.namespace)
        with self._namespace_section(state):
            if self._is_closed() or state.generation != capture.generation:
                return AdmissionOutcome.DECLINED_STALE
        entry = CacheEntry(
            generation_key=(capture.generation,),
            weight=weight,
            value=encoded,
            namespace=capture.namespace,
            identity=None,
        )
        admitted, displaced, evicted = self._lru.conditional_put(key, entry)
        if not admitted:
            return AdmissionOutcome.DECLINED_STALE
        self._process_evicted(evicted)
        still_resident = self._lru.contains_exact(key, entry)
        rolled_back = False
        with self._namespace_section(state):
            if (
                not still_resident
                or self._is_closed()
                or state.generation != capture.generation
            ):
                rolled_back = True
            else:
                state.entry_index[entry] = key
            if displaced is not None:
                self._discard_entry_locked(state, displaced)
        if rolled_back:
            self._lru.remove_exact(key, entry)
            return AdmissionOutcome.DECLINED_STALE
        return AdmissionOutcome.ADMITTED


class _CacheCoreLookup(_CacheCoreBase):
    __slots__ = ()

    def lookup_identity(
        self, namespace: NamespaceId, identity: object, read_shape: object
    ) -> LookupResult:
        self._ensure_active()
        canonical_identity = canonicalize(identity)
        canonical_shape = canonicalize(read_shape)
        key = IdentityCacheKey(namespace, canonical_identity, canonical_shape)
        entry = self._lru.get_and_touch(key)
        if entry is None:
            self._statistics.record_miss()
            return LookupResult(hit=False)
        state = self._namespace(namespace)
        with self._namespace_section(state):
            identity_state = state.identities.get(canonical_identity)
            entry_generation_key = (entry.generation_key[0], entry.generation_key[1])
            valid = self._identity_generation_matches(
                state, identity_state, entry_generation_key
            )
        if not valid:
            self._statistics.record_miss()
            return LookupResult(hit=False)
        self._statistics.record_hit()
        return LookupResult(hit=True, value=decode_value(entry.value))

    def lookup_namespace(
        self, namespace: NamespaceId, discriminator: object
    ) -> LookupResult:
        self._ensure_active()
        canonical_discriminator = canonicalize(discriminator)
        key = NamespaceCacheKey(namespace, canonical_discriminator)
        entry = self._lru.get_and_touch(key)
        if entry is None:
            self._statistics.record_miss()
            return LookupResult(hit=False)
        state = self._namespace(namespace)
        with self._namespace_section(state):
            valid = (state.generation,) == entry.generation_key
        if not valid:
            self._statistics.record_miss()
            return LookupResult(hit=False)
        self._statistics.record_hit()
        return LookupResult(hit=True, value=decode_value(entry.value))

    def resolve_alias(
        self,
        namespace: NamespaceId,
        definition: object,
        value: object,
        collation: object,
    ) -> Canonical | None:
        self._ensure_active()
        alias_key = canonical_alias_key(definition, value, collation)
        state = self._namespace(namespace)
        with self._namespace_section(state):
            return state.aliases.get(alias_key)

    def lookup_by_alias(
        self,
        namespace: NamespaceId,
        definition: object,
        value: object,
        collation: object,
        read_shape: object,
    ) -> LookupResult:
        self._ensure_active()
        alias_key = canonical_alias_key(definition, value, collation)
        state = self._namespace(namespace)
        with self._namespace_section(state):
            identity = state.aliases.get(alias_key)
        if identity is None:
            self._statistics.record_miss()
            return LookupResult(hit=False)
        canonical_shape = canonicalize(read_shape)
        key = IdentityCacheKey(namespace, identity, canonical_shape)
        entry = self._lru.get_and_touch(key)
        if entry is None:
            self._statistics.record_miss()
            return LookupResult(hit=False)
        with self._namespace_section(state):
            still_aliased = state.aliases.get(alias_key) == identity
            identity_state = state.identities.get(identity)
            entry_generation_key = (entry.generation_key[0], entry.generation_key[1])
            valid = still_aliased and self._identity_generation_matches(
                state, identity_state, entry_generation_key
            )
        if not valid:
            self._statistics.record_miss()
            return LookupResult(hit=False)
        self._statistics.record_hit()
        return LookupResult(hit=True, value=decode_value(entry.value))


class CacheCore(
    _CacheCoreLifecycle,
    _CacheCoreNamespaceLifecycle,
    _CacheCoreIdentityAdmission,
    _CacheCoreNamespaceAdmission,
    _CacheCoreLookup,
):
    __slots__ = ()
