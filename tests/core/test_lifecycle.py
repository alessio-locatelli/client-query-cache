from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mongo_client_cache._core.errors import CacheClosedError
from mongo_client_cache._core.lifecycle import CacheLifecycleState
from mongo_client_cache._core.manager import CacheCore
from tests.core.conftest import patch_conditional_put_hook

if TYPE_CHECKING:
    from collections.abc import Callable

    from mongo_client_cache._core.entries import CacheEntry
    from mongo_client_cache._core.keys import CacheKey, NamespaceId

pytestmark = pytest.mark.unit


def test_a_new_manager_starts_active() -> None:
    assert CacheCore().lifecycle_state is CacheLifecycleState.ACTIVE


def test_close_transitions_to_closed_and_releases_storage(
    namespace: NamespaceId,
) -> None:
    core = CacheCore()
    capture = core.begin_identity_admission(namespace, "doc-1")
    core.admit_identity(capture, "full", {"v": 1})

    core.close()

    assert core.lifecycle_state is CacheLifecycleState.CLOSED
    used_bytes, entry_count = core._lru.snapshot_usage()
    assert used_bytes == 0
    assert entry_count == 0


def test_close_is_idempotent() -> None:
    core = CacheCore()
    core.close()
    core.close()
    assert core.lifecycle_state is CacheLifecycleState.CLOSED


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

    core.discard_identity_admission(capture)

    assert namespace not in core._namespaces


def test_an_admission_racing_close_does_not_survive_in_the_closed_snapshot(
    namespace: NamespaceId, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = CacheCore()
    capture = core.begin_identity_admission(namespace, "doc-1")

    # admit_identity() calls conditional_put() exactly once per attempt, and
    # this test only ever admits `capture`, so the hook itself never needs
    # to guard against being re-triggered.
    def hook(_key: CacheKey, _entry: CacheEntry) -> None:
        core.close()

    patch_conditional_put_hook(monkeypatch, core, hook)

    core.admit_identity(capture, "full", {"v": 1})

    snapshot = core.snapshot()
    assert snapshot.used_bytes == 0
    assert snapshot.entry_count == 0
