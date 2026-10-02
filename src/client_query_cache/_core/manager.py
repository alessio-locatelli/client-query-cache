from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bson.errors import BSONError

from client_query_cache._core.canonical import canonicalize, is_canonicalizable
from client_query_cache._core.codec import decode_value, encode_value
from client_query_cache._core.entries import AdmissionOutcome, CacheEntry, LookupResult
from client_query_cache._core.errors import (
    CacheClosedError,
    CacheConfigurationError,
    UnsupportedCacheRequestError,
)
from client_query_cache._core.keys import (
    IdentityCacheKey,
    NamespaceCacheKey,
    canonical_alias_key,
)
from client_query_cache._core.lifecycle import CacheLifecycleState
from client_query_cache._core.locking import LockOrderGuard
from client_query_cache._core.lru import WeightedLru
from client_query_cache._core.namespace import IdentityState, NamespaceState
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._core.snapshots import (
    BypassReason,
    CacheSnapshot,
    CacheStatistics,
)
from client_query_cache._core.stream_cost import (
    DEFAULT_LAG_CAPTURE_WINDOW_CONFIG,
    LagCaptureWindowConfig,
    StreamCostRegistry,
    StreamCostSnapshot,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from typing import Any

    from bson.codec_options import CodecOptions

    from client_query_cache._core.canonical import Canonical
    from client_query_cache._core.keys import AliasKey, CacheKey, NamespaceId

DEFAULT_SHARED_BUDGET_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ENTRY_BYTES = 1 * 1024 * 1024

_NOT_INDEXED = object()
_DEFAULT_DATABASE_AVAILABILITY = (True, 0)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CacheCoreConfig:
    shared_budget_bytes: int = DEFAULT_SHARED_BUDGET_BYTES
    max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES
    lag_capture_window_config: LagCaptureWindowConfig = (
        DEFAULT_LAG_CAPTURE_WINDOW_CONFIG
    )

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
    availability_generation: int
    released: bool = field(default=False)


@dataclass(slots=True)
class NamespaceCapture:
    namespace: NamespaceId
    generation: int
    availability_generation: int


def _maybe_prune_identity_locked(
    state: NamespaceState, identity: Canonical, identity_state: IdentityState
) -> None:
    if identity_state.is_referenced:
        return
    for alias_key in identity_state.alias_keys:
        state.aliases.pop(alias_key, None)
    state.identities.pop(identity, None)
    state.identity_generation_watermark = max(
        state.identity_generation_watermark, identity_state.generation + 1
    )


def _discard_entry_locked(state: NamespaceState, entry: CacheEntry) -> None:
    was_indexed = state.entry_index.pop(entry, _NOT_INDEXED) is not _NOT_INDEXED
    if was_indexed and entry.identity is not None:
        identity_state = state.identities[entry.identity]
        identity_state.cached_ref_count -= 1
        _maybe_prune_identity_locked(state, entry.identity, identity_state)


def _match_identity_state(
    state: NamespaceState,
    identity: Canonical,
    generation_key: tuple[int, int],
) -> IdentityState | None:
    try:
        identity_state = state.identities[identity]
    except KeyError:
        return None
    if (state.epoch, identity_state.generation) != generation_key:
        return None
    return identity_state


class _CacheCoreBase:
    __slots__ = (
        "_availability_lock",
        "_database_availability",
        "_database_namespaces",
        "_guard",
        "_lifecycle",
        "_lifecycle_lock",
        "_lru",
        "_namespaces",
        "_namespaces_lock",
        "_statistics",
        "_stream_cost",
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
        self._database_namespaces: dict[str, dict[NamespaceId, None]] = {}
        self._namespaces_lock = threading.Lock()
        self._lifecycle = CacheLifecycleState.ACTIVE
        self._lifecycle_lock = threading.Lock()
        self._statistics = CacheStatistics()
        self._database_availability: dict[str, tuple[bool, int]] = {}
        self._availability_lock = threading.RLock()
        self._stream_cost = StreamCostRegistry(
            resolved_config.lag_capture_window_config
        )

    def _is_closed(self) -> bool:
        return self._lifecycle is CacheLifecycleState.CLOSED

    def _is_database_available(self, database: str) -> bool:
        with self._availability_lock:
            try:
                available, _generation = self._database_availability[database]
            except KeyError:
                available, _generation = _DEFAULT_DATABASE_AVAILABILITY
            return available

    def _capture_database_availability(self, database: str) -> int:
        with self._availability_lock:
            try:
                _available, generation = self._database_availability[database]
            except KeyError:
                _available, generation = _DEFAULT_DATABASE_AVAILABILITY
            return generation

    @contextmanager
    def _admission_section(
        self,
        namespace: NamespaceId,
        availability_generation: int,
        weight: int,
    ) -> Generator[AdmissionOutcome | None]:
        with self._availability_lock:
            try:
                available, current_generation = self._database_availability[
                    namespace.database
                ]
            except KeyError:
                available, current_generation = _DEFAULT_DATABASE_AVAILABILITY
            if not available or availability_generation != current_generation:
                self._statistics.record_bypass(
                    BypassReason.STREAM_UNAVAILABLE
                    if not available
                    else BypassReason.ADMISSION_INVALIDATED
                )
                yield AdmissionOutcome.DECLINED_UNAVAILABLE
                return
            if self._lru.is_oversize(weight):
                self._statistics.record_oversized_bypass()
                yield AdmissionOutcome.DECLINED_OVERSIZE
                return
            yield None

    def _ensure_active(self) -> None:
        if self._is_closed():
            message = "cache manager is closed"
            raise CacheClosedError(message)

    def _namespace(self, namespace: NamespaceId) -> NamespaceState:
        with self._namespaces_lock:
            try:
                state = self._namespaces[namespace]
            except KeyError:
                state = NamespaceState(namespace=namespace)
                if not self._is_closed():
                    self._namespaces[namespace] = state
                    self._database_namespaces.setdefault(namespace.database, {})[
                        namespace
                    ] = None
            return state

    @contextmanager
    def _namespace_section(self, state: NamespaceState) -> Generator[None]:
        with self._guard.namespace_section(), state.lock:
            yield

    def _reclaim_if_evicted_before_publication(
        self, state: NamespaceState, key: CacheKey, entry: CacheEntry
    ) -> bool:
        if self._lru.contains_exact(key, entry):
            return False
        with self._namespace_section(state):
            _discard_entry_locked(state, entry)
        self._lru.remove_exact(key, entry)
        return True

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
                    _discard_entry_locked(state, entry)

    def _finalize_put(
        self,
        state: NamespaceState,
        key: CacheKey,
        entry: CacheEntry,
        *,
        admitted: bool,
        displaced: CacheEntry | None,
        is_still_valid: Callable[[], bool],
        on_admit: Callable[[], None],
    ) -> AdmissionOutcome:
        if not admitted:
            return AdmissionOutcome.DECLINED_STALE
        still_resident = self._lru.contains_exact(key, entry)
        rolled_back = False
        with self._namespace_section(state):
            if not still_resident or self._is_closed() or not is_still_valid():
                rolled_back = True
            else:
                state.entry_index[entry] = key
                on_admit()
            if displaced is not None:
                _discard_entry_locked(state, displaced)
        if rolled_back:
            self._lru.remove_exact(key, entry)
            return AdmissionOutcome.DECLINED_STALE
        if self._reclaim_if_evicted_before_publication(state, key, entry):
            return AdmissionOutcome.DECLINED_STALE
        return AdmissionOutcome.ADMITTED


class _CacheCoreLifecycle(_CacheCoreBase):
    __slots__ = ()

    def close(self) -> None:
        with self._lifecycle_lock:
            if self._is_closed():
                return
            self._lifecycle = CacheLifecycleState.CLOSED
        self._lru.clear_all()
        with self._namespaces_lock:
            self._namespaces.clear()
            self._database_namespaces.clear()
        logger.info("cache manager closed")

    def record_bypass(self, reason: BypassReason = BypassReason.UNSPECIFIED) -> None:
        self._statistics.record_bypass(reason)

    def snapshot(self) -> CacheSnapshot:
        used_bytes, entry_count = self._lru.snapshot_usage()
        hits, misses, evictions, bypasses, oversized_bypasses, bypass_reasons = (
            self._statistics.snapshot()
        )
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
            oversized_bypasses=oversized_bypasses,
            bypass_reasons=bypass_reasons,
        )


class _CacheCoreNamespaceLifecycle(_CacheCoreBase):
    __slots__ = ()

    def namespaces_for_database(self, database: str) -> list[NamespaceId]:
        with self._namespaces_lock:
            try:
                namespaces = self._database_namespaces[database]
            except KeyError:
                namespaces = {}
            return list(namespaces)

    def has_namespace(self, namespace: NamespaceId) -> bool:
        with self._namespaces_lock:
            return namespace in self._namespaces

    def current_epoch(self, namespace: NamespaceId) -> int:
        state = self._namespace(namespace)
        with self._namespace_section(state):
            return state.epoch

    def current_index_generation(self, namespace: NamespaceId) -> int:
        state = self._namespace(namespace)
        with self._namespace_section(state):
            return state.index_generation

    def record_index_change(self, namespace: NamespaceId) -> None:
        self._ensure_active()
        state = self._namespace(namespace)
        with self._namespace_section(state):
            state.index_generation += 1

    def record_write(self, namespace: NamespaceId, identity: object) -> None:
        self._ensure_active()
        identity = order_sensitive_key(identity)
        state = self._namespace(namespace)
        with self._namespace_section(state):
            state.generation += 1
            if not is_canonicalizable(identity):
                return
            try:
                identity_state = state.identities[canonicalize(identity)]
            except KeyError:
                return
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
            state.index_generation += 1
            state.aliases = {}
            reclaimed = list(state.entry_index.items())
            state.entry_index.clear()
            for entry, _key in reclaimed:
                if entry.identity is not None:
                    state.identities[entry.identity].cached_ref_count -= 1
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


class _CacheCoreDatabaseAvailability(_CacheCoreBase):
    __slots__ = ()

    def is_database_available(self, database: str) -> bool:
        return self._is_database_available(database)

    def set_database_available(self, database: str, *, available: bool) -> None:
        with self._availability_lock:
            try:
                current_available, generation = self._database_availability[database]
            except KeyError:
                current_available, generation = _DEFAULT_DATABASE_AVAILABILITY
            if available != current_available:
                self._database_availability[database] = (available, generation + 1)


class _CacheCoreIdentityAdmission(_CacheCoreBase):
    __slots__ = ()

    def begin_identity_admission(
        self, namespace: NamespaceId, identity: object
    ) -> IdentityCapture:
        self._ensure_active()
        canonical_identity = canonicalize(order_sensitive_key(identity))
        if canonical_identity is None:
            message = "identity must not be None"
            raise UnsupportedCacheRequestError(message)
        availability_generation = self._capture_database_availability(
            namespace.database
        )
        state = self._namespace(namespace)
        with self._namespace_section(state):
            try:
                identity_state = state.identities[canonical_identity]
            except KeyError:
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
            availability_generation=availability_generation,
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
        codec_options: CodecOptions[Any] | None = None,
    ) -> AdmissionOutcome:
        self._ensure_active()
        try:
            canonical_shape = canonicalize(read_shape)
            try:
                encoded = encode_value(value, codec_options)
            except BSONError:
                return AdmissionOutcome.DECLINED_UNENCODABLE
            except OverflowError:
                return AdmissionOutcome.DECLINED_UNENCODABLE
            weight = len(encoded)
            with self._admission_section(
                capture.namespace, capture.availability_generation, weight
            ) as rejected:
                if rejected is not None:
                    return rejected
                key = IdentityCacheKey(
                    capture.namespace, capture.identity, canonical_shape
                )
                state = self._namespace(capture.namespace)
                with self._namespace_section(state):
                    identity_state = _match_identity_state(
                        state, capture.identity, capture.generation_key
                    )
                    if self._is_closed() or identity_state is None:
                        return AdmissionOutcome.DECLINED_STALE
                    if alias is not None:
                        _publish_alias_locked(state, alias, capture.identity)
                entry = CacheEntry(
                    generation_key=capture.generation_key,
                    weight=weight,
                    value=encoded,
                    namespace=capture.namespace,
                    identity=capture.identity,
                )
                admitted, displaced, evicted = self._lru.conditional_put(key, entry)
            self._process_evicted(evicted)

            def _is_still_valid() -> bool:
                return (
                    _match_identity_state(
                        state, capture.identity, capture.generation_key
                    )
                    is not None
                )

            def _on_admit() -> None:
                state.identities[capture.identity].cached_ref_count += 1

            return self._finalize_put(
                state,
                key,
                entry,
                admitted=admitted,
                displaced=displaced,
                is_still_valid=_is_still_valid,
                on_admit=_on_admit,
            )
        finally:
            self._release_identity_capture(capture)

    def _release_identity_capture(self, capture: IdentityCapture) -> None:
        if capture.released:
            return
        capture.released = True
        state = self._namespace(capture.namespace)
        with self._namespace_section(state):
            try:
                identity_state = state.identities[capture.identity]
            except KeyError:
                return
            identity_state.inflight_ref_count -= 1
            _maybe_prune_identity_locked(state, capture.identity, identity_state)


def _publish_alias_locked(
    state: NamespaceState, alias: AliasKey, identity: Canonical
) -> None:
    try:
        previous_identity = state.aliases[alias]
    except KeyError:
        previous_identity = None
    if previous_identity is not None and previous_identity != identity:
        state.identities[previous_identity].alias_keys.discard(alias)
    state.aliases[alias] = identity
    state.identities[identity].alias_keys.add(alias)


def _discard_alias_locked(
    state: NamespaceState, alias: AliasKey, expected_identity: Canonical
) -> None:
    try:
        current_identity = state.aliases[alias]
    except KeyError:
        return
    if current_identity != expected_identity:
        return
    del state.aliases[alias]
    identity_state = state.identities[expected_identity]
    identity_state.alias_keys.discard(alias)
    _maybe_prune_identity_locked(state, expected_identity, identity_state)


class _CacheCoreNamespaceAdmission(_CacheCoreBase):
    __slots__ = ()

    def capture_namespace_generation(self, namespace: NamespaceId) -> NamespaceCapture:
        self._ensure_active()
        availability_generation = self._capture_database_availability(
            namespace.database
        )
        state = self._namespace(namespace)
        with self._namespace_section(state):
            return NamespaceCapture(
                namespace=namespace,
                generation=state.generation,
                availability_generation=availability_generation,
            )

    def admit_namespace(
        self,
        capture: NamespaceCapture,
        discriminator: object,
        value: object,
        *,
        codec_options: CodecOptions[Any] | None = None,
    ) -> AdmissionOutcome:
        self._ensure_active()
        canonical_discriminator = canonicalize(discriminator)
        try:
            encoded = encode_value(value, codec_options)
        except BSONError:
            return AdmissionOutcome.DECLINED_UNENCODABLE
        except OverflowError:
            return AdmissionOutcome.DECLINED_UNENCODABLE
        weight = len(encoded)
        with self._admission_section(
            capture.namespace, capture.availability_generation, weight
        ) as rejected:
            if rejected is not None:
                return rejected
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
        self._process_evicted(evicted)
        return self._finalize_put(
            state,
            key,
            entry,
            admitted=admitted,
            displaced=displaced,
            is_still_valid=lambda: state.generation == capture.generation,
            on_admit=lambda: None,
        )


class _CacheCoreUniqueKeyAdmission(_CacheCoreBase):
    __slots__ = ()

    def discard_stale_alias(
        self, namespace: NamespaceId, alias: AliasKey, expected_identity: Canonical
    ) -> None:
        self._ensure_active()
        state = self._namespace(namespace)
        with self._namespace_section(state):
            _discard_alias_locked(state, alias, expected_identity)

    def discard_namespace_entry(
        self, namespace: NamespaceId, discriminator: object, generation: int
    ) -> None:
        self._ensure_active()
        key = NamespaceCacheKey(namespace, canonicalize(discriminator))
        entry = self._lru.peek(key)
        if entry is None or entry.generation_key != (generation,):
            return
        state = self._namespace(namespace)
        with self._namespace_section(state):
            _discard_entry_locked(state, entry)
        self._lru.remove_exact(key, entry)

    def admit_unique_key_match(
        self,
        namespace_capture: NamespaceCapture,
        discriminator: object,
        identity: object,
        read_shape: object,
        value: object,
        *,
        alias: AliasKey,
        codec_options: CodecOptions[Any] | None = None,
    ) -> AdmissionOutcome:
        self._ensure_active()
        namespace = namespace_capture.namespace
        canonical_discriminator = canonicalize(discriminator)
        canonical_identity = canonicalize(order_sensitive_key(identity))
        if canonical_identity is None:
            message = "identity must not be None"
            raise UnsupportedCacheRequestError(message)
        canonical_shape = canonicalize(read_shape)
        try:
            encoded = encode_value(value, codec_options)
        except BSONError:
            return AdmissionOutcome.DECLINED_UNENCODABLE
        except OverflowError:
            return AdmissionOutcome.DECLINED_UNENCODABLE
        weight = len(encoded)
        with self._admission_section(
            namespace, namespace_capture.availability_generation, weight
        ) as rejected:
            if rejected is not None:
                return rejected
            namespace_key = NamespaceCacheKey(namespace, canonical_discriminator)
            identity_key = IdentityCacheKey(
                namespace, canonical_identity, canonical_shape
            )
            state = self._namespace(namespace)
            with self._namespace_section(state):
                if (
                    self._is_closed()
                    or state.generation != namespace_capture.generation
                ):
                    return AdmissionOutcome.DECLINED_STALE
                try:
                    identity_state = state.identities[canonical_identity]
                except KeyError:
                    identity_state = IdentityState(
                        generation=state.identity_generation_watermark
                    )
                    state.identity_generation_watermark += 1
                    state.identities[canonical_identity] = identity_state
                identity_generation_key = (state.epoch, identity_state.generation)
                _publish_alias_locked(state, alias, canonical_identity)
            namespace_entry = CacheEntry(
                generation_key=(namespace_capture.generation,),
                weight=weight,
                value=encoded,
                namespace=namespace,
                identity=None,
            )
            identity_entry = CacheEntry(
                generation_key=identity_generation_key,
                weight=weight,
                value=encoded,
                namespace=namespace,
                identity=canonical_identity,
            )
            ns_admitted, ns_displaced, ns_evicted = self._lru.conditional_put(
                namespace_key, namespace_entry
            )
            id_admitted, id_displaced, id_evicted = self._lru.conditional_put(
                identity_key, identity_entry
            )
        self._process_evicted(ns_evicted)
        self._process_evicted(id_evicted)
        namespace_outcome = self._finalize_put(
            state,
            namespace_key,
            namespace_entry,
            admitted=ns_admitted,
            displaced=ns_displaced,
            is_still_valid=lambda: state.generation == namespace_capture.generation,
            on_admit=lambda: None,
        )

        def _identity_still_valid() -> bool:
            return (
                _match_identity_state(
                    state, canonical_identity, identity_generation_key
                )
                is not None
            )

        def _on_identity_admit() -> None:
            state.identities[canonical_identity].cached_ref_count += 1

        identity_outcome = self._finalize_put(
            state,
            identity_key,
            identity_entry,
            admitted=id_admitted,
            displaced=id_displaced,
            is_still_valid=_identity_still_valid,
            on_admit=_on_identity_admit,
        )
        if identity_outcome is not AdmissionOutcome.ADMITTED:
            with self._namespace_section(state):
                try:
                    current_identity_state = state.identities[canonical_identity]
                except KeyError:
                    current_identity_state = None
                if (
                    current_identity_state is None
                    or not current_identity_state.is_referenced
                ):
                    _discard_alias_locked(state, alias, canonical_identity)
        if namespace_outcome is AdmissionOutcome.ADMITTED:
            return identity_outcome
        return namespace_outcome


class _CacheCoreLookup(_CacheCoreBase):
    __slots__ = ()

    def lookup_identity(
        self,
        namespace: NamespaceId,
        identity: object,
        read_shape: object,
        *,
        codec_options: CodecOptions[Any] | None = None,
    ) -> LookupResult:
        self._ensure_active()
        if not self._is_database_available(namespace.database):
            self._statistics.record_bypass(BypassReason.STREAM_UNAVAILABLE)
            return LookupResult(hit=False)
        canonical_identity = canonicalize(order_sensitive_key(identity))
        key = IdentityCacheKey(namespace, canonical_identity, canonicalize(read_shape))
        entry = self._lru.peek(key)
        if entry is None:
            self._statistics.record_miss()
            return LookupResult(hit=False)
        state = self._namespace(namespace)
        entry_generation_key = (entry.generation_key[0], entry.generation_key[1])
        with self._namespace_section(state):
            matched = _match_identity_state(
                state, canonical_identity, entry_generation_key
            )
        if matched is None:
            self._statistics.record_miss()
            return LookupResult(hit=False)
        self._lru.touch(key)
        self._statistics.record_hit()
        return LookupResult(hit=True, value=decode_value(entry.value, codec_options))

    def lookup_namespace(
        self,
        namespace: NamespaceId,
        discriminator: object,
        *,
        codec_options: CodecOptions[Any] | None = None,
    ) -> LookupResult:
        self._ensure_active()
        if not self._is_database_available(namespace.database):
            self._statistics.record_bypass(BypassReason.STREAM_UNAVAILABLE)
            return LookupResult(hit=False)
        canonical_discriminator = canonicalize(discriminator)
        key = NamespaceCacheKey(namespace, canonical_discriminator)
        entry = self._lru.peek(key)
        if entry is None:
            self._statistics.record_miss()
            return LookupResult(hit=False)
        state = self._namespace(namespace)
        with self._namespace_section(state):
            valid = (state.generation,) == entry.generation_key
        if not valid:
            self._statistics.record_miss()
            return LookupResult(hit=False)
        self._lru.touch(key)
        self._statistics.record_hit()
        return LookupResult(hit=True, value=decode_value(entry.value, codec_options))

    def resolve_alias(
        self,
        namespace: NamespaceId,
        definition: object,
        value: object,
        collation: object,
    ) -> Canonical | None:
        self._ensure_active()
        if not self._is_database_available(namespace.database):
            self._statistics.record_bypass(BypassReason.STREAM_UNAVAILABLE)
            return None
        alias_key = canonical_alias_key(definition, value, collation)
        state = self._namespace(namespace)
        with self._namespace_section(state):
            try:
                return state.aliases[alias_key]
            except KeyError:
                return None


class _CacheCoreStreamCostTelemetry(_CacheCoreBase):
    __slots__ = ()

    def record_stream_poll(self, database: str) -> None:
        self._stream_cost.record_poll(database)

    def record_logical_event_bytes(self, database: str, count: int) -> None:
        self._stream_cost.record_logical_event_bytes(database, count)

    def record_invalidation_applied(
        self,
        database: str,
        raw_lag_seconds: float,
        wall_seconds: float,
        monotonic_seconds: float,
    ) -> None:
        self._stream_cost.record_invalidation(
            database, raw_lag_seconds, wall_seconds, monotonic_seconds
        )

    def reset_stream_cost_statistics(self, database: str | None = None) -> None:
        if database is None:
            self._stream_cost.reset_all()
        else:
            self._stream_cost.reset(database)

    def stream_cost_snapshot(self, database: str) -> StreamCostSnapshot:
        used_bytes, _entry_count = self._lru.snapshot_usage()
        return self._stream_cost.snapshot(database, resident_bytes=used_bytes)

    def active_stream_cost_databases(self) -> list[str]:
        return self._stream_cost.active_databases()


class CacheCore(
    _CacheCoreLifecycle,
    _CacheCoreNamespaceLifecycle,
    _CacheCoreDatabaseAvailability,
    _CacheCoreIdentityAdmission,
    _CacheCoreNamespaceAdmission,
    _CacheCoreUniqueKeyAdmission,
    _CacheCoreLookup,
    _CacheCoreStreamCostTelemetry,
):
    __slots__ = ()
