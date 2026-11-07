from collections.abc import Callable, Hashable, Mapping
from typing import final

from client_query_cache._core.canonical import Canonical
from client_query_cache._core.contracts import LocalCacheCore as _LocalCacheCore
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_reads import FindSource
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._types import (
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

@final
class Payload:
    @property
    def token(self) -> int: ...

@final
class OwnerIndex:
    def __init__(
        self,
        slots: int,
        arena_bytes: int,
        databases: int,
        namespaces: int,
        incarnation: int,
        expiry_ns: int,
    ) -> None: ...
    def reader_descriptor(self) -> int: ...
    def store(self, payload: bytes) -> Payload | None: ...
    def release(self, payload: Payload) -> None: ...
    def snapshot(self, payload: Payload) -> bytes | None: ...
    def publish(
        self,
        database: int,
        namespace: int,
        epoch: int,
        identity: bytes,
        shape: bytes,
        payload: Payload,
    ) -> int | None: ...
    def unpublish(self, payload: Payload) -> bool: ...
    def published(self) -> int: ...
    def set_available(self, database: int, available: bool) -> None: ...
    def set_progress(self, database: int, monotonic_ns: int) -> None: ...
    def set_epoch(self, namespace: int, epoch: int) -> None: ...
    def record_write(self, namespace: NonNegativeInt) -> None: ...
    def enable_capture(self, enabled: bool) -> None: ...
    def validate_capture(
        self,
        database: NonNegativeInt,
        namespace: NonNegativeInt,
        epoch: NonNegativeInt,
        incarnation: NonNegativeInt,
        token: tuple[NonNegativeInt, NonNegativeInt, NonNegativeInt],
        max_age_ns: PositiveInt,
    ) -> bool: ...
    def session_ring(
        self,
        tokens: PositiveInt,
        admission_bytes: NonNegativeInt = 0,
        enable_telemetry: bool = False,
    ) -> SessionRing: ...
    def serve(self, path: str) -> EchoOwner: ...

@final
class SessionRing:
    def descriptor(self) -> int: ...
    def close_descriptor(self) -> None: ...
    def drain(self) -> list[int]: ...
    def dropped(self) -> int: ...
    def drain_admissions(
        self, max_frames: NonNegativeInt | None = None
    ) -> list[bytes]: ...

@final
class ReaderIndex:
    def __init__(
        self,
        index_descriptor: int,
        ring_descriptor: int,
        enable_telemetry: bool = False,
    ) -> None: ...
    @property
    def incarnation(self) -> int: ...
    @property
    def detached(self) -> bool: ...
    @property
    def admissions_enabled(self) -> bool: ...
    def lookup(
        self, database: int, namespace: int, epoch: int, identity: bytes, shape: bytes
    ) -> bytes | None: ...
    def detach(self) -> None: ...
    def capture(
        self, database: NonNegativeInt, namespace: NonNegativeInt, epoch: NonNegativeInt
    ) -> tuple[NonNegativeInt, NonNegativeInt, NonNegativeInt] | None: ...
    def dropped(self) -> int: ...
    def enqueue_admission(self, frame: bytes) -> bool: ...

@final
class EchoOwner:
    def close(self) -> None: ...

@final
class ByteRelay:
    def __init__(self) -> None: ...
    def run(self, client: NonNegativeInt, upstream: NonNegativeInt) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...
    @property
    def bytes_sent(self) -> NonNegativeInt: ...
    @property
    def bytes_received(self) -> NonNegativeInt: ...

@final
class EncodedArray:
    def __init__(self, limit: NonNegativeInt) -> None: ...
    @property
    def retained_bytes(self) -> NonNegativeInt: ...
    def append(self, envelope: bytes) -> bool: ...
    def finish(self) -> bytes: ...
    def clear(self) -> None: ...

@final
class Canonicalizer:
    def __init__(
        self,
        canonical_tag: type,
        pending_tag: type,
        mapping: object,
        sequence: object,
        boolean: object,
        mapping_abc: type,
        sequence_abc: type,
        unsupported: type[Exception],
        reference: Callable[[object], Hashable],
    ) -> None: ...
    def canonical(self, value: object) -> Hashable: ...

@final
class OrderedKeys:
    def __init__(
        self,
        canonicalizer: Canonicalizer,
        pending_tags: tuple[object, object, object, object],
        int64_type: type,
        decimal_type: type,
        reference: Callable[[object], object],
        discriminator_reference: Callable[[object], object],
    ) -> None: ...
    def key(self, value: object) -> Hashable: ...
    def discriminator(self, value: object) -> Hashable: ...
    def pending_key(self, value: object) -> object: ...
    def pending_discriminator(self, value: object) -> object: ...

@final
class UnsafeScan:
    def __init__(
        self,
        key_set: frozenset[str],
        variables: frozenset[str],
        prefixes: tuple[str, ...],
        mapping_abc: type,
        sequence_abc: type,
        reference: Callable[[object, frozenset[str]], bool],
    ) -> None: ...
    def __call__(self, node: object) -> bool: ...

@final
class FindKeyEncoder:
    def encode(
        self, family: object, limit: object, scalar_encoder: Callable[[object], bytes]
    ) -> tuple[bytes, bytes]: ...
    def wrap(
        self, family: bytes, limit: object, scalar_encoder: Callable[[object], bytes]
    ) -> bytes: ...

def find_key_encoder(tags: Mapping[NonNegativeInt, str]) -> FindKeyEncoder: ...

@final
class LocalCapture:
    @property
    def namespace(self) -> NamespaceId: ...
    @property
    def identity(self) -> Canonical: ...
    @property
    def generation_key(self) -> tuple[NonNegativeInt, NonNegativeInt]: ...
    @property
    def generation(self) -> NonNegativeInt: ...
    @property
    def availability_generation(self) -> NonNegativeInt: ...
    @property
    def released(self) -> bool: ...
    def release(self) -> None: ...

class LocalCacheCore(_LocalCacheCore):
    def _ownership(
        self,
    ) -> tuple[
        NonNegativeInt, NonNegativeInt, NonNegativeInt, NonNegativeInt, NonNegativeInt
    ]: ...
    def _recency(self) -> list[object]: ...
    def begin_identity_admission(
        self, namespace: NamespaceId, identity: object
    ) -> LocalCapture: ...
    def capture_namespace_generation(self, namespace: NamespaceId) -> LocalCapture: ...

@final
class SharedOwnerCore(LocalCacheCore):
    def __init__(
        self,
        config: CacheCoreConfig,
        index: OwnerIndex | None,
        databases: list[str],
        namespaces: PositiveInt,
        probe_ttl_seconds: PositiveFloat,
    ) -> None: ...
    def begin_namespace_metadata_probe(
        self, namespace: NamespaceId
    ) -> NonNegativeInt | None: ...
    def cancel_namespace_metadata_probe(
        self, namespace: NamespaceId, token: NonNegativeInt
    ) -> None: ...
    def registered_namespace_metadata(
        self, namespace: NamespaceId
    ) -> tuple[NonNegativeInt, NonNegativeInt] | None: ...
    def namespace_metadata_after_probe(
        self, namespace: NamespaceId, token: NonNegativeInt
    ) -> (
        tuple[
            NonNegativeInt,
            NonNegativeInt,
            tuple[NonNegativeInt, NonNegativeInt] | None,
        ]
        | None
    ): ...
    def assigned_slot(
        self, namespace: NamespaceId
    ) -> tuple[NonNegativeInt, NonNegativeInt] | None: ...
    def admit_identity_published(
        self,
        capture: LocalCapture,
        read_shape: object,
        encoded: bytes,
        identity_key: bytes,
        shape_key: bytes,
    ) -> AdmissionOutcome: ...
    def admit_namespace_published(
        self,
        capture: LocalCapture,
        discriminator: object,
        encoded: bytes,
        shape_key: bytes,
        *,
        find_source: FindSource | None = None,
    ) -> AdmissionOutcome: ...
    def admit_local(
        self,
        namespace: NamespaceId,
        slot: tuple[NonNegativeInt, NonNegativeInt],
        epoch: NonNegativeInt,
        incarnation: NonNegativeInt,
        token: tuple[NonNegativeInt, NonNegativeInt, NonNegativeInt],
        identity: object,
        shape: object,
        encoded: bytes,
        identity_key: bytes,
        shape_key: bytes,
        max_age_ns: PositiveInt,
    ) -> AdmissionOutcome | None: ...
    def touch(self, ring: SessionRing) -> None: ...
    def _probes(self) -> list[tuple[str, str, NonNegativeInt, PositiveInt]]: ...
    def published(self) -> NonNegativeInt: ...
    def available_since(self, database: str) -> NonNegativeFloat | None: ...
