from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from client_query_cache import CacheClosedError, CacheCore, CacheCoreConfig
from client_query_cache._core.keys import NamespaceId

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.unit


def test_a_new_manager_starts_active() -> None:
    assert (
        CacheCore(CacheCoreConfig(enable_telemetry=True)).snapshot().lifecycle
        == "active"
    )


def test_close_transitions_to_closed_and_releases_storage(
    namespace: NamespaceId,
) -> None:
    core = CacheCore(CacheCoreConfig(enable_telemetry=True))
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.admit_identity(capture, "full", {"v": 1})

    core.close()

    assert core.snapshot().lifecycle == "closed"
    snapshot = core.snapshot()
    assert snapshot.used_bytes == 0
    assert snapshot.entry_count == 0


def test_close_is_idempotent() -> None:
    core = CacheCore(CacheCoreConfig(enable_telemetry=True))
    core.close()
    core.close()
    assert core.snapshot().lifecycle == "closed"


@pytest.mark.parametrize(
    "invoke",
    [
        pytest.param(
            lambda core, namespace: core.begin_identity_admission(namespace, "doc-1"),
            id="begin_identity_admission",
        ),
        pytest.param(
            lambda core, namespace: core.lookup_identity(namespace, "doc-1", "full"),
            id="lookup_identity",
        ),
    ],
)
def test_operation_after_close_raises_cache_closed_error(
    namespace: NamespaceId,
    invoke: Callable[[CacheCore, NamespaceId], object],
) -> None:
    core = CacheCore()
    core.close()
    with pytest.raises(CacheClosedError):
        invoke(core, namespace)


def test_admit_identity_after_close_raises_cache_closed_error(
    namespace: NamespaceId,
) -> None:
    core = CacheCore()
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.close()

    with pytest.raises(CacheClosedError):
        core.admit_identity(capture, "full", {"v": 1})


def test_releasing_a_capture_after_close_does_not_recreate_namespace_state(
    namespace: NamespaceId,
) -> None:
    core = CacheCore()
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.close()

    capture.release()

    assert not core.has_namespace(namespace)


def test_database_namespace_lookup_lists_only_that_database(
    namespace: NamespaceId,
) -> None:
    core = CacheCore()
    other_namespace = NamespaceId("other_database", namespace.collection)
    core.capture_namespace_generation(namespace)
    core.capture_namespace_generation(other_namespace)

    assert core.namespaces_for_database(namespace.database) == [namespace]


def test_close_releases_database_namespace_index(namespace: NamespaceId) -> None:
    core = CacheCore()
    core.capture_namespace_generation(namespace)

    core.close()

    assert core.namespaces_for_database(namespace.database) == []
