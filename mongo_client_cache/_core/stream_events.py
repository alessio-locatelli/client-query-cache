from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mongo_client_cache._core.keys import NamespaceId

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableSet

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


def route_change_event(
    cache: CacheCore,
    event: Mapping[str, Any],
    known_namespaces: MutableSet[NamespaceId],
) -> bool:
    operation_type = event["operationType"]
    if operation_type in WRITE_OPERATION_TYPES:
        namespace = _namespace_from_ns(event["ns"])
        known_namespaces.add(namespace)
        cache.record_write(namespace, event["documentKey"]["_id"])
        return False
    if operation_type == "create":
        namespace = _namespace_from_ns(event["ns"])
        known_namespaces.add(namespace)
        cache.create_namespace(namespace)
        return False
    if operation_type == "drop":
        namespace = _namespace_from_ns(event["ns"])
        cache.clear_namespace(namespace)
        known_namespaces.discard(namespace)
        return False
    if operation_type == "rename":
        source = _namespace_from_ns(event["ns"])
        destination = _namespace_from_ns(event["to"])
        cache.clear_namespace(source)
        cache.clear_namespace(destination)
        known_namespaces.discard(source)
        known_namespaces.add(destination)
        return False
    if operation_type == "dropDatabase":
        return False
    # operation_type == "invalidate": the $match stage above admits no other
    # kind, and dropDatabase is the only event that invalidates a
    # database-scoped stream, so every namespace this database ever routed an
    # event for must be cleared before the stream can safely reopen.
    for namespace in list(known_namespaces):
        cache.clear_namespace(namespace)
    known_namespaces.clear()
    return True


def is_unresumable_change_stream_error(error: OperationFailure) -> bool:
    return (
        error.has_error_label(NONRESUMABLE_CHANGE_STREAM_ERROR_LABEL)
        or error.code == CHANGE_STREAM_HISTORY_LOST_CODE
    )
