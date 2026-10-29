from typing import Any, Protocol

from bson.codec_options import CodecOptions

from client_query_cache._core.canonical import Canonical
from client_query_cache._core.entries import AdmissionOutcome, LookupResult
from client_query_cache._core.find_reads import (
    FindReadShape,
    FindSource,
    PreparedFindRead,
)
from client_query_cache._core.keys import AliasKey, NamespaceId
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._core.snapshots import BypassReason, CacheSnapshot
from client_query_cache._core.stream_cost import StreamCostSnapshot
from client_query_cache._types import (
    NonEmptyStr,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
)

class IdentityCaptureView(Protocol):
    @property
    def namespace(self) -> NamespaceId: ...
    @property
    def identity(self) -> Canonical: ...
    @property
    def generation_key(self) -> tuple[NonNegativeInt, NonNegativeInt]: ...
    @property
    def availability_generation(self) -> NonNegativeInt: ...
    @property
    def released(self) -> bool: ...
    def release(self) -> None: ...

class NamespaceCaptureView(Protocol):
    @property
    def namespace(self) -> NamespaceId: ...
    @property
    def generation_key(self) -> tuple[NonNegativeInt, NonNegativeInt]: ...
    @property
    def availability_generation(self) -> NonNegativeInt: ...
    @property
    def generation(self) -> NonNegativeInt: ...

class CoreLifecycle(Protocol):
    @property
    def max_entries(self) -> PositiveInt | None: ...
    @property
    def max_entry_bytes(self) -> PositiveInt: ...
    @property
    def max_namespaces(self) -> PositiveInt: ...
    def close(self) -> None: ...
    def snapshot(self) -> CacheSnapshot: ...
    def record_miss(self) -> None: ...
    def record_bypass(self, reason: BypassReason = ...) -> None: ...
    def record_oversized_bypass(self) -> None: ...

class CoreCoherence(Protocol):
    def namespaces_for_database(self, database: NonEmptyStr) -> list[NamespaceId]: ...
    def has_namespace(self, namespace: NamespaceId) -> bool: ...
    def can_register_namespace(self, namespace: NamespaceId) -> bool: ...
    def try_current_epoch(self, namespace: NamespaceId) -> NonNegativeInt | None: ...
    def current_epoch(self, namespace: NamespaceId) -> NonNegativeInt: ...
    def current_index_generation(self, namespace: NamespaceId) -> NonNegativeInt: ...
    def record_index_change(self, namespace: NamespaceId) -> None: ...
    def record_write(self, namespace: NamespaceId, identity: object) -> None: ...
    def clear_namespace(self, namespace: NamespaceId) -> None: ...
    def drop_namespace(self, namespace: NamespaceId) -> None: ...
    def release_namespace_if_epoch_matches(
        self, namespace: NamespaceId, epoch: NonNegativeInt
    ) -> bool: ...
    def create_namespace(self, namespace: NamespaceId) -> None: ...
    def invalidate_namespace_metadata_probe(self, namespace: NamespaceId) -> None: ...
    def invalidate_namespace_metadata_probes_for_database(
        self, database: NonEmptyStr
    ) -> None: ...
    def is_database_available(self, database: NonEmptyStr) -> bool: ...
    def set_database_available(
        self, database: NonEmptyStr, *, available: bool
    ) -> None: ...

class CoreAdmission(Protocol):
    def begin_identity_admission(
        self, namespace: NamespaceId, identity: object
    ) -> IdentityCaptureView: ...
    def admit_identity(
        self,
        capture: IdentityCaptureView,
        read_shape: object,
        value: object,
        *,
        alias: AliasKey | None = None,
        codec_options: CodecOptions[Any] | None = None,
    ) -> AdmissionOutcome: ...
    def admit_identity_encoded(
        self,
        capture: IdentityCaptureView,
        read_shape: object,
        encoded: bytes,
        *,
        alias: AliasKey | None = None,
    ) -> AdmissionOutcome: ...
    def capture_namespace_generation(
        self, namespace: NamespaceId
    ) -> NamespaceCaptureView: ...
    def admit_namespace(
        self,
        capture: NamespaceCaptureView,
        discriminator: object,
        value: object,
        *,
        codec_options: CodecOptions[Any] | None = None,
        find_source: FindSource | None = None,
    ) -> AdmissionOutcome: ...
    def admit_namespace_encoded(
        self,
        capture: NamespaceCaptureView,
        discriminator: object,
        encoded: bytes,
        *,
        find_source: FindSource | None = None,
    ) -> AdmissionOutcome: ...
    def discard_stale_alias(
        self,
        capture: NamespaceCaptureView,
        alias: AliasKey,
        expected_identity: Canonical,
    ) -> None: ...
    def discard_namespace_entry(
        self, capture: NamespaceCaptureView, discriminator: object
    ) -> None: ...
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
    ) -> AdmissionOutcome: ...

class CoreReads(Protocol):
    def lookup_identity(
        self,
        namespace: NamespaceId,
        identity: object,
        read_shape: object,
        *,
        codec_options: CodecOptions[Any] | None = None,
        defer_miss: bool = False,
    ) -> LookupResult: ...
    def lookup_identity_encoded(
        self, namespace: NamespaceId, identity: object, read_shape: object
    ) -> bytes | None: ...
    def lookup_namespace(
        self,
        namespace: NamespaceId,
        discriminator: object,
        *,
        codec_options: CodecOptions[Any] | None = None,
        defer_miss: bool = False,
    ) -> LookupResult: ...
    def lookup_namespace_encoded(
        self,
        namespace: NamespaceId,
        discriminator: object,
        *,
        defer_miss: bool = False,
    ) -> bytes | LookupResult: ...
    def lookup_find(
        self,
        namespace: NamespaceId,
        shape: FindReadShape | PreparedFindRead,
        *,
        codec_options: CodecOptions[Any] | None = None,
    ) -> LookupResult: ...
    def lookup_find_encoded(
        self, namespace: NamespaceId, shape: FindReadShape | PreparedFindRead
    ) -> bytes | None: ...
    def resolve_alias(
        self,
        namespace: NamespaceId,
        definition: object,
        value: object,
        collation: object,
    ) -> Canonical | None: ...

class CoreStreamCost(Protocol):
    def record_stream_poll(self, database: NonEmptyStr) -> None: ...
    def record_logical_event_bytes(
        self, database: NonEmptyStr, count: NonNegativeInt
    ) -> None: ...
    def record_invalidation_applied(
        self,
        database: NonEmptyStr,
        raw_lag_seconds: float,
        wall_seconds: NonNegativeFloat,
        monotonic_seconds: NonNegativeFloat,
    ) -> None: ...
    def reset_stream_cost_statistics(
        self, database: NonEmptyStr | None = None
    ) -> None: ...
    def stream_cost_snapshot(self, database: NonEmptyStr) -> StreamCostSnapshot: ...
    def active_stream_cost_databases(self) -> list[NonEmptyStr]: ...

class LocalCacheCore(
    CoreLifecycle, CoreCoherence, CoreAdmission, CoreReads, CoreStreamCost, Protocol
):
    def __init__(self, config: CacheCoreConfig | None = None) -> None: ...
