from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mongo_client_cache._core.keys import NamespaceId

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pymongo.errors import OperationFailure

    from mongo_client_cache._core.manager import CacheCore

NONRESUMABLE_CHANGE_STREAM_ERROR_LABEL = "NonResumableChangeStreamError"
CHANGE_STREAM_HISTORY_LOST_CODE = 286

WRITE_OPERATION_TYPES = frozenset({"insert", "update", "replace", "delete"})

RELEVANT_OPERATION_TYPES = WRITE_OPERATION_TYPES | frozenset(
    {"drop", "dropDatabase", "rename", "create", "invalidate"}
)

CHANGE_STREAM_PROJECTION: Mapping[str, int] = {
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


def _route_write(cache: CacheCore, event: Mapping[str, Any]) -> None:
    namespace = _namespace_from_ns(event["ns"])
    if cache.has_namespace(namespace):
        cache.record_write(namespace, event["documentKey"]["_id"])


def _route_create(cache: CacheCore, event: Mapping[str, Any]) -> None:
    namespace = _namespace_from_ns(event["ns"])
    if cache.has_namespace(namespace):
        cache.create_namespace(namespace)


def _route_drop(cache: CacheCore, event: Mapping[str, Any]) -> None:
    namespace = _namespace_from_ns(event["ns"])
    if cache.has_namespace(namespace):
        cache.clear_namespace(namespace)


def _route_rename(cache: CacheCore, event: Mapping[str, Any]) -> None:
    source = _namespace_from_ns(event["ns"])
    destination = _namespace_from_ns(event["to"])
    if cache.has_namespace(source):
        cache.clear_namespace(source)
    if cache.has_namespace(destination):
        cache.clear_namespace(destination)


def _route_invalidate(cache: CacheCore, database: str) -> None:
    # dropDatabase is the only event that invalidates a database-scoped
    # stream, so every namespace cache-core currently tracks for this
    # database must be cleared before the stream can safely reopen — not
    # just namespaces this stream happened to route an event for, since a
    # namespace-guarded entry (e.g. a negative lookup) can be admitted for
    # a namespace that never produced a write.
    for namespace in cache.namespaces_for_database(database):
        cache.clear_namespace(namespace)


def route_change_event(
    cache: CacheCore, database: str, event: Mapping[str, Any]
) -> bool:
    operation_type = event["operationType"]
    if operation_type in WRITE_OPERATION_TYPES:
        _route_write(cache, event)
        return False
    if operation_type == "create":
        _route_create(cache, event)
        return False
    if operation_type == "drop":
        _route_drop(cache, event)
        return False
    if operation_type == "rename":
        _route_rename(cache, event)
        return False
    if operation_type == "dropDatabase":
        return False
    # operation_type == "invalidate": the $match stage above admits no other kind.
    _route_invalidate(cache, database)
    return True


def is_unresumable_change_stream_error(error: OperationFailure) -> bool:
    return (
        error.has_error_label(NONRESUMABLE_CHANGE_STREAM_ERROR_LABEL)
        or error.code == CHANGE_STREAM_HISTORY_LOST_CODE
    )
