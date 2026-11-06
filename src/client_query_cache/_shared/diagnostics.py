from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import starmap
from typing import TYPE_CHECKING, Final, TypedDict, cast

from client_query_cache._types import (
    NonEmptyStr,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from client_query_cache._shared.attachment import Message


class SharedBypassReason(StrEnum):
    SESSION = "session"
    READ_PROFILE = "read_profile"
    UNSUPPORTED_OPTIONS = "unsupported_options"
    UNSAFE_FILTER = "unsafe_filter"
    UNSAFE_PROJECTION = "unsafe_projection"
    UNSAFE_PIPELINE = "unsafe_pipeline"
    UNCANONICALIZABLE_KEY = "uncanonicalizable_key"
    UNPORTABLE_KEY = "unportable_key"
    SHARED_SCOPE = "shared_scope"
    MISSING_COLLECTION = "missing_collection"
    VIEW_COLLECTION = "view_collection"
    TIME_SERIES_COLLECTION = "time_series_collection"
    METADATA_UNAVAILABLE = "metadata_unavailable"
    METADATA_REFRESH = "metadata_refresh"
    NAMESPACE_CAPACITY = "namespace_capacity"
    DATABASE_NOT_AUTHORIZED = "database_not_authorized"
    STREAM_STARTING = "stream_starting"
    STREAM_UNAVAILABLE = "stream_unavailable"
    PROGRESS_EXPIRED = "progress_expired"
    OWNER_UNAVAILABLE = "owner_unavailable"
    UNSPECIFIED = "unspecified"


class SharedStreamStatus(StrEnum):
    NOT_STARTED = "not_started"
    STARTING = "starting"
    STARTUP_FAILED = "startup_failed"
    UNAVAILABLE = "unavailable"
    PROGRESS_EXPIRED = "progress_expired"
    HEALTHY = "healthy"


@dataclass(frozen=True, slots=True)
class SharedBypassReasonCount:
    reason: SharedBypassReason
    count: NonNegativeInt


@dataclass(frozen=True, slots=True)
class SharedCacheStatistics:
    hits: NonNegativeInt
    misses: NonNegativeInt
    bypasses: NonNegativeInt
    oversized_bypasses: NonNegativeInt
    bypass_reasons: tuple[SharedBypassReasonCount, ...]


REASONS_BY_VALUE: Final = {reason.value: reason for reason in SharedBypassReason}


def reason_counts(
    recorded: Mapping[SharedBypassReason, NonNegativeInt],
) -> tuple[SharedBypassReasonCount, ...]:
    totals = dict.fromkeys(SharedBypassReason, 0)
    totals.update(recorded)
    return tuple(starmap(SharedBypassReasonCount, totals.items()))


@dataclass(frozen=True, slots=True)
class SharedCapacityUsage:
    in_use: NonNegativeInt
    limit: PositiveInt


@dataclass(frozen=True, slots=True)
class SharedDatabaseHealth:
    database_name: NonEmptyStr
    status: SharedStreamStatus


@dataclass(frozen=True, slots=True)
class SharedOwnerSnapshot:
    incarnation: int
    uptime_seconds: NonNegativeFloat
    cache_bytes: SharedCapacityUsage
    index_entries: SharedCapacityUsage
    namespaces: SharedCapacityUsage
    connections: SharedCapacityUsage
    evictions: NonNegativeInt
    rejected_connections: NonNegativeInt
    streams: tuple[SharedDatabaseHealth, ...]


class _Limits(TypedDict):
    index_entries: PositiveInt
    namespaces: PositiveInt
    connections: PositiveInt


class _Cache(TypedDict):
    used_bytes: NonNegativeInt
    budget_bytes: PositiveInt
    evictions: NonNegativeInt


class _Database(TypedDict):
    status: str


class _Counters(TypedDict):
    connections_rejected: NonNegativeInt


class _SharedIndex(TypedDict):
    published: NonNegativeInt


class _Observation(TypedDict):
    incarnation: int
    uptime_seconds: NonNegativeFloat
    limits: _Limits
    namespaces: NonNegativeInt
    connections: NonNegativeInt
    cache: _Cache
    counters: _Counters
    shared_index: _SharedIndex
    databases: dict[str, _Database]


def owner_snapshot_from_wire(reply: Message) -> SharedOwnerSnapshot:
    return _snapshot(cast("_Observation", reply))


def _snapshot(observation: _Observation) -> SharedOwnerSnapshot:
    limits = observation["limits"]
    cache = observation["cache"]
    return SharedOwnerSnapshot(
        incarnation=int(observation["incarnation"]),
        uptime_seconds=observation["uptime_seconds"],
        cache_bytes=SharedCapacityUsage(cache["used_bytes"], cache["budget_bytes"]),
        index_entries=SharedCapacityUsage(
            observation["shared_index"]["published"], limits["index_entries"]
        ),
        namespaces=SharedCapacityUsage(observation["namespaces"], limits["namespaces"]),
        connections=SharedCapacityUsage(
            observation["connections"], limits["connections"]
        ),
        evictions=cache["evictions"],
        rejected_connections=observation["counters"]["connections_rejected"],
        streams=tuple(
            SharedDatabaseHealth(name, SharedStreamStatus(database["status"]))
            for name, database in observation["databases"].items()
        ),
    )
