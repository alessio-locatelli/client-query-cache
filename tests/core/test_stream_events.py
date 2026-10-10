from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from unittest.mock import ANY, Mock, call

import pytest
from pymongo.errors import OperationFailure

from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore
from client_query_cache._core.stream_events import (
    CHANGE_STREAM_PROJECTION,
    INDEX_OPERATION_TYPES,
    RELEVANT_OPERATION_TYPES,
    WRITE_OPERATION_TYPES,
    build_change_stream_pipeline,
    is_unresumable_change_stream_error,
    route_change_event,
)
from client_query_cache._types import BsonDict

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit

_WALL_TIME = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)


def test_pipeline_matches_only_relevant_operation_types() -> None:
    pipeline = build_change_stream_pipeline()

    matched_types = set(pipeline[0]["$match"]["operationType"]["$in"])
    assert matched_types == RELEVANT_OPERATION_TYPES


def test_pipeline_projects_every_routing_and_resume_field() -> None:
    pipeline = build_change_stream_pipeline()

    assert pipeline[1]["$project"] == dict(CHANGE_STREAM_PROJECTION)
    assert set(CHANGE_STREAM_PROJECTION) == {
        "_id",
        "operationType",
        "ns",
        "documentKey",
        "to",
        "clusterTime",
        "wallTime",
    }


def _projected_event_for(operation_type: str) -> BsonDict:
    event: BsonDict = {"operationType": operation_type, "wallTime": _WALL_TIME}
    if operation_type in WRITE_OPERATION_TYPES:
        event["ns"] = {"db": "db", "coll": "coll"}
        event["documentKey"] = {"_id": "doc-1"}
    elif operation_type in INDEX_OPERATION_TYPES or operation_type in {
        "create",
        "drop",
    }:
        event["ns"] = {"db": "db", "coll": "coll"}
    elif operation_type == "rename":
        event["ns"] = {"db": "db", "coll": "old_coll"}
        event["to"] = {"db": "db", "coll": "new_coll"}
    return event


@pytest.mark.parametrize("operation_type", sorted(RELEVANT_OPERATION_TYPES))
def test_every_relevant_operation_type_is_routed_without_a_full_document(
    operation_type: str,
) -> None:
    cache = Mock()
    cache.has_namespace.return_value = True
    cache.namespaces_for_database.return_value = [NamespaceId("db", "coll")]
    event = _projected_event_for(operation_type)
    assert "fullDocument" not in event
    assert "fullDocumentBeforeChange" not in event

    route_change_event(cache, "db", event)


def test_update_event_without_full_document_routes_invalidation_and_lag() -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    identity_capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(identity_capture, "full", {"v": 1})
    event = {
        "_id": {"tok": "resume-1"},
        "operationType": "update",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
        "wallTime": _WALL_TIME,
    }
    assert "fullDocument" not in event
    assert "fullDocumentBeforeChange" not in event

    route_change_event(cache, "db", event)

    assert cache.lookup_identity(namespace, "doc-1", "full").hit is False
    assert cache.stream_cost_snapshot("db").invalidations == 1


@pytest.mark.parametrize("operation_type", ["insert", "update", "replace", "delete"])
def test_write_events_record_a_write_against_the_document_identity(
    operation_type: str,
) -> None:
    cache = Mock()
    cache.has_namespace.return_value = True
    namespace = NamespaceId("db", "coll")
    event: Mapping[str, object] = {
        "operationType": operation_type,
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
        "wallTime": _WALL_TIME,
    }

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    cache.record_write.assert_called_once_with(namespace, "doc-1")


@pytest.mark.parametrize("operation_type", ["createIndexes", "dropIndexes"])
def test_index_events_record_an_index_change_against_the_namespace(
    operation_type: str,
) -> None:
    cache = Mock()
    cache.has_namespace.return_value = True
    namespace = NamespaceId("db", "coll")
    event: Mapping[str, object] = {
        "operationType": operation_type,
        "ns": {"db": "db", "coll": "coll"},
        "wallTime": _WALL_TIME,
    }

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    cache.record_index_change.assert_called_once_with(namespace)
    cache.record_write.assert_not_called()
    cache.clear_namespace.assert_not_called()


@pytest.mark.parametrize(
    ("event", "unused_method"),
    [
        pytest.param(
            {
                "operationType": "insert",
                "ns": {"db": "db", "coll": "coll"},
                "documentKey": {"_id": "doc-1"},
                "wallTime": _WALL_TIME,
            },
            "record_write",
            id="write",
        ),
        pytest.param(
            {
                "operationType": "create",
                "ns": {"db": "db", "coll": "coll"},
                "wallTime": _WALL_TIME,
            },
            "create_namespace",
            id="create",
        ),
        pytest.param(
            {
                "operationType": "drop",
                "ns": {"db": "db", "coll": "coll"},
                "wallTime": _WALL_TIME,
            },
            "clear_namespace",
            id="drop",
        ),
        pytest.param(
            {
                "operationType": "createIndexes",
                "ns": {"db": "db", "coll": "coll"},
                "wallTime": _WALL_TIME,
            },
            "record_index_change",
            id="createIndexes",
        ),
        pytest.param(
            {
                "operationType": "dropIndexes",
                "ns": {"db": "db", "coll": "coll"},
                "wallTime": _WALL_TIME,
            },
            "record_index_change",
            id="dropIndexes",
        ),
    ],
)
def test_event_for_an_untracked_namespace_does_not_touch_the_cache(
    event: Mapping[str, object], unused_method: str
) -> None:
    cache = Mock()
    cache.has_namespace.return_value = False

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    getattr(cache, unused_method).assert_not_called()


def test_rename_event_skips_an_untracked_source_and_destination() -> None:
    cache = Mock()
    cache.has_namespace.return_value = False
    event = {
        "operationType": "rename",
        "ns": {"db": "db", "coll": "old_coll"},
        "to": {"db": "db", "coll": "new_coll"},
        "wallTime": _WALL_TIME,
    }

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    cache.clear_namespace.assert_not_called()


@pytest.mark.parametrize(
    ("operation_type", "method_name"),
    [
        pytest.param("create", "create_namespace", id="create"),
        pytest.param("drop", "clear_namespace", id="drop"),
    ],
)
def test_event_for_a_tracked_namespace_updates_the_cache(
    operation_type: str, method_name: str
) -> None:
    cache = Mock()
    cache.has_namespace.return_value = True
    namespace = NamespaceId("db", "coll")
    event = {
        "operationType": operation_type,
        "ns": {"db": "db", "coll": "coll"},
        "wallTime": _WALL_TIME,
    }

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    getattr(cache, method_name).assert_called_once_with(namespace)


def test_rename_event_clears_both_the_source_and_destination_namespaces() -> None:
    cache = Mock()
    cache.has_namespace.return_value = True
    source = NamespaceId("db", "old_coll")
    destination = NamespaceId("db", "new_coll")
    event = {
        "operationType": "rename",
        "ns": {"db": "db", "coll": "old_coll"},
        "to": {"db": "db", "coll": "new_coll"},
        "wallTime": _WALL_TIME,
    }

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    cache.clear_namespace.assert_has_calls([call(source), call(destination)])


def test_rename_event_does_not_clear_a_destination_in_another_database() -> None:
    cache = Mock()
    cache.has_namespace.return_value = True
    source = NamespaceId("db", "old_coll")
    event = {
        "operationType": "rename",
        "ns": {"db": "db", "coll": "old_coll"},
        "to": {"db": "other_db", "coll": "new_coll"},
        "wallTime": _WALL_TIME,
    }

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    cache.clear_namespace.assert_called_once_with(source)


def test_drop_database_clears_every_cache_namespace_immediately() -> None:
    cache = Mock()
    first = NamespaceId("db", "first")
    second = NamespaceId("db", "second")
    cache.namespaces_for_database.return_value = [first, second]
    event = {
        "operationType": "dropDatabase",
        "ns": {"db": "db"},
        "wallTime": _WALL_TIME,
    }

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is True
    assert cache.mock_calls == [
        call.set_database_available("db", available=False),
        call.namespaces_for_database("db"),
        call.clear_namespace(first),
        call.clear_namespace(second),
        call.record_invalidation_applied("db", ANY, ANY, ANY),
    ]


def test_invalidate_with_no_cached_namespaces_records_no_lag_sample() -> None:
    cache = Mock()
    cache.namespaces_for_database.return_value = []
    event = {"operationType": "invalidate", "wallTime": _WALL_TIME}

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is True
    cache.record_invalidation_applied.assert_not_called()


def test_invalidate_clears_every_namespace_cache_core_tracks_for_the_database() -> None:
    cache = Mock()
    first = NamespaceId("db", "first")
    second = NamespaceId("db", "second")
    cache.namespaces_for_database.return_value = [first, second]
    event = {"operationType": "invalidate", "wallTime": _WALL_TIME}

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is True
    assert cache.mock_calls == [
        call.set_database_available("db", available=False),
        call.namespaces_for_database("db"),
        call.clear_namespace(first),
        call.clear_namespace(second),
        call.record_invalidation_applied("db", ANY, ANY, ANY),
    ]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            OperationFailure(
                "history lost",
                details={"errorLabels": ["NonResumableChangeStreamError"]},
            ),
            True,
            id="detected_by_label",
        ),
        pytest.param(
            OperationFailure("history lost", code=286), True, id="detected_by_code"
        ),
        pytest.param(OperationFailure("transient", code=1), False, id="resumable"),
    ],
)
def test_is_unresumable_change_stream_error(
    error: OperationFailure, expected: bool
) -> None:
    assert is_unresumable_change_stream_error(error) is expected


def test_write_event_invalidates_document_and_namespace_guarded_entries() -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    identity_capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(identity_capture, "full", {"v": 1})
    namespace_capture = cache.capture_namespace_generation(namespace)
    cache.admit_namespace(namespace_capture, "query-shape", [{"v": 1}])
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True
    assert cache.lookup_namespace(namespace, "query-shape").hit is True

    event = {
        "operationType": "update",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
        "wallTime": _WALL_TIME,
    }
    route_change_event(cache, "db", event)

    assert cache.lookup_identity(namespace, "doc-1", "full").hit is False
    assert cache.lookup_namespace(namespace, "query-shape").hit is False


@pytest.mark.parametrize("operation_type", ["createIndexes", "dropIndexes"])
def test_index_event_advances_index_generation_without_touching_document_cache(
    operation_type: str,
) -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    identity_capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(identity_capture, "full", {"v": 1})
    namespace_capture = cache.capture_namespace_generation(namespace)
    cache.admit_namespace(namespace_capture, "query-shape", [{"v": 1}])
    generation_before = cache.current_index_generation(namespace)

    event = {
        "operationType": operation_type,
        "ns": {"db": "db", "coll": "coll"},
        "wallTime": _WALL_TIME,
    }
    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    assert cache.current_index_generation(namespace) == generation_before + 1
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True
    assert cache.lookup_namespace(namespace, "query-shape").hit is True


def test_index_event_for_an_untracked_namespace_does_not_grow_cache_core_state() -> (
    None
):
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    event = {
        "operationType": "createIndexes",
        "ns": {"db": "db", "coll": "coll"},
        "wallTime": _WALL_TIME,
    }

    route_change_event(cache, "db", event)

    assert cache.has_namespace(namespace) is False


def test_drop_event_invalidates_identity_guarded_entries_via_epoch() -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    identity_capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(identity_capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    event = {
        "operationType": "drop",
        "ns": {"db": "db", "coll": "coll"},
        "wallTime": _WALL_TIME,
    }
    route_change_event(cache, "db", event)

    assert cache.lookup_identity(namespace, "doc-1", "full").hit is False


def test_create_event_reclaims_entries_cached_before_the_namespace_existed() -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    namespace_capture = cache.capture_namespace_generation(namespace)
    cache.admit_namespace(namespace_capture, "missing-doc", None)
    assert cache.lookup_namespace(namespace, "missing-doc").hit is True
    _used_before, count_before = cache._lru.snapshot_usage()
    assert count_before == 1

    event = {
        "operationType": "create",
        "ns": {"db": "db", "coll": "coll"},
        "wallTime": _WALL_TIME,
    }
    route_change_event(cache, "db", event)

    assert cache.lookup_namespace(namespace, "missing-doc").hit is False
    used_after, count_after = cache._lru.snapshot_usage()
    assert count_after == 0
    assert used_after == 0


def test_write_to_an_uncached_namespace_does_not_grow_cache_core_state() -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    event = {
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
        "wallTime": _WALL_TIME,
    }

    route_change_event(cache, "db", event)

    assert cache.has_namespace(namespace) is False


def test_invalidate_clears_a_namespace_that_never_produced_an_event() -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "never_written")
    other_database_namespace = NamespaceId("other_db", "coll")
    namespace_capture = cache.capture_namespace_generation(namespace)
    cache.admit_namespace(namespace_capture, "missing-doc", None)
    other_capture = cache.capture_namespace_generation(other_database_namespace)
    cache.admit_namespace(other_capture, "missing-doc", None)
    assert cache.lookup_namespace(namespace, "missing-doc").hit is True

    event = {"operationType": "invalidate", "wallTime": _WALL_TIME}
    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is True
    assert cache.lookup_namespace(namespace, "missing-doc").hit is False
    assert cache.lookup_namespace(other_database_namespace, "missing-doc").hit is True


def test_rename_to_another_database_does_not_clear_that_databases_cache() -> None:
    cache = CacheCore()
    source = NamespaceId("db", "old_coll")
    destination = NamespaceId("other_db", "new_coll")
    source_capture = cache.capture_namespace_generation(source)
    cache.admit_namespace(source_capture, "query", [1])
    destination_capture = cache.capture_namespace_generation(destination)
    cache.admit_namespace(destination_capture, "query", [1])
    assert cache.lookup_namespace(destination, "query").hit is True

    event = {
        "operationType": "rename",
        "ns": {"db": "db", "coll": "old_coll"},
        "to": {"db": "other_db", "coll": "new_coll"},
        "wallTime": _WALL_TIME,
    }
    route_change_event(cache, "db", event)

    assert cache.lookup_namespace(source, "query").hit is False
    assert cache.lookup_namespace(destination, "query").hit is True
