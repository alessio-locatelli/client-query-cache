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
        "_identities",
        "_index",
        "_lock",
        "_namespaces",
        "_published",
        "_shapes",
        "_tokens",
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
        self._published: dict[Payload, tuple[int, NamespaceId, Canonical]] = {}
        self._identities: dict[tuple[NamespaceId, Canonical], set[Payload]] = {}
        self._tokens: dict[int, CacheKey] = {}
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
                if len(self._namespaces) >= self._capacity:
                    return None
                slot = NamespaceSlot(database, len(self._namespaces))
                self._namespaces[namespace] = slot
            self._raise_epoch(namespace, epoch)
            self._index.set_epoch(slot.namespace, self._epochs[namespace])
        return slot

    def assigned(self, namespace: NamespaceId) -> NamespaceSlot | None:
        with self._lock:
            try:
                return self._namespaces[namespace]
            except KeyError:
                return None

    def _raise_epoch(self, namespace: NamespaceId, epoch: NonNegativeInt) -> None:
        try:
            current = self._epochs[namespace]
        except KeyError:
            current = epoch
        self._epochs[namespace] = max(current, epoch)

    def progress(self, database: str) -> None:
        self._index.set_progress(self._databases[database], time.monotonic_ns())

    def key(self, token: int) -> CacheKey | None:
        with self._lock:
            try:
                return self._tokens[token]
            except KeyError:
                return None

    def admitted(self, key: CacheKey, entry: CacheEntry) -> None:
        payload = entry.value
        if not isinstance(key, IdentityCacheKey) or not isinstance(payload, Payload):
            return
        with self._lock:
            try:
                namespace = self._namespaces[key.namespace]
            except KeyError:
                return
            token = self._index.publish(
                namespace.database,
                namespace.namespace,
                entry.generation_key[0],
                encode_key(key.identity),
                self._shapes.encode(key.read_shape),
                payload,
            )
            if token is None:
                return
            self._published[payload] = (token, key.namespace, key.identity)
            self._identities.setdefault((key.namespace, key.identity), set()).add(
                payload
            )
            self._tokens[token] = key

    def _forget(self, payload: Payload) -> tuple[NamespaceId, Canonical] | None:
        try:
            token, namespace, identity = self._published.pop(payload)
        except KeyError:
            return None
        self._index.unpublish(payload)
        del self._tokens[token]
        return namespace, identity

    def removed(self, _key: CacheKey, entry: CacheEntry) -> None:
        payload = entry.value
        if not isinstance(payload, Payload):
            return
        with self._lock:
            identity = self._forget(payload)
            if identity is None:
                return
            members = self._identities[identity]
            members.discard(payload)
            if not members:
                del self._identities[identity]

    def identity_written(self, namespace: NamespaceId, identity: Canonical) -> None:
        with self._lock:
            try:
                slot = self._namespaces[namespace]
            except KeyError:
                return
            self._index.record_write(slot.namespace)
            try:
                payloads = self._identities.pop((namespace, identity))
            except KeyError:
                return
            for payload in payloads:
                self._forget(payload)

    def epoch_changed(self, namespace: NamespaceId, epoch: NonNegativeInt) -> None:
        with self._lock:
            self._raise_epoch(namespace, epoch)
            try:
                slot = self._namespaces[namespace]
            except KeyError:
                return
            self._index.set_epoch(slot.namespace, self._epochs[namespace])

    def availability_changed(self, database: str, *, available: bool) -> None:
        with self._lock:
            self._available_since[database] = time.monotonic() if available else None
            self._index.set_available(self._databases[database], available=available)

    def available_since(self, database: str) -> NonNegativeFloat | None:
        with self._lock:
            return self._available_since[database]
