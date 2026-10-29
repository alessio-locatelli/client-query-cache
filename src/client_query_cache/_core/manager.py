from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

from bson.errors import BSONError

from client_query_cache._core.canonical import canonicalize, is_canonicalizable
from client_query_cache._core.codec import decode_value, encode_value
from client_query_cache._core.entries import (
    _DEFERRED_MISS,
    _MISS,
    AdmissionOutcome,
    CacheEntry,
    LookupResult,
)
from client_query_cache._core.errors import (
    CacheClosedError,
    CacheConfigurationError,
    UnsupportedCacheRequestError,
)
from client_query_cache._core.find_reads import (
    FindReadShape,
    PreparedFindRead,
    find_discriminator,
)
from client_query_cache._core.keys import (
    IdentityCacheKey,
    NamespaceCacheKey,
    canonical_alias_key,
)
from client_query_cache._core.lifecycle import CacheLifecycleState
from client_query_cache._core.locking import LockOrderGuard, NamespaceLock
from client_query_cache._core.lru import LruPlanChangedError, WeightedLru
from client_query_cache._core.namespace import IdentityState, NamespaceState
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._core.retention import AliasRegistry, RetentionPlan, key_decline
from client_query_cache._core.snapshots import (
    BypassReason,
    CacheSnapshot,
    CacheStatistics,
    RetentionDeclineReason,
    RetentionRecordKind,
)
from client_query_cache._core.stream_cost import (
    DEFAULT_LAG_CAPTURE_WINDOW_CONFIG,
    LagCaptureWindowConfig,
    StreamCostRegistry,
    StreamCostSnapshot,
)
from client_query_cache._types import (
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from typing import Any

    from bson.codec_options import CodecOptions

    from client_query_cache._core.canonical import Canonical
    from client_query_cache._core.contracts import (
        IdentityCaptureView,
        NamespaceCaptureView,
    )
    from client_query_cache._core.find_reads import FindSource
    from client_query_cache._core.keys import AliasKey, CacheKey, NamespaceId
    from client_query_cache._core.residency import CacheObserver, PayloadStore

DEFAULT_BUDGET_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ENTRY_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_NAMESPACES = 1024
_NAMESPACE_METADATA_PROBE_TTL_SECONDS: PositiveFloat = 30.0

_NOT_INDEXED = object()
_DEFAULT_DATABASE_AVAILABILITY = (True, 0)

logger = logging.getLogger(__name__)


def _log_evictions(count: PositiveInt) -> None:
    logger.debug("cache entries evicted", extra={"evicted_count": count})


@dataclass(frozen=True, slots=True)
class CacheCoreConfig:
    budget_bytes: PositiveInt = DEFAULT_BUDGET_BYTES
    max_entry_bytes: PositiveInt = DEFAULT_MAX_ENTRY_BYTES
    lag_capture_window_config: LagCaptureWindowConfig = (
        DEFAULT_LAG_CAPTURE_WINDOW_CONFIG
    )
    max_namespaces: PositiveInt = DEFAULT_MAX_NAMESPACES
    max_entries: PositiveInt | None = None
    max_key_bytes: PositiveInt | None = None

    def __post_init__(self) -> None:
        if type(self.budget_bytes) is not int:
            message = "budget_bytes must be a built-in integer"
            raise CacheConfigurationError(message)
        if type(self.max_entry_bytes) is not int:
            message = "max_entry_bytes must be a built-in integer"
            raise CacheConfigurationError(message)
        if type(self.max_namespaces) is not int:
            message = "max_namespaces must be a built-in integer"
            raise CacheConfigurationError(message)
        if self.budget_bytes <= 0:
            message = "budget_bytes must be positive"
            raise CacheConfigurationError(message)
        if self.max_entry_bytes <= 0:
            message = "max_entry_bytes must be positive"
            raise CacheConfigurationError(message)
        if self.max_namespaces <= 0:
            message = "max_namespaces must be positive"
            raise CacheConfigurationError(message)
        if self.max_entry_bytes > self.budget_bytes:
            message = "max_entry_bytes must not exceed budget_bytes"
            raise CacheConfigurationError(message)
        for name in ("max_entries", "max_key_bytes"):
            limit = getattr(self, name)
            if limit is None:
                continue
            if type(limit) is not int:
                message = f"{name} must be a built-in integer or None"
                raise CacheConfigurationError(message)
            if limit <= 0:
                message = f"{name} must be positive"
                raise CacheConfigurationError(message)


@dataclass(slots=True)
class IdentityCapture:
    namespace: NamespaceId
    identity: Canonical
    generation_key: tuple[NonNegativeInt, NonNegativeInt]
    availability_generation: NonNegativeInt
    state: NamespaceState
    released: bool = field(default=False)

    def release(self) -> None:
        with self.state.alias_registry.section:
            if self.released:
                return
            self.released = True
            with self.state.lock:
                try:
                    identity_state = self.state.identities[self.identity]
                except KeyError:
                    return
                identity_state.inflight_ref_count -= 1
                _maybe_prune_identity_locked(self.state, self.identity, identity_state)


@dataclass(slots=True)
class NamespaceCapture:
    namespace: NamespaceId
    generation_key: tuple[NonNegativeInt, NonNegativeInt]
    availability_generation: NonNegativeInt
    state: NamespaceState

    @property
    def generation(self) -> NonNegativeInt:
        return self.generation_key[0]


@dataclass(slots=True)
class _NamespaceMetadataProbe:
    token: NonNegativeInt
    active_requests: PositiveInt
    expires_at: NonNegativeFloat


def _maybe_prune_identity_locked(
    state: NamespaceState, identity: Canonical, identity_state: IdentityState
) -> None:
    if identity_state.is_referenced:
        return
    for alias_key in identity_state.alias_keys or ():
        state.alias_registry.removed(state, alias_key)
        state.alias_registry.retire(state.aliases.pop(alias_key, None))
    state.alias_registry.identity_removed(state, identity_state)
    state.identities.pop(identity, None)
    state.identity_generation_watermark = max(
        state.identity_generation_watermark, identity_state.generation + 1
    )


def _discard_entry_locked(state: NamespaceState, entry: CacheEntry) -> None:
    indexed_key = state.entry_index.pop(entry, _NOT_INDEXED)
    was_indexed = indexed_key is not _NOT_INDEXED
    state.alias_registry.retire(indexed_key, entry)
    if entry.find_source is not None:
        family = entry.find_source.family
        try:
            bucket = state.find_families[family]
        except KeyError:
            pass  # Invalidation can already have cleared the family.
        else:
            bucket.pop(entry, None)
            if not bucket:
                del state.find_families[family]
    if was_indexed and entry.identity is not None:
        identity_state = state.identities[entry.identity]
        identity_state.cached_ref_count -= 1
        _maybe_prune_identity_locked(state, entry.identity, identity_state)


def _match_identity_state(
    state: NamespaceState,
    identity: Canonical,
    generation_key: tuple[NonNegativeInt, NonNegativeInt],
) -> IdentityState | None:
    try:
        identity_state = state.identities[identity]
    except KeyError:
        return None
    if (state.epoch, identity_state.generation) != generation_key:
        return None
    return identity_state


def _is_registered_state(state: NamespaceState) -> bool:
    return state.tracked


class _CacheCoreBase:
    __slots__ = (
        "_availability_lock",
        "_database_availability",
        "_database_namespaces",
        "_generation",
        "_generation_lock",
        "_guard",
        "_lifecycle",
        "_lifecycle_lock",
        "_lru",
        "_max_entries",
        "_max_key_bytes",
        "_max_namespaces",
        "_namespace_metadata_probes",
        "_namespaces",
        "_namespaces_lock",
        "_next_namespace_metadata_probe_token",
        "_observer",
        "_payloads",
        "_retention",
        "_statistics",
        "_stream_cost",
    )

    def __init__(
        self,
        config: CacheCoreConfig | None = None,
        *,
        observer: CacheObserver | None = None,
        payloads: PayloadStore | None = None,
    ) -> None:
        resolved_config = config if config is not None else CacheCoreConfig()
        self._guard = LockOrderGuard()
        self._availability_lock = threading.RLock()
        self._retention = AliasRegistry(
            resolved_config.max_entries, self._availability_lock, self._guard
        )
        self._observer = observer
        self._payloads = payloads
        self._lru = WeightedLru(
            budget_bytes=resolved_config.budget_bytes,
            max_entry_bytes=resolved_config.max_entry_bytes,
            guard=self._guard,
            track_revision=resolved_config.max_entries is not None,
            on_removed=(
                None if observer is None and payloads is None else self._removed
            ),
        )
        self._namespaces: dict[NamespaceId, NamespaceState] = {}
        self._database_namespaces: dict[str, dict[NamespaceId, None]] = {}
        self._namespaces_lock = threading.Lock()
        self._namespace_metadata_probes: dict[NamespaceId, _NamespaceMetadataProbe] = {}
        self._next_namespace_metadata_probe_token: NonNegativeInt = 0
        self._generation: NonNegativeInt = 0
        self._generation_lock = threading.Lock()
        self._max_namespaces = resolved_config.max_namespaces
        self._max_entries = resolved_config.max_entries
        self._max_key_bytes = resolved_config.max_key_bytes
        self._lifecycle = CacheLifecycleState.ACTIVE
        self._lifecycle_lock = threading.Lock()
        self._statistics = CacheStatistics()
        self._database_availability: dict[str, tuple[bool, NonNegativeInt]] = {}
        self._stream_cost = StreamCostRegistry(
            resolved_config.lag_capture_window_config
        )

    def _is_closed(self) -> bool:
        return self._lifecycle is CacheLifecycleState.CLOSED

    @property
    def max_entry_bytes(self) -> PositiveInt:
        return self._lru.max_entry_bytes

    @property
    def max_namespaces(self) -> PositiveInt:
        return self._max_namespaces

    @property
    def max_entries(self) -> PositiveInt | None:
        return self._max_entries

    def _capture_current(self, capture: IdentityCapture | NamespaceCapture) -> bool:
        state = capture.state
        if self._is_closed() or not state.tracked:
            return False
        if isinstance(capture, NamespaceCapture):
            return state.query_generation_key == capture.generation_key
        return (
            _match_identity_state(state, capture.identity, capture.generation_key)
            is not None
        )

    def _retention_preflight(
        self, capture: IdentityCapture | NamespaceCapture, weight: NonNegativeInt
    ) -> AdmissionOutcome | None:
        with self._admission_section(
            capture.namespace, capture.availability_generation, weight
        ) as rejected:
            if rejected is not None:
                return rejected
            with capture.state.lock:
                return (
                    None
                    if self._capture_current(capture)
                    else AdmissionOutcome.DECLINED_STALE
                )

    def _key_decision(self, *roots: object) -> RetentionDeclineReason | None:
        assert self._max_key_bytes is not None
        return key_decline(self._max_key_bytes, *roots)

    def _limited_put(
        self,
        capture: IdentityCapture | NamespaceCapture,
        key: IdentityCacheKey | NamespaceCacheKey,
        encoded: bytes,
        *,
        decision: RetentionDeclineReason | None,
        alias: AliasKey | None = None,
        alias_decision: RetentionDeclineReason | None = None,
        require_alias: bool = False,
        redundant: NamespaceCacheKey | None = None,
        pending: tuple[RetentionRecordKind, RetentionDeclineReason] | None = None,
        find_source: FindSource | None = None,
    ) -> AdmissionOutcome:
        assert self._max_entries is not None
        state = capture.state
        kind = (
            RetentionRecordKind.IDENTITY_VALUE
            if isinstance(key, IdentityCacheKey)
            else RetentionRecordKind.NAMESPACE_VALUE
        )
        with self._retention.section:
            while True:
                rejected = self._retention_preflight(capture, len(encoded))
                if rejected is not None:
                    return rejected
                with state.lock:
                    if decision is not None:
                        if pending is not None:
                            self._statistics.record_retention_decline(*pending)
                        self._statistics.record_retention_decline(kind, decision)
                        return AdmissionOutcome.DECLINED_RETENTION
                    owner = None
                    if isinstance(key, IdentityCacheKey):
                        try:
                            owner = state.identities[key.identity]
                        except KeyError:
                            generation = (
                                state.epoch,
                                state.identity_generation_watermark,
                            )
                        else:
                            generation = (state.epoch, owner.generation)
                    else:
                        generation = state.query_generation_key
                view = self._lru.planning_view()
                previous = self._lru.peek(key)
                obsolete = None if redundant is None else self._lru.peek(redundant)
                reuse = previous is not None and previous.generation_key == generation
                used, count = self._lru.snapshot_usage()
                order = self._retention.order
                assert order is not None
                plan = RetentionPlan(
                    self._retention,
                    self._lru,
                    self._registered_namespace,
                    view,
                    count + self._retention.count,
                    used,
                    owner,
                    iter(order.values()),
                )
                if obsolete is not None:
                    assert redundant is not None
                    plan.remove_value(redundant, obsolete)
                if not reuse:
                    if previous is not None:
                        plan.remove_value(key, previous)
                    plan.records += 1
                    plan.used += len(encoded)
                try:
                    plan.fit_value()
                except LruPlanChangedError:
                    continue
                alias_block = alias_decision
                if alias is not None and alias_block is None:
                    alias_token = (id(state), alias)
                    delta = (
                        1
                        if alias_token not in order or alias_token in plan.aliases
                        else 0
                    )
                    fits = (
                        plan.fit_alias(state, alias)
                        if require_alias
                        else plan.records + delta <= self._max_entries
                    )
                    if not fits:
                        alias_block = RetentionDeclineReason.ENTRY_CAPACITY
                        if require_alias:
                            return AdmissionOutcome.DECLINED_RETENTION
                entry = (
                    None
                    if reuse
                    else CacheEntry(
                        generation_key=generation,
                        weight=len(encoded),
                        value=self._stored(encoded),
                        namespace=capture.namespace,
                        identity=key.identity
                        if isinstance(key, IdentityCacheKey)
                        else None,
                        find_source=find_source,
                    )
                )
                # Mutators share this transaction; payload callbacks cannot reenter it.
                with state.lock:
                    assert self._capture_current(capture)
                if not self._lru.commit_plan(view, plan.victims, key, entry):
                    if entry is not None:
                        self._release(entry)
                    continue
                if isinstance(key, IdentityCacheKey):
                    with state.lock:
                        if owner is None:
                            owner = IdentityState(generation=generation[1])
                            state.identity_generation_watermark += 1
                            state.identities[key.identity] = owner
                            state.alias_registry.identity_added(
                                state, key.identity, owner
                            )
                        owner.inflight_ref_count += 1
                return self._complete_limited_put(
                    capture,
                    key,
                    plan,
                    entry=entry,
                    previous=previous,
                    obsolete=obsolete,
                    owner=owner,
                    alias=alias,
                    alias_block=alias_block,
                    pending=pending,
                    find_source=find_source,
                )

    def _complete_limited_put(
        self,
        capture: IdentityCapture | NamespaceCapture,
        key: IdentityCacheKey | NamespaceCacheKey,
        plan: RetentionPlan,
        *,
        entry: CacheEntry | None,
        previous: CacheEntry | None,
        obsolete: CacheEntry | None,
        owner: IdentityState | None,
        alias: AliasKey | None,
        alias_block: RetentionDeclineReason | None,
        pending: tuple[RetentionRecordKind, RetentionDeclineReason] | None,
        find_source: FindSource | None,
    ) -> AdmissionOutcome:
        state = capture.state

        try:
            for alias_state, victim_alias in plan.aliases.values():
                with alias_state.lock:
                    _discard_alias_locked(
                        alias_state,
                        victim_alias,
                        alias_state.aliases[victim_alias],
                    )
            evicted = [
                victim
                for _key, victim in plan.victims
                if victim is not previous and victim is not obsolete
            ]
            self._process_evicted(evicted)
            with state.lock:
                for victim in (previous, obsolete):
                    if victim is not None and victim in plan.removed:
                        _discard_entry_locked(state, victim)
            if entry is not None:

                def publish() -> None:
                    if isinstance(key, IdentityCacheKey):
                        assert owner is not None
                        owner.cached_ref_count += 1
                    if find_source is not None:
                        assert isinstance(key, NamespaceCacheKey)
                        state.find_families.setdefault(find_source.family, {})[
                            entry
                        ] = key

                outcome = self._finalize_put(
                    state,
                    key,
                    entry,
                    admitted=True,
                    displaced=None,
                    is_still_valid=lambda: self._capture_current(capture),
                    on_admit=publish,
                )
                assert outcome is AdmissionOutcome.ADMITTED
            if alias is not None:
                if alias_block is None:
                    assert isinstance(key, IdentityCacheKey)
                    with state.lock:
                        _publish_alias_locked(state, alias, key.identity)
                else:
                    self._statistics.record_retention_decline(
                        RetentionRecordKind.ALIAS, alias_block
                    )
            if pending is not None:
                self._statistics.record_retention_decline(*pending)
            return AdmissionOutcome.ADMITTED
        finally:
            if owner is not None and isinstance(key, IdentityCacheKey):
                with state.lock:
                    owner.inflight_ref_count -= 1
                    _maybe_prune_identity_locked(state, key.identity, owner)

    def _removed(self, key: CacheKey, entry: CacheEntry) -> None:
        if self._observer is not None:
            self._observer.removed(key, entry)
        self._release(entry)

    def _stored(self, encoded: bytes) -> object:
        payloads = self._payloads
        return encoded if payloads is None else payloads.store(encoded)

    def _release(self, entry: CacheEntry) -> None:
        if self._payloads is not None:
            self._payloads.release(entry.value)

    def _snapshot(self, stored: object) -> bytes | None:
        payloads = self._payloads
        assert payloads is not None
        return payloads.snapshot(stored)

    def _is_database_available(self, database: str) -> bool:
        with self._availability_lock:
            try:
                available, _generation = self._database_availability[database]
            except KeyError:
                available, _generation = _DEFAULT_DATABASE_AVAILABILITY
            return available

    def _capture_database_availability(self, database: str) -> NonNegativeInt:
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
        availability_generation: NonNegativeInt,
        weight: NonNegativeInt,
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
                if self._is_closed() or len(self._namespaces) >= self._max_namespaces:
                    return NamespaceState(
                        namespace=namespace,
                        lock=NamespaceLock(self._guard),
                        alias_registry=self._retention,
                        tracked=False,
                    )
                generation = self._next_generation()
                state = NamespaceState(
                    namespace=namespace,
                    lock=NamespaceLock(self._guard),
                    alias_registry=self._retention,
                    generation=generation,
                    epoch=generation,
                    index_generation=generation,
                    query_generation_key=(generation, generation),
                    tracked=True,
                )
                self._namespaces[namespace] = state
                self._database_namespaces.setdefault(namespace.database, {})[
                    namespace
                ] = None
            return state

    def _registered_namespace(self, namespace: NamespaceId) -> NamespaceState | None:
        with self._namespaces_lock:
            try:
                return self._namespaces[namespace]
            except KeyError:
                return None

    def _next_generation(self, *, greater_than: NonNegativeInt = 0) -> NonNegativeInt:
        with self._generation_lock:
            self._generation = max(self._generation, greater_than)
            generation = self._generation
            self._generation += 1
            return generation

    def _reclaim_if_evicted_before_publication(
        self, state: NamespaceState, key: CacheKey, entry: CacheEntry
    ) -> bool:
        if self._lru.contains_exact(key, entry):
            return False
        with state.lock:
            _discard_entry_locked(state, entry)
        self._lru.remove_exact(key, entry)
        return True

    def _process_evicted(self, evicted: list[CacheEntry]) -> None:
        if not evicted:
            return
        self._statistics.record_evictions(len(evicted))
        capacity = self._retention.capacity
        if capacity is None:
            _log_evictions(len(evicted))
        else:
            capacity.set_completion(partial(_log_evictions, len(evicted)))
        by_namespace: dict[NamespaceId, list[CacheEntry]] = {}
        for entry in evicted:
            by_namespace.setdefault(entry.namespace, []).append(entry)
        for namespace, entries in by_namespace.items():
            state = self._registered_namespace(namespace)
            if state is None:
                continue
            with state.lock:
                if not state.tracked:
                    continue
                for entry in entries:
                    entry_epoch = entry.generation_key[0]
                    if entry.identity is not None and entry_epoch != state.epoch:
                        continue
                    if entry.identity is None and entry_epoch < state.epoch:
                        continue
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
            self._release(entry)
            return AdmissionOutcome.DECLINED_STALE
        still_resident = self._lru.contains_exact(key, entry)
        rolled_back = False
        with state.lock:
            if not still_resident or self._is_closed() or not is_still_valid():
                rolled_back = True
            else:
                state.entry_index[entry] = key
                on_admit()
                if self._observer is not None:
                    self._observer.admitted(key, entry)
            if displaced is not None:
                _discard_entry_locked(state, displaced)
        if rolled_back:
            self._lru.remove_exact(key, entry)
            return AdmissionOutcome.DECLINED_STALE
        if self._reclaim_if_evicted_before_publication(state, key, entry):
            return AdmissionOutcome.DECLINED_STALE
        return AdmissionOutcome.ADMITTED

    def _admit_namespace_prepared(
        self,
        capture: NamespaceCapture,
        canonical_discriminator: Canonical,
        encoded: bytes,
        *,
        find_source: FindSource | None,
        decision: RetentionDeclineReason | None,
        pending: tuple[RetentionRecordKind, RetentionDeclineReason] | None = None,
    ) -> AdmissionOutcome:
        weight = len(encoded)
        if self._max_entries is not None:
            return self._limited_put(
                capture,
                NamespaceCacheKey(capture.namespace, canonical_discriminator),
                encoded,
                decision=decision,
                find_source=find_source,
                pending=pending,
            )
        with self._admission_section(
            capture.namespace, capture.availability_generation, weight
        ) as rejected:
            if rejected is not None:
                return rejected
            key = NamespaceCacheKey(capture.namespace, canonical_discriminator)
            state = capture.state
            with state.lock:
                if (
                    self._is_closed()
                    or not _is_registered_state(state)
                    or state.query_generation_key != capture.generation_key
                ):
                    return AdmissionOutcome.DECLINED_STALE
                if pending is not None:
                    self._statistics.record_retention_decline(*pending)
                if decision is not None:
                    self._statistics.record_retention_decline(
                        RetentionRecordKind.NAMESPACE_VALUE, decision
                    )
                    return AdmissionOutcome.DECLINED_RETENTION
            entry = CacheEntry(
                generation_key=capture.generation_key,
                weight=weight,
                value=self._stored(encoded),
                namespace=capture.namespace,
                identity=None,
                find_source=find_source,
            )
            admitted, displaced, evicted = self._lru.conditional_put(key, entry)
        self._process_evicted(evicted)

        def publish_source() -> None:
            if find_source is not None:
                state.find_families.setdefault(find_source.family, {})[entry] = key

        return self._finalize_put(
            state,
            key,
            entry,
            admitted=admitted,
            displaced=displaced,
            is_still_valid=lambda: (
                _is_registered_state(state)
                and state.query_generation_key == capture.generation_key
            ),
            on_admit=publish_source,
        )


class _CacheCoreLifecycle(_CacheCoreBase):
    __slots__ = ()

    def close(self) -> None:
        retired: list[object] = []
        with self._retention.section:
            with self._lifecycle_lock:
                if self._is_closed():
                    return
                self._lifecycle = CacheLifecycleState.CLOSED
            self._lru.clear_all()
            with self._namespaces_lock:
                states = list(self._namespaces.values())
            for state in states:
                with state.lock:
                    state.tracked = False
                    retired.append(
                        (
                            state.aliases,
                            state.identities,
                            state.entry_index,
                            state.find_families,
                        )
                    )
                    state.aliases = {}
                    state.identities = {}
                    state.entry_index = {}
                    state.find_families = {}
            self._retention.clear()
            with self._namespaces_lock:
                self._namespaces.clear()
                self._database_namespaces.clear()
                self._namespace_metadata_probes.clear()
        retired.clear()
        logger.info("cache manager closed")

    def record_miss(self) -> None:
        self._statistics.record_miss()

    def record_bypass(self, reason: BypassReason = BypassReason.UNSPECIFIED) -> None:
        self._statistics.record_bypass(reason)

    def record_oversized_bypass(self) -> None:
        self._statistics.record_oversized_bypass()

    def snapshot(self) -> CacheSnapshot:
        with self._retention.section:
            used_bytes, entry_count = self._lru.snapshot_usage()
            hits, misses, evictions, bypasses, oversized_bypasses, bypass_reasons = (
                self._statistics.snapshot()
            )
            return CacheSnapshot(
                lifecycle=self._lifecycle.value,
                used_bytes=used_bytes,
                budget_bytes=self._lru.budget_bytes,
                max_entry_bytes=self._lru.max_entry_bytes,
                entry_count=entry_count,
                hits=hits,
                misses=misses,
                evictions=evictions,
                bypasses=bypasses,
                oversized_bypasses=oversized_bypasses,
                bypass_reasons=bypass_reasons,
                max_entries=self._max_entries,
                max_key_bytes=self._max_key_bytes,
                alias_count=self._retention.count,
                retention_declines=self._statistics.retention_snapshot(),
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

    def can_register_namespace(self, namespace: NamespaceId) -> bool:
        with self._namespaces_lock:
            if self._is_closed():
                return False
            if namespace in self._namespaces:
                return True
            return len(self._namespaces) < self._max_namespaces

    def _expire_namespace_metadata_probes(self, now: NonNegativeFloat) -> None:
        while self._namespace_metadata_probes:
            namespace, probe = next(iter(self._namespace_metadata_probes.items()))
            if probe.expires_at > now:
                return
            del self._namespace_metadata_probes[namespace]

    def begin_namespace_metadata_probe(
        self, namespace: NamespaceId
    ) -> NonNegativeInt | None:
        now = time.monotonic()
        with self._namespaces_lock:
            self._expire_namespace_metadata_probes(now)
            if self._is_closed():
                return None
            if namespace not in self._namespaces and len(self._namespaces) >= (
                self._max_namespaces
            ):
                return None
            try:
                probe = self._namespace_metadata_probes[namespace]
            except KeyError:
                if len(self._namespace_metadata_probes) >= self._max_namespaces:
                    return None
                probe = _NamespaceMetadataProbe(
                    token=self._next_namespace_metadata_probe_token,
                    active_requests=1,
                    expires_at=now + _NAMESPACE_METADATA_PROBE_TTL_SECONDS,
                )
                self._next_namespace_metadata_probe_token += 1
            else:
                probe.active_requests += 1
                probe.expires_at = now + _NAMESPACE_METADATA_PROBE_TTL_SECONDS
                del self._namespace_metadata_probes[namespace]
            self._namespace_metadata_probes[namespace] = probe
            return probe.token

    def _finish_namespace_metadata_probe(
        self, namespace: NamespaceId, token: NonNegativeInt
    ) -> None:
        with self._namespaces_lock:
            self._expire_namespace_metadata_probes(time.monotonic())
            try:
                probe = self._namespace_metadata_probes[namespace]
            except KeyError:
                return
            if probe.token != token:
                return
            if probe.active_requests == 1:
                del self._namespace_metadata_probes[namespace]
            else:
                probe.active_requests -= 1

    def cancel_namespace_metadata_probe(
        self, namespace: NamespaceId, token: NonNegativeInt
    ) -> None:
        self._finish_namespace_metadata_probe(namespace, token)

    def invalidate_namespace_metadata_probe(self, namespace: NamespaceId) -> None:
        with self._namespaces_lock:
            self._namespace_metadata_probes.pop(namespace, None)

    def invalidate_namespace_metadata_probes_for_database(self, database: str) -> None:
        with self._namespaces_lock:
            for namespace in tuple(self._namespace_metadata_probes):
                if namespace.database == database:
                    del self._namespace_metadata_probes[namespace]

    def registered_namespace_metadata(
        self, namespace: NamespaceId
    ) -> tuple[NonNegativeInt, NonNegativeInt] | None:
        state = self._registered_namespace(namespace)
        if state is None:
            return None
        with state.lock:
            if not state.tracked:
                return None
            return state.epoch, state.index_generation

    def try_current_epoch(self, namespace: NamespaceId) -> NonNegativeInt | None:
        state = self._namespace(namespace)
        with state.lock:
            if not state.tracked:
                return None
            return state.epoch

    @contextmanager
    def locked_namespace_metadata_after_probe(
        self,
        namespace: NamespaceId,
        probe_token: NonNegativeInt,
    ) -> Generator[tuple[NonNegativeInt, NonNegativeInt] | None]:
        state = self._reserve_namespace_for_metadata_probe(namespace, probe_token)
        try:
            if state is None:
                yield None
                return
            with state.lock:
                if (
                    not self._namespace_metadata_probe_is_active(namespace, probe_token)
                    or not state.tracked
                ):
                    yield None
                    return
                yield state.epoch, state.index_generation
        finally:
            self._finish_namespace_metadata_probe(namespace, probe_token)

    def _reserve_namespace_for_metadata_probe(
        self, namespace: NamespaceId, token: NonNegativeInt
    ) -> NamespaceState | None:
        with self._namespaces_lock:
            self._expire_namespace_metadata_probes(time.monotonic())
            if self._is_closed():
                return None
            try:
                probe = self._namespace_metadata_probes[namespace]
            except KeyError:
                return None
            if probe.token != token:
                return None
            try:
                return self._namespaces[namespace]
            except KeyError:
                if len(self._namespaces) >= self._max_namespaces:
                    return None
                generation = self._next_generation()
                state = NamespaceState(
                    namespace=namespace,
                    lock=NamespaceLock(self._guard),
                    alias_registry=self._retention,
                    generation=generation,
                    epoch=generation,
                    index_generation=generation,
                    query_generation_key=(generation, generation),
                    tracked=True,
                )
                self._namespaces[namespace] = state
                self._database_namespaces.setdefault(namespace.database, {})[
                    namespace
                ] = None
                return state

    def _namespace_metadata_probe_is_active(
        self, namespace: NamespaceId, token: NonNegativeInt
    ) -> bool:
        with self._namespaces_lock:
            self._expire_namespace_metadata_probes(time.monotonic())
            try:
                probe = self._namespace_metadata_probes[namespace]
            except KeyError:
                return False
            return probe.token == token

    def current_epoch(self, namespace: NamespaceId) -> NonNegativeInt:
        epoch = self.try_current_epoch(namespace)
        return 0 if epoch is None else epoch

    def current_index_generation(self, namespace: NamespaceId) -> NonNegativeInt:
        state = self._namespace(namespace)
        with state.lock:
            if not state.tracked:
                return 0
            return state.index_generation

    def record_index_change(self, namespace: NamespaceId) -> None:
        with self._retention.section:
            self._ensure_active()
            state = self._namespace(namespace)
            with state.lock:
                if not _is_registered_state(state):
                    return
                state.index_generation = self._next_generation(
                    greater_than=state.index_generation + 1
                )
                state.query_generation_key = (state.generation, state.index_generation)
                state.find_families.clear()
                if self._observer is not None:
                    self._observer.namespace_written(state.namespace)

    def record_write(self, namespace: NamespaceId, identity: object) -> None:
        self._ensure_active()
        identity = order_sensitive_key(identity)
        with self._retention.section:
            state = self._namespace(namespace)
            observer = self._observer
            with state.lock:
                state.generation += 1
                state.query_generation_key = (state.generation, state.index_generation)
                state.find_families.clear()
                if not is_canonicalizable(identity):
                    if observer is not None and state.tracked:
                        observer.namespace_written(state.namespace)
                    return
                canonical_identity = canonicalize(identity)
                if observer is not None and state.tracked:
                    observer.identity_written(state.namespace, canonical_identity)
                try:
                    identity_state = state.identities[canonical_identity]
                except KeyError:
                    return
                identity_state.generation += 1
                for alias_key in identity_state.alias_keys or ():
                    state.alias_registry.removed(state, alias_key)
                    state.alias_registry.retire(state.aliases.pop(alias_key, None))
                identity_state.clear_aliases()

    def clear_namespace(self, namespace: NamespaceId) -> None:
        self._ensure_active()
        self._bump_epoch_and_reclaim(namespace)

    def drop_namespace(self, namespace: NamespaceId) -> None:
        self._ensure_active()
        self.invalidate_namespace_metadata_probe(namespace)
        state = self._registered_namespace(namespace)
        if state is None:
            return
        self._bump_epoch_and_reclaim(namespace, release=True, expected_state=state)

    def release_namespace_if_epoch_matches(
        self, namespace: NamespaceId, epoch: NonNegativeInt
    ) -> bool:
        self._ensure_active()
        state = self._registered_namespace(namespace)
        if state is None:
            return False
        return self._bump_epoch_and_reclaim(
            namespace,
            release=True,
            expected_state=state,
            expected_epoch=epoch,
        )

    def create_namespace(self, namespace: NamespaceId) -> None:
        self._ensure_active()
        self._bump_epoch_and_reclaim(namespace)

    def _bump_epoch_and_reclaim(
        self,
        namespace: NamespaceId,
        *,
        release: bool = False,
        expected_state: NamespaceState | None = None,
        expected_epoch: NonNegativeInt | None = None,
    ) -> bool:
        if expected_epoch is None:
            self.invalidate_namespace_metadata_probe(namespace)
        with self._retention.section:
            state = (
                self._namespace(namespace) if expected_state is None else expected_state
            )
            released = False
            with state.lock:
                if not _is_registered_state(state):
                    return False
                if expected_epoch is not None and state.epoch != expected_epoch:
                    return False
                self.invalidate_namespace_metadata_probe(namespace)
                generation = self._next_generation(greater_than=state.generation + 1)
                state.generation = generation
                state.epoch = generation
                state.index_generation = generation
                state.query_generation_key = (generation, generation)
                if self._observer is not None:
                    self._observer.epoch_changed(state.namespace, state.epoch)
                state.alias_registry.retire(state.aliases)
                for alias_key in state.aliases:
                    state.alias_registry.removed(state, alias_key)
                state.aliases = {}
                reclaimed = list(state.entry_index.items())
                state.entry_index.clear()
                state.find_families.clear()
                for entry, _key in reclaimed:
                    if entry.identity is not None:
                        state.identities[entry.identity].cached_ref_count -= 1
                for identity_state in state.identities.values():
                    identity_state.clear_aliases()
                for identity, identity_state in list(state.identities.items()):
                    if not identity_state.is_referenced:
                        state.alias_registry.identity_removed(state, identity_state)
                        del state.identities[identity]
                if release:
                    state.tracked = False
            for entry, key in reclaimed:
                self._lru.remove_exact(key, entry)
        if release:
            try:
                if self._observer is not None:
                    self._observer.namespace_released(namespace, state.epoch)
            finally:
                with self._namespaces_lock:
                    try:
                        del self._namespaces[namespace]
                    except KeyError:
                        pass
                    else:
                        database_namespaces = self._database_namespaces[
                            namespace.database
                        ]
                        del database_namespaces[namespace]
                        if not database_namespaces:
                            del self._database_namespaces[namespace.database]
                        released = True
        logger.debug(
            "cache namespace reclaimed",
            extra={
                "database": namespace.database,
                "collection": namespace.collection,
                "reclaimed_entries": len(reclaimed),
                "released": released,
            },
        )
        return True


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
                if self._observer is not None:
                    self._observer.availability_changed(database, available=available)


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
        with self._retention.section:
            state = self._namespace(namespace)
            with state.lock:
                registered = _is_registered_state(state)
                if not registered:
                    return IdentityCapture(
                        namespace=namespace,
                        identity=canonical_identity,
                        generation_key=(state.epoch, 0),
                        availability_generation=availability_generation,
                        state=state,
                    )
                try:
                    identity_state = state.identities[canonical_identity]
                except KeyError:
                    identity_state = IdentityState(
                        generation=state.identity_generation_watermark
                    )
                    state.identity_generation_watermark += 1
                    state.identities[canonical_identity] = identity_state
                    state.alias_registry.identity_added(
                        state, canonical_identity, identity_state
                    )
                identity_state.inflight_ref_count += 1
                generation_key = (state.epoch, identity_state.generation)
            return IdentityCapture(
                namespace=state.namespace,
                identity=canonical_identity,
                generation_key=generation_key,
                availability_generation=availability_generation,
                state=state,
            )

    def admit_identity(
        self,
        capture: IdentityCaptureView,
        read_shape: object,
        value: object,
        *,
        alias: AliasKey | None = None,
        codec_options: CodecOptions[Any] | None = None,
    ) -> AdmissionOutcome:
        self._ensure_active()
        try:
            encoded = encode_value(value, codec_options)
        except BSONError:
            capture.release()
            return AdmissionOutcome.DECLINED_UNENCODABLE
        except OverflowError:
            capture.release()
            return AdmissionOutcome.DECLINED_UNENCODABLE
        except BaseException:
            capture.release()
            raise
        return self._admit_identity_encoded(capture, read_shape, encoded, alias)

    def admit_identity_encoded(
        self,
        capture: IdentityCaptureView,
        read_shape: object,
        encoded: bytes,
        *,
        alias: AliasKey | None = None,
    ) -> AdmissionOutcome:
        try:
            self._ensure_active()
        except CacheClosedError:
            capture.release()
            raise
        return self._admit_identity_encoded(capture, read_shape, encoded, alias)

    def _admit_identity_encoded(
        self,
        capture: IdentityCaptureView,
        read_shape: object,
        encoded: bytes,
        alias: AliasKey | None,
    ) -> AdmissionOutcome:
        assert isinstance(capture, IdentityCapture)
        state = capture.state
        try:
            canonical_shape = canonicalize(read_shape)
            weight = len(encoded)
            decision = None
            alias_decision = None
            if self._max_key_bytes is not None:
                rejected = self._retention_preflight(capture, weight)
                if rejected is not None:
                    return rejected
                decision = self._key_decision(capture.identity, canonical_shape)
                if decision is None and alias is not None:
                    alias_decision = self._key_decision(alias, capture.identity)
            if self._max_entries is not None:
                return self._limited_put(
                    capture,
                    IdentityCacheKey(
                        capture.namespace, capture.identity, canonical_shape
                    ),
                    encoded,
                    decision=decision,
                    alias=alias,
                    alias_decision=alias_decision,
                )
            with self._admission_section(
                capture.namespace, capture.availability_generation, weight
            ) as rejected:
                if rejected is not None:
                    return rejected
                key = IdentityCacheKey(
                    capture.namespace, capture.identity, canonical_shape
                )
                with state.lock:
                    identity_state = _match_identity_state(
                        state, capture.identity, capture.generation_key
                    )
                    if (
                        self._is_closed()
                        or not _is_registered_state(state)
                        or identity_state is None
                    ):
                        return AdmissionOutcome.DECLINED_STALE
                    if decision is not None:
                        self._statistics.record_retention_decline(
                            RetentionRecordKind.IDENTITY_VALUE, decision
                        )
                        return AdmissionOutcome.DECLINED_RETENTION
                    if alias is not None:
                        if alias_decision is None:
                            _publish_alias_locked(state, alias, capture.identity)
                        else:
                            self._statistics.record_retention_decline(
                                RetentionRecordKind.ALIAS, alias_decision
                            )
                entry = CacheEntry(
                    generation_key=capture.generation_key,
                    weight=weight,
                    value=self._stored(encoded),
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
            capture.release()


def _publish_alias_locked(
    state: NamespaceState, alias: AliasKey, identity: Canonical
) -> None:
    alias = state.alias_registry.canonical_alias(state, alias)
    try:
        previous_identity = state.aliases[alias]
    except KeyError:
        previous_identity = None
        state.alias_registry.added(state, alias)
    else:
        state.alias_registry.republished(state, alias)
        state.alias_registry.retire(previous_identity)
    if previous_identity is not None and previous_identity != identity:
        state.identities[previous_identity].discard_alias(alias)
    state.aliases[alias] = identity
    state.identities[identity].add_alias(alias)


def _discard_alias_locked(
    state: NamespaceState, alias: AliasKey, expected_identity: Canonical
) -> None:
    try:
        current_identity = state.aliases[alias]
    except KeyError:
        return
    if current_identity != expected_identity:
        return
    state.alias_registry.removed(state, alias)
    state.alias_registry.retire(current_identity)
    del state.aliases[alias]
    identity_state = state.identities[expected_identity]
    identity_state.discard_alias(alias)
    _maybe_prune_identity_locked(state, expected_identity, identity_state)


class _CacheCoreNamespaceAdmission(_CacheCoreBase):
    __slots__ = ()

    def capture_namespace_generation(self, namespace: NamespaceId) -> NamespaceCapture:
        self._ensure_active()
        availability_generation = self._capture_database_availability(
            namespace.database
        )
        state = self._namespace(namespace)
        with state.lock:
            return NamespaceCapture(
                namespace=state.namespace,
                generation_key=state.query_generation_key,
                availability_generation=availability_generation,
                state=state,
            )

    def admit_namespace(
        self,
        capture: NamespaceCaptureView,
        discriminator: object,
        value: object,
        *,
        codec_options: CodecOptions[Any] | None = None,
        find_source: FindSource | None = None,
    ) -> AdmissionOutcome:
        self._ensure_active()
        try:
            encoded = encode_value(value, codec_options)
        except BSONError:
            return AdmissionOutcome.DECLINED_UNENCODABLE
        except OverflowError:
            return AdmissionOutcome.DECLINED_UNENCODABLE
        return self._admit_namespace_encoded(
            capture, discriminator, encoded, find_source
        )

    def admit_namespace_encoded(
        self,
        capture: NamespaceCaptureView,
        discriminator: object,
        encoded: bytes,
        *,
        find_source: FindSource | None = None,
    ) -> AdmissionOutcome:
        self._ensure_active()
        return self._admit_namespace_encoded(
            capture, discriminator, encoded, find_source
        )

    def _admit_namespace_encoded(
        self,
        capture: NamespaceCaptureView,
        discriminator: object,
        encoded: bytes,
        find_source: FindSource | None,
    ) -> AdmissionOutcome:
        assert isinstance(capture, NamespaceCapture)
        canonical_discriminator = canonicalize(discriminator)
        weight = len(encoded)
        decision = None
        if self._max_key_bytes is not None:
            rejected = self._retention_preflight(capture, weight)
            if rejected is not None:
                return rejected
            decision = self._key_decision(canonical_discriminator)
        return self._admit_namespace_prepared(
            capture,
            canonical_discriminator,
            encoded,
            find_source=find_source,
            decision=decision,
        )


class _CacheCoreUniqueKeyAdmission(_CacheCoreBase):
    __slots__ = ()

    def _admit_unique_limited(
        self,
        capture: NamespaceCapture,
        discriminator: Canonical,
        identity: Canonical,
        shape: Canonical,
        encoded: bytes,
        *,
        alias: AliasKey,
    ) -> AdmissionOutcome:
        rejected = self._retention_preflight(capture, len(encoded))
        if rejected is not None:
            return rejected
        blocked = (RetentionRecordKind.ALIAS, RetentionDeclineReason.ENTRY_CAPACITY)
        identity_decision = None
        alias_decision = None
        if self._max_entries != 1 and self._max_key_bytes is not None:
            identity_decision = self._key_decision(identity, shape)
            if identity_decision is not None:
                blocked = (RetentionRecordKind.IDENTITY_VALUE, identity_decision)
            else:
                alias_decision = self._key_decision(alias, identity)
                if alias_decision is not None:
                    blocked = (RetentionRecordKind.ALIAS, alias_decision)
        eligible = (
            self._max_entries != 1
            and identity_decision is None
            and alias_decision is None
        )
        if not eligible:
            decision = None
            if self._max_key_bytes is not None:
                decision = self._key_decision(discriminator)
            return self._admit_namespace_prepared(
                capture,
                discriminator,
                encoded,
                find_source=None,
                decision=decision,
                pending=blocked,
            )
        namespace_key = NamespaceCacheKey(capture.namespace, discriminator)
        identity_key = IdentityCacheKey(capture.namespace, identity, shape)
        prepared_fallback = False
        namespace_decision = None
        while True:
            with self._retention.section:
                outcome = self._limited_put(
                    capture,
                    identity_key,
                    encoded,
                    decision=None,
                    alias=alias,
                    require_alias=True,
                    redundant=namespace_key,
                )
                if outcome is not AdmissionOutcome.DECLINED_RETENTION:
                    return outcome
                if prepared_fallback:
                    return self._limited_put(
                        capture,
                        namespace_key,
                        encoded,
                        decision=namespace_decision,
                        pending=blocked,
                    )
            if self._max_key_bytes is not None:
                namespace_decision = self._key_decision(discriminator)
            prepared_fallback = True

    def discard_stale_alias(
        self,
        capture: NamespaceCaptureView,
        alias: AliasKey,
        expected_identity: Canonical,
    ) -> None:
        with self._retention.section:
            self._ensure_active()
            assert isinstance(capture, NamespaceCapture)
            state = capture.state
            with state.lock:
                if (
                    state.tracked
                    and state.query_generation_key == capture.generation_key
                ):
                    _discard_alias_locked(state, alias, expected_identity)

    def discard_namespace_entry(
        self, capture: NamespaceCaptureView, discriminator: object
    ) -> None:
        with self._retention.section:
            self._ensure_active()
            assert isinstance(capture, NamespaceCapture)
            key = NamespaceCacheKey(capture.namespace, canonicalize(discriminator))
            entry = self._lru.peek(key)
            if entry is None or entry.generation_key != capture.generation_key:
                return
            state = capture.state
            with state.lock:
                if (
                    not state.tracked
                    or state.query_generation_key != capture.generation_key
                ):
                    return
                _discard_entry_locked(state, entry)
            self._lru.remove_exact(key, entry)

    def admit_unique_key_match(
        self,
        namespace_capture: NamespaceCaptureView,
        discriminator: object,
        identity: object,
        read_shape: object,
        value: object,
        *,
        alias: AliasKey,
        codec_options: CodecOptions[Any] | None = None,
    ) -> AdmissionOutcome:
        self._ensure_active()
        assert isinstance(namespace_capture, NamespaceCapture)
        canonical_identity = canonicalize(order_sensitive_key(identity))
        if canonical_identity is None:
            message = "identity must not be None"
            raise UnsupportedCacheRequestError(message)
        try:
            encoded = encode_value(value, codec_options)
        except BSONError:
            return AdmissionOutcome.DECLINED_UNENCODABLE
        except OverflowError:
            return AdmissionOutcome.DECLINED_UNENCODABLE
        namespace = namespace_capture.namespace
        canonical_discriminator = canonicalize(discriminator)
        canonical_shape = canonicalize(read_shape)
        weight = len(encoded)
        if self._max_entries is not None:
            return self._admit_unique_limited(
                namespace_capture,
                canonical_discriminator,
                canonical_identity,
                canonical_shape,
                encoded,
                alias=alias,
            )
        namespace_decision = None
        identity_decision = None
        alias_decision = None
        if self._max_key_bytes is not None:
            rejected = self._retention_preflight(namespace_capture, weight)
            if rejected is not None:
                return rejected
            namespace_decision = self._key_decision(canonical_discriminator)
            identity_decision = self._key_decision(canonical_identity, canonical_shape)
            if identity_decision is not None:
                outcome = self._admit_namespace_prepared(
                    namespace_capture,
                    canonical_discriminator,
                    encoded,
                    find_source=None,
                    decision=namespace_decision,
                    pending=(RetentionRecordKind.IDENTITY_VALUE, identity_decision),
                )
                return (
                    AdmissionOutcome.DECLINED_RETENTION
                    if outcome is AdmissionOutcome.ADMITTED
                    else outcome
                )
            alias_decision = self._key_decision(alias, canonical_identity)
        with self._admission_section(
            namespace, namespace_capture.availability_generation, weight
        ) as rejected:
            if rejected is not None:
                return rejected
            namespace_key = NamespaceCacheKey(namespace, canonical_discriminator)
            identity_key = IdentityCacheKey(
                namespace, canonical_identity, canonical_shape
            )
            state = namespace_capture.state
            with state.lock:
                if (
                    self._is_closed()
                    or not _is_registered_state(state)
                    or state.query_generation_key != namespace_capture.generation_key
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
                    state.alias_registry.identity_added(
                        state, canonical_identity, identity_state
                    )
                identity_generation_key = (state.epoch, identity_state.generation)
                if alias_decision is None:
                    _publish_alias_locked(state, alias, canonical_identity)
                else:
                    self._statistics.record_retention_decline(
                        RetentionRecordKind.ALIAS, alias_decision
                    )
            namespace_entry = None
            if namespace_decision is None:
                namespace_entry = CacheEntry(
                    generation_key=namespace_capture.generation_key,
                    weight=weight,
                    value=self._stored(encoded),
                    namespace=namespace,
                    identity=None,
                )
            identity_entry = CacheEntry(
                generation_key=identity_generation_key,
                weight=weight,
                value=self._stored(encoded),
                namespace=namespace,
                identity=canonical_identity,
            )
            if namespace_entry is not None:
                ns_admitted, ns_displaced, ns_evicted = self._lru.conditional_put(
                    namespace_key, namespace_entry
                )
            else:
                ns_admitted, ns_displaced, ns_evicted = False, None, []
            id_admitted, id_displaced, id_evicted = self._lru.conditional_put(
                identity_key, identity_entry
            )
        self._process_evicted(ns_evicted)
        self._process_evicted(id_evicted)
        if namespace_entry is not None:
            namespace_outcome = self._finalize_put(
                state,
                namespace_key,
                namespace_entry,
                admitted=ns_admitted,
                displaced=ns_displaced,
                is_still_valid=lambda: (
                    _is_registered_state(state)
                    and state.query_generation_key == namespace_capture.generation_key
                ),
                on_admit=lambda: None,
            )
        else:
            assert namespace_decision is not None
            self._statistics.record_retention_decline(
                RetentionRecordKind.NAMESPACE_VALUE, namespace_decision
            )
            namespace_outcome = AdmissionOutcome.DECLINED_RETENTION

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
            with state.lock:
                try:
                    current_identity_state = state.identities[canonical_identity]
                except KeyError:
                    current_identity_state = None
                if (
                    current_identity_state is None
                    or not current_identity_state.is_referenced
                ):
                    _discard_alias_locked(state, alias, canonical_identity)
        if (
            namespace_outcome is AdmissionOutcome.ADMITTED
            or identity_outcome is not AdmissionOutcome.ADMITTED
        ):
            return identity_outcome
        return namespace_outcome


def _find_candidate_order(
    candidate: tuple[CacheEntry, NamespaceCacheKey],
) -> tuple[bool, NonNegativeInt]:
    descriptor = candidate[0].find_source
    assert descriptor is not None
    # Zero denotes unlimited and sorts after every covering positive limit.
    return descriptor.limit == 0, descriptor.limit


class _CacheCoreLookup(_CacheCoreBase):
    __slots__ = ()

    def _probe_namespace_entry(
        self,
        state: NamespaceState,
        key: NamespaceCacheKey,
        expected: CacheEntry | None = None,
    ) -> CacheEntry | None:
        entry = self._lru.peek(key)
        if entry is None or (expected is not None and entry is not expected):
            return None
        with state.lock:
            valid = state.query_generation_key == entry.generation_key
        return entry if valid else None

    def lookup_find(
        self,
        namespace: NamespaceId,
        shape: FindReadShape | PreparedFindRead,
        *,
        codec_options: CodecOptions[Any] | None = None,
    ) -> LookupResult:
        encoded = self.lookup_find_encoded(namespace, shape)
        if encoded is None:
            return _MISS
        documents: list[object] = decode_value(  # type: ignore[assignment]
            encoded, codec_options
        )
        if not isinstance(shape.limit, bool) and shape.limit > 0:
            documents = documents[: shape.limit]
        return LookupResult(hit=True, value=documents)

    def lookup_find_encoded(
        self, namespace: NamespaceId, shape: FindReadShape | PreparedFindRead
    ) -> bytes | None:
        self._ensure_active()
        if not self._is_database_available(namespace.database):
            self._statistics.record_bypass(BypassReason.STREAM_UNAVAILABLE)
            return None
        state = self._namespace(namespace)
        if isinstance(shape, FindReadShape):
            shape = PreparedFindRead(canonicalize(shape.family), shape.limit)
        family = shape.family
        key = NamespaceCacheKey(namespace, shape.discriminator)
        entry = self._probe_namespace_entry(state, key)
        if entry is None and not isinstance(shape.limit, bool) and shape.limit > 0:
            with state.lock:
                try:
                    candidates = tuple(state.find_families[hash(family)].items())
                except KeyError:
                    candidates = ()
            for token, source_key in sorted(candidates, key=_find_candidate_order):
                descriptor = token.find_source
                assert descriptor is not None
                limit = descriptor.limit
                if limit != 0 and limit < shape.limit:
                    continue
                if source_key.discriminator != find_discriminator(family, limit):
                    continue
                candidate = self._probe_namespace_entry(state, source_key, token)
                if candidate is not None:
                    key, entry = source_key, candidate
                    break
        if entry is None:
            self._statistics.record_miss()
            return None
        self._lru.touch(key)
        value = entry.value
        if not isinstance(value, bytes):
            value = self._snapshot(value)
            if value is None:
                self._statistics.record_miss()
                return None
        self._statistics.record_hit()
        return value

    def lookup_identity(
        self,
        namespace: NamespaceId,
        identity: object,
        read_shape: object,
        *,
        codec_options: CodecOptions[Any] | None = None,
        defer_miss: bool = False,
    ) -> LookupResult:
        encoded = self._lookup_identity_bytes(
            namespace, identity, read_shape, defer_miss=defer_miss
        )
        if isinstance(encoded, LookupResult):
            return encoded
        return LookupResult(hit=True, value=decode_value(encoded, codec_options))

    def lookup_identity_encoded(
        self, namespace: NamespaceId, identity: object, read_shape: object
    ) -> bytes | None:
        encoded = self._lookup_identity_bytes(
            namespace, identity, read_shape, defer_miss=False
        )
        return encoded if isinstance(encoded, bytes) else None

    def _lookup_identity_bytes(
        self,
        namespace: NamespaceId,
        identity: object,
        read_shape: object,
        *,
        defer_miss: bool,
    ) -> bytes | LookupResult:
        self._ensure_active()
        if not self._is_database_available(namespace.database):
            self._statistics.record_bypass(BypassReason.STREAM_UNAVAILABLE)
            return _MISS
        canonical_identity = canonicalize(order_sensitive_key(identity))
        key = IdentityCacheKey(namespace, canonical_identity, canonicalize(read_shape))
        entry = self._lru.peek(key)
        if entry is None:
            return self._namespace_miss(defer_miss=defer_miss)
        state = self._namespace(namespace)
        entry_generation_key = (entry.generation_key[0], entry.generation_key[1])
        with state.lock:
            matched = _match_identity_state(
                state, canonical_identity, entry_generation_key
            )
        if matched is None:
            return self._namespace_miss(defer_miss=defer_miss)
        self._lru.touch(key)
        value = entry.value
        if not isinstance(value, bytes):
            value = self._snapshot(value)
            if value is None:
                return self._namespace_miss(defer_miss=defer_miss)
        self._statistics.record_hit()
        return value

    def lookup_namespace(
        self,
        namespace: NamespaceId,
        discriminator: object,
        *,
        codec_options: CodecOptions[Any] | None = None,
        defer_miss: bool = False,
    ) -> LookupResult:
        encoded = self.lookup_namespace_encoded(
            namespace, discriminator, defer_miss=defer_miss
        )
        if isinstance(encoded, LookupResult):
            return encoded
        return LookupResult(hit=True, value=decode_value(encoded, codec_options))

    def lookup_namespace_encoded(
        self,
        namespace: NamespaceId,
        discriminator: object,
        *,
        defer_miss: bool = False,
    ) -> bytes | LookupResult:
        self._ensure_active()
        if not self._is_database_available(namespace.database):
            self._statistics.record_bypass(BypassReason.STREAM_UNAVAILABLE)
            return _MISS
        canonical_discriminator = canonicalize(discriminator)
        key = NamespaceCacheKey(namespace, canonical_discriminator)
        entry = self._lru.peek(key)
        if entry is None:
            return self._namespace_miss(defer_miss=defer_miss)
        state = self._namespace(namespace)
        with state.lock:
            valid = state.query_generation_key == entry.generation_key
        if not valid:
            return self._namespace_miss(defer_miss=defer_miss)
        self._lru.touch(key)
        value = entry.value
        if not isinstance(value, bytes):
            value = self._snapshot(value)
            if value is None:
                return self._namespace_miss(defer_miss=defer_miss)
        self._statistics.record_hit()
        return value

    def _namespace_miss(self, *, defer_miss: bool) -> LookupResult:
        if defer_miss:
            return _DEFERRED_MISS
        self._statistics.record_miss()
        return _MISS

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
        with state.lock:
            try:
                return state.aliases[alias_key]
            except KeyError:
                return None


class _CacheCoreStreamCostTelemetry(_CacheCoreBase):
    __slots__ = ()

    def record_stream_poll(self, database: str) -> None:
        self._stream_cost.record_poll(database)

    def record_logical_event_bytes(self, database: str, count: NonNegativeInt) -> None:
        self._stream_cost.record_logical_event_bytes(database, count)

    def record_invalidation_applied(
        self,
        database: str,
        raw_lag_seconds: float,
        wall_seconds: NonNegativeFloat,
        monotonic_seconds: NonNegativeFloat,
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
