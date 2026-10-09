from __future__ import annotations

import datetime
import time
from typing import TYPE_CHECKING, Any

from bson.datetime_ms import DatetimeMS

from client_query_cache._core.keys import NamespaceId
from client_query_cache._types import NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pymongo.errors import OperationFailure

    from client_query_cache._core.manager import CacheCore

NONRESUMABLE_CHANGE_STREAM_ERROR_LABEL = "NonResumableChangeStreamError"
CHANGE_STREAM_HISTORY_LOST_CODE = 286

WRITE_OPERATION_TYPES = frozenset({"insert", "update", "replace", "delete"})

INDEX_OPERATION_TYPES = frozenset({"createIndexes", "dropIndexes"})

RELEVANT_OPERATION_TYPES = (
    WRITE_OPERATION_TYPES
    | INDEX_OPERATION_TYPES
    | frozenset({"drop", "dropDatabase", "rename", "create", "invalidate"})
)

CHANGE_STREAM_PROJECTION: Mapping[str, NonNegativeInt] = {
    "_id": 1,
    "operationType": 1,
    "ns": 1,
    "documentKey": 1,
    "to": 1,
    "clusterTime": 1,
    "wallTime": 1,
}


def build_change_stream_pipeline() -> list[Mapping[str, Any]]:
    return [
        {"$match": {"operationType": {"$in": sorted(RELEVANT_OPERATION_TYPES)}}},
        {"$project": dict(CHANGE_STREAM_PROJECTION)},
    ]


def _namespace_from_ns(ns: Mapping[str, Any]) -> NamespaceId:
    return NamespaceId(ns["db"], ns["coll"])


def _wall_time_seconds(value: datetime.datetime | DatetimeMS) -> float:
    if isinstance(value, DatetimeMS):
        return int(value) / 1000.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.UTC)
    return value.timestamp()


def _record_invalidation(
    cache: CacheCore, database: str, event: Mapping[str, Any]
) -> None:
    wall_seconds = time.time()
    monotonic_seconds = time.monotonic()
    raw_lag_seconds = wall_seconds - _wall_time_seconds(event["wallTime"])
    cache.record_invalidation_applied(
        database, raw_lag_seconds, wall_seconds, monotonic_seconds
    )


def _route_write(cache: CacheCore, database: str, event: Mapping[str, Any]) -> None:
    namespace = _namespace_from_ns(event["ns"])
    if cache.has_namespace(namespace):
        cache.record_write(namespace, event["documentKey"]["_id"])
        _record_invalidation(cache, database, event)


def _route_create(cache: CacheCore, database: str, event: Mapping[str, Any]) -> None:
    namespace = _namespace_from_ns(event["ns"])
    if cache.has_namespace(namespace):
        cache.create_namespace(namespace)
        _record_invalidation(cache, database, event)


def _route_drop(cache: CacheCore, database: str, event: Mapping[str, Any]) -> None:
    namespace = _namespace_from_ns(event["ns"])
    if cache.has_namespace(namespace):
        cache.clear_namespace(namespace)
        _record_invalidation(cache, database, event)


def _route_index_change(
    cache: CacheCore, database: str, event: Mapping[str, Any]
) -> None:
    namespace = _namespace_from_ns(event["ns"])
    if cache.has_namespace(namespace):
        cache.record_index_change(namespace)
        _record_invalidation(cache, database, event)


def _route_rename(cache: CacheCore, database: str, event: Mapping[str, Any]) -> None:
    source = _namespace_from_ns(event["ns"])
    destination = _namespace_from_ns(event["to"])
    invalidated = False
    if cache.has_namespace(source):
        cache.clear_namespace(source)
        invalidated = True
    if destination.database == database and cache.has_namespace(destination):
        cache.clear_namespace(destination)
        invalidated = True
    if invalidated:
        _record_invalidation(cache, database, event)


def _route_invalidate(
    cache: CacheCore, database: str, event: Mapping[str, Any]
) -> None:
    cache.set_database_available(database, available=False)
    namespaces = cache.namespaces_for_database(database)
    for namespace in namespaces:
        cache.clear_namespace(namespace)
    if namespaces:
        _record_invalidation(cache, database, event)


def route_change_event(
    cache: CacheCore, database: str, event: Mapping[str, Any]
) -> bool:
    operation_type = event["operationType"]
    if operation_type in WRITE_OPERATION_TYPES:
        _route_write(cache, database, event)
        return False
    if operation_type in INDEX_OPERATION_TYPES:
        _route_index_change(cache, database, event)
        return False
    if operation_type == "create":
        _route_create(cache, database, event)
        return False
    if operation_type == "drop":
        _route_drop(cache, database, event)
        return False
    if operation_type == "rename":
        _route_rename(cache, database, event)
        return False
    if operation_type == "dropDatabase":
        _route_invalidate(cache, database, event)
        return True
    _route_invalidate(cache, database, event)
    return True


def is_unresumable_change_stream_error(error: OperationFailure) -> bool:
    return (
        error.has_error_label(NONRESUMABLE_CHANGE_STREAM_ERROR_LABEL)
        or error.code == CHANGE_STREAM_HISTORY_LOST_CODE
    )
