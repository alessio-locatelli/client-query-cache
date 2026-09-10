from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock, call

import pytest
from pymongo.errors import OperationFailure

from mongo_client_cache._core.keys import NamespaceId
from mongo_client_cache._core.manager import CacheCore
from mongo_client_cache._core.stream_events import (
    CHANGE_STREAM_PROJECTION,
    RELEVANT_OPERATION_TYPES,
    build_change_stream_pipeline,
    is_unresumable_change_stream_error,
    route_change_event,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit


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
    }

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    cache.record_write.assert_called_once_with(namespace, "doc-1")


def test_write_event_for_an_untracked_namespace_does_not_touch_the_cache() -> None:
    cache = Mock()
    cache.has_namespace.return_value = False
    event = {
        "operationType": "insert",
        "ns": {"db": "db", "coll": "coll"},
        "documentKey": {"_id": "doc-1"},
    }

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    cache.record_write.assert_not_called()


def test_create_event_creates_the_namespace() -> None:
    cache = Mock()
    cache.has_namespace.return_value = True
    namespace = NamespaceId("db", "coll")
    event = {"operationType": "create", "ns": {"db": "db", "coll": "coll"}}

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    cache.create_namespace.assert_called_once_with(namespace)


def test_drop_event_clears_the_namespace() -> None:
    cache = Mock()
    cache.has_namespace.return_value = True
    namespace = NamespaceId("db", "coll")
    event = {"operationType": "drop", "ns": {"db": "db", "coll": "coll"}}

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    cache.clear_namespace.assert_called_once_with(namespace)


def test_rename_event_clears_both_the_source_and_destination_namespaces() -> None:
    cache = Mock()
    cache.has_namespace.return_value = True
    source = NamespaceId("db", "old_coll")
    destination = NamespaceId("db", "new_coll")
    event = {
        "operationType": "rename",
        "ns": {"db": "db", "coll": "old_coll"},
        "to": {"db": "db", "coll": "new_coll"},
    }

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    cache.clear_namespace.assert_has_calls([call(source), call(destination)])


def test_drop_database_event_is_a_no_op_pending_its_invalidation() -> None:
    cache = Mock()
    event = {"operationType": "dropDatabase", "ns": {"db": "db"}}

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is False
    cache.clear_namespace.assert_not_called()


def test_invalidate_clears_every_namespace_cache_core_tracks_for_the_database() -> None:
    cache = Mock()
    first = NamespaceId("db", "first")
    second = NamespaceId("db", "second")
    cache.namespaces_for_database.return_value = [first, second]
    event = {"operationType": "invalidate"}

    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is True
    cache.namespaces_for_database.assert_called_once_with("db")
    cache.clear_namespace.assert_has_calls([call(first), call(second)], any_order=True)


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
    }
    route_change_event(cache, "db", event)

    assert cache.lookup_identity(namespace, "doc-1", "full").hit is False
    assert cache.lookup_namespace(namespace, "query-shape").hit is False


def test_drop_event_invalidates_identity_guarded_entries_via_epoch() -> None:
    cache = CacheCore()
    namespace = NamespaceId("db", "coll")
    identity_capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(identity_capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    event = {"operationType": "drop", "ns": {"db": "db", "coll": "coll"}}
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

    event = {"operationType": "create", "ns": {"db": "db", "coll": "coll"}}
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

    event = {"operationType": "invalidate"}
    must_reopen = route_change_event(cache, "db", event)

    assert must_reopen is True
    assert cache.lookup_namespace(namespace, "missing-doc").hit is False
    assert cache.lookup_namespace(other_database_namespace, "missing-doc").hit is True
