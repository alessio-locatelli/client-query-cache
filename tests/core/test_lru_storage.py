from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from client_query_cache import CacheCoreConfig
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.manager import CacheCore

if TYPE_CHECKING:
    from collections.abc import Callable

    from client_query_cache._core.keys import NamespaceId

pytestmark = pytest.mark.unit


def test_eviction_keeps_used_bytes_within_the_shared_budget(
    namespace: NamespaceId,
) -> None:
    budget_bytes = 2_000
    core = CacheCore(CacheCoreConfig(budget_bytes=budget_bytes, max_entry_bytes=200))
    for index in range(100):
        capture = core.begin_identity_admission(namespace, f"doc-{index}")
        outcome = core.admit_identity(capture, "full", {"v": "x" * 100})
        assert outcome is AdmissionOutcome.ADMITTED

    used_bytes, _entry_count = core._lru.snapshot_usage()
    assert used_bytes <= budget_bytes


def test_eviction_updates_the_owning_namespaces_index_after_the_lru_lock_releases(
    namespace: NamespaceId,
) -> None:
    core = CacheCore(CacheCoreConfig(budget_bytes=300, max_entry_bytes=200))
    evicted_identity = "doc-0"
    capture = core.begin_identity_admission(namespace, evicted_identity)
    core.admit_identity(capture, "full", {"v": "x" * 100})

    for index in range(1, 20):
        capture = core.begin_identity_admission(namespace, f"doc-{index}")
        core.admit_identity(capture, "full", {"v": "x" * 100})

    state = core._namespace(namespace)
    live_identities = {
        entry.identity for entry in state.entry_index if entry.identity is not None
    }
    assert evicted_identity not in live_identities
    assert evicted_identity not in state.identities


def test_the_shared_budget_is_shared_across_namespaces(
    namespace: NamespaceId, other_namespace: NamespaceId
) -> None:
    core = CacheCore(CacheCoreConfig(budget_bytes=300, max_entry_bytes=200))
    capture_a = core.begin_identity_admission(namespace, "doc-a")
    core.admit_identity(capture_a, "full", {"v": "x" * 100})

    capture_b = core.begin_identity_admission(other_namespace, "doc-b")
    core.admit_identity(capture_b, "full", {"v": "x" * 100})

    for index in range(20):
        capture = core.begin_identity_admission(other_namespace, f"doc-flood-{index}")
        core.admit_identity(capture, "full", {"v": "x" * 100})

    lookup_result = core.lookup_identity(namespace, "doc-a", "full")
    assert lookup_result.hit is False


@pytest.mark.parametrize(
    "admit_oversize",
    [
        pytest.param(
            lambda core, namespace: core.admit_identity(
                core.begin_identity_admission(namespace, "doc-1"),
                "full",
                {"payload": "x" * 200},
            ),
            id="identity_guarded",
        ),
        pytest.param(
            lambda core, namespace: core.admit_namespace(
                core.capture_namespace_generation(namespace),
                ("find", {}),
                ["x" * 200],
            ),
            id="namespace_guarded",
        ),
    ],
)
def test_oversize_value_is_declined_without_touching_the_budget(
    namespace: NamespaceId,
    admit_oversize: Callable[[CacheCore, NamespaceId], AdmissionOutcome],
) -> None:
    core = CacheCore(CacheCoreConfig(budget_bytes=1_000, max_entry_bytes=32))

    outcome = admit_oversize(core, namespace)

    assert outcome is AdmissionOutcome.DECLINED_OVERSIZE
    used_bytes, entry_count = core._lru.snapshot_usage()
    assert used_bytes == 0
    assert entry_count == 0
