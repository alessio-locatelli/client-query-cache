from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from client_query_cache._core.keys import IdentityCacheKey
from client_query_cache._shared.wire import KeyCache, encode_key
from client_query_cache._shared_index import OwnerIndex, Payload
from client_query_cache._types import NonNegativeFloat, NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from client_query_cache._core.canonical import Canonical
    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import CacheKey, NamespaceId

_SHAPE_KEYS: Final = 256


@dataclass(frozen=True, slots=True)
class SharedIndexLimits:
    slots: PositiveInt
    arena_bytes: PositiveInt
    namespaces: PositiveInt
    ring_tokens: PositiveInt
    local_miss_admission: bool = False
    native_admission_queue: bool = False

    def __post_init__(self) -> None:
        if self.native_admission_queue and not self.local_miss_admission:
            raise ValueError("native admission queues require local miss capture")


@dataclass(frozen=True, slots=True)
class NamespaceSlot:
    database: NonNegativeInt
    namespace: NonNegativeInt


class ArenaPayloads:
    __slots__ = ("_index",)

    def __init__(self, index: OwnerIndex) -> None:
        self._index = index

    def store(self, encoded: bytes) -> object:
        payload = self._index.store(encoded)
        return encoded if payload is None else payload

    def release(self, stored: object) -> None:
        if isinstance(stored, Payload):
            self._index.release(stored)

    def snapshot(self, stored: object) -> bytes | None:
        assert isinstance(stored, Payload)
        return self._index.snapshot(stored)


class IndexPublisher:
    __slots__ = (
        "_available_since",
        "_capacity",
        "_databases",
        "_epochs",
        "_finds",
        "_free_slots",
        "_identities",
        "_index",
        "_lock",
        "_namespaces",
        "_next_slot",
        "_published",
        "_shapes",
        "_tokens",
        "_unpublished_finds",
    )

    def __init__(
        self, index: OwnerIndex, databases: tuple[str, ...], namespaces: PositiveInt
    ) -> None:
        self._index = index
        self._databases = {database: slot for slot, database in enumerate(databases)}
        now = time.monotonic()
        self._available_since: dict[str, NonNegativeFloat | None] = dict.fromkeys(
            databases, now
        )
        self._capacity = namespaces
        self._namespaces: dict[NamespaceId, NamespaceSlot] = {}
        self._epochs: dict[NamespaceId, NonNegativeInt] = {}
        self._free_slots: list[NonNegativeInt] = []
        self._next_slot: NonNegativeInt = 0
        self._published: dict[Payload, tuple[NonNegativeInt, CacheKey]] = {}
        self._identities: dict[tuple[NamespaceId, Canonical], set[Payload]] = {}
        self._finds: dict[NamespaceId, set[Payload]] = {}
        self._unpublished_finds: dict[NamespaceId, set[CacheEntry]] = {}
        self._tokens: dict[NonNegativeInt, CacheKey] = {}
        self._shapes = KeyCache(_SHAPE_KEYS)
        self._lock = threading.Lock()
        for slot in self._databases.values():
            index.set_available(slot, available=True)

    def assign(
        self, namespace: NamespaceId, epoch: NonNegativeInt
    ) -> NamespaceSlot | None:
        database = self._databases[namespace.database]
        with self._lock:
            try:
                slot = self._namespaces[namespace]
            except KeyError:
                if self._free_slots:
                    slot_number = self._free_slots.pop()
                elif self._next_slot < self._capacity:
                    slot_number = self._next_slot
                    self._next_slot += 1
                else:
                    return None
                slot = NamespaceSlot(database, slot_number)
                self._namespaces[namespace] = slot
                self._epochs[namespace] = epoch
            self._raise_epoch(namespace, epoch)
            self._index.set_epoch(slot.namespace, self._epochs[namespace])
            self._index.set_find_complete(
                slot.namespace, namespace not in self._unpublished_finds
            )
        return slot

    def assigned(self, namespace: NamespaceId) -> NamespaceSlot | None:
        with self._lock:
            try:
                return self._namespaces[namespace]
            except KeyError:
                return None

    def _raise_epoch(self, namespace: NamespaceId, epoch: NonNegativeInt) -> None:
        self._epochs[namespace] = max(self._epochs[namespace], epoch)

    def progress(self, database: str) -> None:
        self._index.set_progress(self._databases[database], time.monotonic_ns())

    def key(self, token: NonNegativeInt) -> CacheKey | None:
        with self._lock:
            try:
                return self._tokens[token]
            except KeyError:
                return None

    def admitted(self, key: CacheKey, entry: CacheEntry) -> None:
        payload = entry.value
        with self._lock:
            if not isinstance(payload, Payload):
                if entry.find_source is not None:
                    self._find_unpublished(key.namespace, entry)
                return
            try:
                namespace = self._namespaces[key.namespace]
            except KeyError:
                if entry.find_source is not None:
                    self._find_unpublished(key.namespace, entry)
                return
            if isinstance(key, IdentityCacheKey):
                identity = encode_key(key.identity)
                shape = self._shapes.encode(key.read_shape)
            elif entry.find_source is not None:
                discriminator = key.discriminator
                assert isinstance(discriminator, tuple)
                parts = discriminator[1]
                assert isinstance(parts, tuple)
                family = self._shapes.encode(parts[0])
                token = self._index.publish_find(
                    namespace.database,
                    namespace.namespace,
                    self._epochs[key.namespace],
                    family,
                    entry.find_source.limit,
                    payload,
                )
                if token is None:
                    self._find_unpublished(key.namespace, entry)
                    return
                self._remember_publication(key, payload, token)
                return
            else:
                identity = b""
                shape = self._shapes.encode(key.discriminator)
            token = self._index.publish(
                namespace.database,
                namespace.namespace,
                self._epochs[key.namespace],
                identity,
                shape,
                payload,
            )
            if token is None:
                return
            self._remember_publication(key, payload, token)

    def _remember_publication(
        self, key: CacheKey, payload: Payload, token: NonNegativeInt
    ) -> None:
        self._published[payload] = (token, key)
        if isinstance(key, IdentityCacheKey):
            self._identities.setdefault((key.namespace, key.identity), set()).add(
                payload
            )
        else:
            self._finds.setdefault(key.namespace, set()).add(payload)
        self._tokens[token] = key

    def _find_unpublished(self, namespace: NamespaceId, entry: CacheEntry) -> None:
        self._unpublished_finds.setdefault(namespace, set()).add(entry)
        try:
            slot = self._namespaces[namespace]
        except KeyError:
            return
        self._index.set_find_complete(slot.namespace, complete=False)

    def _forget_unpublished(
        self, namespace: NamespaceId, entry: CacheEntry | None = None
    ) -> None:
        try:
            unpublished = self._unpublished_finds[namespace]
        except KeyError:
            return
        if entry is not None:
            unpublished.discard(entry)
            if unpublished:
                return
        del self._unpublished_finds[namespace]
        try:
            slot = self._namespaces[namespace]
        except KeyError:
            return
        self._index.set_find_complete(slot.namespace, complete=True)

    def _forget(self, payload: Payload) -> CacheKey | None:
        try:
            token, key = self._published.pop(payload)
        except KeyError:
            return None
        self._index.unpublish(payload)
        del self._tokens[token]
        return key

    def removed(self, _key: CacheKey, entry: CacheEntry) -> None:
        payload = entry.value
        with self._lock:
            self._forget_unpublished(_key.namespace, entry)
            if not isinstance(payload, Payload):
                return
            key = self._forget(payload)
            if key is None:
                return
            if isinstance(key, IdentityCacheKey):
                members = self._identities[key.namespace, key.identity]
            else:
                members = self._finds[key.namespace]
            members.discard(payload)
            if not members:
                if isinstance(key, IdentityCacheKey):
                    del self._identities[key.namespace, key.identity]
                else:
                    del self._finds[key.namespace]

    def _invalidate_finds(self, namespace: NamespaceId) -> None:
        self._forget_unpublished(namespace)
        try:
            payloads = self._finds.pop(namespace)
        except KeyError:
            return
        for payload in payloads:
            self._forget(payload)

    def namespace_written(self, namespace: NamespaceId) -> None:
        with self._lock:
            self._forget_unpublished(namespace)
            try:
                slot = self._namespaces[namespace]
            except KeyError:
                return
            self._index.record_write(slot.namespace)
            self._invalidate_finds(namespace)

    def identity_written(self, namespace: NamespaceId, identity: Canonical) -> None:
        with self._lock:
            self._forget_unpublished(namespace)
            try:
                slot = self._namespaces[namespace]
            except KeyError:
                return
            self._index.record_write(slot.namespace)
            self._invalidate_finds(namespace)
            try:
                payloads = self._identities.pop((namespace, identity))
            except KeyError:
                return
            for payload in payloads:
                self._forget(payload)

    def epoch_changed(self, namespace: NamespaceId, epoch: NonNegativeInt) -> None:
        with self._lock:
            try:
                slot = self._namespaces[namespace]
            except KeyError:
                return
            self._invalidate_finds(namespace)
            self._raise_epoch(namespace, epoch)
            self._index.set_epoch(slot.namespace, self._epochs[namespace])

    def namespace_released(self, namespace: NamespaceId, epoch: NonNegativeInt) -> None:
        with self._lock:
            try:
                assigned_epoch = self._epochs[namespace]
            except KeyError:
                return
            if assigned_epoch != epoch:
                return
            self._invalidate_finds(namespace)
            slot = self._namespaces[namespace]
            del self._namespaces[namespace]
            del self._epochs[namespace]
            self._free_slots.append(slot.namespace)

    def availability_changed(self, database: str, *, available: bool) -> None:
        with self._lock:
            self._available_since[database] = time.monotonic() if available else None
            self._index.set_available(self._databases[database], available=available)

    def available_since(self, database: str) -> NonNegativeFloat | None:
        with self._lock:
            return self._available_since[database]
