from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from bson.errors import BSONError

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import decode_value, encode_value
from client_query_cache._core.entries import (
    _DEFERRED_MISS,
    _MISS,
    AdmissionOutcome,
    LookupResult,
)
from client_query_cache._core.errors import (
    CacheClosedError,
    UnsupportedCacheRequestError,
)
from client_query_cache._core.find_reads import PreparedFindRead, find_discriminator
from client_query_cache._core.keys import canonical_alias_key
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._core.retention import key_decline
from client_query_cache._core.snapshots import (
    BypassReason,
    BypassReasonCount,
    CacheSnapshot,
    RetentionDeclineReason,
    retention_counts,
)
from client_query_cache._core.stream_cost import StreamCostRegistry
from client_query_cache._types import NonEmpty, NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from typing import Any

    from bson.codec_options import CodecOptions

_REASONS = tuple(BypassReason)

type NativeStatistics = tuple[
    bool,
    NonNegativeInt,
    NonNegativeInt,
    NonNegativeInt,
    NonNegativeInt,
    NonNegativeInt,
    NonNegativeInt,
    NonEmpty[list[NonNegativeInt]],
    NonNegativeInt,
    list[NonNegativeInt],
]


type NativeSetup = tuple[
    CacheCoreConfig,
    PositiveInt,
    PositiveInt,
    PositiveInt,
    StreamCostRegistry,
    PositiveInt | None,
]


def initialize(config: CacheCoreConfig | None) -> NativeSetup:
    resolved = CacheCoreConfig() if config is None else config
    # No Python bytes object or resident set can exceed the address space.
    # Keep the caller's unbounded integer configuration for inspection.
    return (
        resolved,
        min(resolved.budget_bytes, sys.maxsize),
        min(resolved.max_entry_bytes, sys.maxsize),
        min(resolved.max_namespaces, sys.maxsize),
        StreamCostRegistry(resolved.lag_capture_window_config),
        None
        if resolved.max_entries is None
        else min(resolved.max_entries, sys.maxsize),
    )


def decoded_value(
    encoded: bytes, codec_options: CodecOptions[Any] | None
) -> LookupResult:
    return LookupResult(hit=True, value=decode_value(encoded, codec_options))


def decoded_find(
    encoded: bytes,
    limit: int,
    codec_options: CodecOptions[Any] | None,
) -> LookupResult:
    documents: list[object] = decode_value(encoded, codec_options)  # type: ignore[assignment]
    if not isinstance(limit, bool) and limit > 0:
        documents = documents[:limit]
    return LookupResult(hit=True, value=documents)


def snapshot(statistics: NativeStatistics, config: CacheCoreConfig) -> CacheSnapshot:
    (
        closed,
        used,
        count,
        hits,
        misses,
        evictions,
        oversized,
        reasons,
        aliases,
        declines,
    ) = statistics
    return CacheSnapshot(
        lifecycle="closed" if closed else "active",
        used_bytes=used,
        budget_bytes=config.budget_bytes,
        max_entry_bytes=config.max_entry_bytes,
        entry_count=count,
        hits=hits,
        misses=misses,
        evictions=evictions,
        bypasses=sum(reasons),
        oversized_bypasses=oversized,
        bypass_reasons=tuple(map(BypassReasonCount, _REASONS, reasons, strict=True)),
        max_entries=config.max_entries,
        max_key_bytes=config.max_key_bytes,
        alias_count=aliases,
        retention_declines=retention_counts(declines),
    )


_KEY_DECLINE_INDEX = {
    RetentionDeclineReason.KEY_SIZE_LIMIT: 0,
    RetentionDeclineReason.KEY_SIZE_UNAVAILABLE: 1,
}


def native_key_decline(maximum: PositiveInt, *roots: object) -> NonNegativeInt | None:
    reason = key_decline(maximum, *roots)
    return None if reason is None else _KEY_DECLINE_INDEX[reason]


_OPERATIONS = (
    initialize,
    canonicalize,
    order_sensitive_key,
    encode_value,
    decoded_value,
    decoded_find,
    snapshot,
    canonical_alias_key,
    find_discriminator,
    PreparedFindRead,
    CacheClosedError,
    UnsupportedCacheRequestError,
    BSONError,
    _MISS,
    _DEFERRED_MISS,
    tuple(AdmissionOutcome),
    _REASONS,
    native_key_decline,
)
