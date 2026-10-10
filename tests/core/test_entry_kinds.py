from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from bson.decimal128 import Decimal128

from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.keys import NamespaceId, canonical_alias_key
from client_query_cache._core.manager import CacheCore, CacheCoreConfig

if TYPE_CHECKING:
    from collections.abc import Callable

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


@pytest.mark.parametrize(
    ("cached_id", "written_id", "invalidated"),
    [
        pytest.param(1, Decimal128("1"), True, id="equal-value"),
        pytest.param(19.99, Decimal128("19.99"), False, id="inexact-double"),
    ],
)
def test_a_write_under_another_numeric_type_invalidates_only_an_equal_identity(
    core: CacheCore,
    namespace: NamespaceId,
    *,
    cached_id: float,
    written_id: Decimal128,
    invalidated: bool,
) -> None:
    capture = core.begin_identity_admission(namespace, cached_id)
    outcome = core.admit_identity(capture, "full", {"_id": cached_id})
    assert outcome is AdmissionOutcome.ADMITTED

    core.record_write(namespace, written_id)

    assert core.lookup_identity(namespace, cached_id, "full").hit is not invalidated


def test_write_invalidates_namespace_guarded_entries_regardless_of_document(
    core: CacheCore, namespace: NamespaceId
) -> None:
    namespace_capture = core.capture_namespace_generation(namespace)
    core.admit_namespace(namespace_capture, ("find", "shape"), [1, 2, 3])

    core.record_write(namespace, "some-other-doc")

    assert core.lookup_namespace(namespace, ("find", "shape")).hit is False


@pytest.mark.parametrize(
    ("begin", "admit"),
    [
        pytest.param(
            lambda core, namespace: core.begin_identity_admission(namespace, "doc-1"),
            lambda core, capture: core.admit_identity(capture, "full", {"v": "x"}),
            id="identity_guarded",
        ),
        pytest.param(
            lambda core, namespace: core.capture_namespace_generation(namespace),
            lambda core, capture: core.admit_namespace(capture, ("find", "shape"), [1]),
            id="namespace_guarded",
        ),
    ],
)
def test_admission_captured_before_a_write_is_rejected_by_compare_and_decide(
    core: CacheCore,
    namespace: NamespaceId,
    begin: Callable[[CacheCore, NamespaceId], object],
    admit: Callable[[CacheCore, object], AdmissionOutcome],
) -> None:
    capture = begin(core, namespace)  # pytriage: TR5

    core.record_write(namespace, "doc-1")

    assert admit(core, capture) is AdmissionOutcome.DECLINED_STALE


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


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(
            (("find", {"a": 1}), [{"doc": 1}]),
            (("find", {"a": 2}), [{"doc": 2}]),
            id="different_find_filters",
        ),
        pytest.param(
            (("distinct", "email", {}), ["a@example.com"]),
            (("distinct", "username", {}), ["alice"]),
            id="different_distinct_fields",
        ),
    ],
)
def test_different_namespace_guarded_discriminators_do_not_collide(
    core: CacheCore,
    namespace: NamespaceId,
    first: tuple[object, object],
    second: tuple[object, object],
) -> None:
    discriminator_1, value_1 = first
    discriminator_2, value_2 = second

    capture_1 = core.capture_namespace_generation(namespace)
    core.admit_namespace(capture_1, discriminator_1, value_1)
    capture_2 = core.capture_namespace_generation(namespace)
    core.admit_namespace(capture_2, discriminator_2, value_2)

    assert core.lookup_namespace(namespace, discriminator_1).value == value_1
    assert core.lookup_namespace(namespace, discriminator_2).value == value_2


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
