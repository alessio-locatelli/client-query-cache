from __future__ import annotations

import pytest

from mongo_client_cache._core.entries import AdmissionOutcome
from mongo_client_cache._core.keys import NamespaceId, canonical_alias_key
from mongo_client_cache._core.manager import CacheCore, CacheCoreConfig

pytestmark = pytest.mark.unit


def test_write_to_one_document_does_not_invalidate_another_documents_entry(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture_a = core.begin_identity_admission(namespace, "doc-a")
    core.admit_identity(capture_a, "full", {"v": "a"})
    capture_b = core.begin_identity_admission(namespace, "doc-b")
    core.admit_identity(capture_b, "full", {"v": "b"})

    core.record_write(namespace, "doc-a")

    assert core.lookup_identity(namespace, "doc-a", "full").hit is False
    result_b = core.lookup_identity(namespace, "doc-b", "full")
    assert result_b.hit
    assert result_b.value == {"v": "b"}


def test_write_invalidates_namespace_guarded_entries_regardless_of_document(
    core: CacheCore, namespace: NamespaceId
) -> None:
    namespace_capture = core.capture_namespace_generation(namespace)
    core.admit_namespace(namespace_capture, ("find", "shape"), [1, 2, 3])

    core.record_write(namespace, "some-other-doc")

    assert core.lookup_namespace(namespace, ("find", "shape")).hit is False


def test_admission_captured_before_a_write_is_rejected_by_compare_and_decide(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    capture = core.begin_identity_admission(namespace, identity)
    core.record_write(namespace, identity)

    outcome = core.admit_identity(capture, "full", {"v": "stale"})

    assert outcome is AdmissionOutcome.DECLINED_STALE


def test_identity_state_is_bounded_by_cache_capacity_not_write_history(
    namespace: NamespaceId,
) -> None:
    core = CacheCore(CacheCoreConfig(shared_budget_bytes=500, max_entry_bytes=100))
    admission_count = 500

    for index in range(admission_count):
        capture = core.begin_identity_admission(namespace, f"doc-{index}")
        core.admit_identity(capture, "full", {"v": index})

    state = core._namespace(namespace)
    assert len(state.identities) < admission_count


def test_a_resolved_unique_key_read_shares_the_entry_with_an_id_read(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    capture = core.begin_identity_admission(namespace, identity)
    alias = canonical_alias_key("email", "a@example.com", None)
    core.admit_identity(capture, "full", {"doc": "data"}, alias=alias)

    resolved_identity = core.resolve_alias(namespace, "email", "a@example.com", None)
    assert resolved_identity is not None

    by_alias = core.lookup_identity(namespace, resolved_identity, "full")
    by_id = core.lookup_identity(namespace, identity, "full")
    assert by_alias.hit
    assert by_id.hit
    assert by_alias.value == by_id.value == {"doc": "data"}


def test_a_projected_read_does_not_collide_with_a_full_document_read(
    core: CacheCore, namespace: NamespaceId
) -> None:
    identity = "doc-1"
    capture_full = core.begin_identity_admission(namespace, identity)
    core.admit_identity(capture_full, None, {"a": 1, "b": 2})
    capture_projected = core.begin_identity_admission(namespace, identity)
    core.admit_identity(capture_projected, {"a": 1}, {"a": 1})

    full = core.lookup_identity(namespace, identity, None)
    projected = core.lookup_identity(namespace, identity, {"a": 1})

    assert full.value == {"a": 1, "b": 2}
    assert projected.value == {"a": 1}


def test_different_find_or_aggregate_shapes_do_not_collide(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture_1 = core.capture_namespace_generation(namespace)
    core.admit_namespace(capture_1, ("find", {"a": 1}), [{"doc": 1}])
    capture_2 = core.capture_namespace_generation(namespace)
    core.admit_namespace(capture_2, ("find", {"a": 2}), [{"doc": 2}])

    assert core.lookup_namespace(namespace, ("find", {"a": 1})).value == [{"doc": 1}]
    assert core.lookup_namespace(namespace, ("find", {"a": 2})).value == [{"doc": 2}]


def test_distinct_calls_on_different_fields_do_not_collide(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture_email = core.capture_namespace_generation(namespace)
    core.admit_namespace(capture_email, ("distinct", "email", {}), ["a@example.com"])
    capture_username = core.capture_namespace_generation(namespace)
    core.admit_namespace(capture_username, ("distinct", "username", {}), ["alice"])

    email_result = core.lookup_namespace(namespace, ("distinct", "email", {}))
    username_result = core.lookup_namespace(namespace, ("distinct", "username", {}))
    assert email_result.value == ["a@example.com"]
    assert username_result.value == ["alice"]


def test_namespace_creation_invalidates_and_reclaims_a_pre_creation_entry(
    core: CacheCore, namespace: NamespaceId
) -> None:
    capture = core.capture_namespace_generation(namespace)
    core.admit_namespace(capture, ("find", {}), [])

    core.create_namespace(namespace)

    assert core.lookup_namespace(namespace, ("find", {})).hit is False
    used_bytes, entry_count = core._lru.snapshot_usage()
    assert used_bytes == 0
    assert entry_count == 0


def test_the_same_identity_and_query_shape_do_not_collide_across_namespaces(
    core: CacheCore, namespace: NamespaceId, other_namespace: NamespaceId
) -> None:
    capture_a = core.begin_identity_admission(namespace, "shared-id")
    core.admit_identity(capture_a, "full", {"from": "ns-a"})
    capture_b = core.begin_identity_admission(other_namespace, "shared-id")
    core.admit_identity(capture_b, "full", {"from": "ns-b"})

    assert core.lookup_identity(namespace, "shared-id", "full").value == {
        "from": "ns-a"
    }
    assert core.lookup_identity(other_namespace, "shared-id", "full").value == {
        "from": "ns-b"
    }

    namespace_capture_a = core.capture_namespace_generation(namespace)
    core.admit_namespace(namespace_capture_a, ("q",), ["a"])
    namespace_capture_b = core.capture_namespace_generation(other_namespace)
    core.admit_namespace(namespace_capture_b, ("q",), ["b"])

    assert core.lookup_namespace(namespace, ("q",)).value == ["a"]
    assert core.lookup_namespace(other_namespace, ("q",)).value == ["b"]
