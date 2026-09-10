from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mongo_client_cache._core.errors import CacheClosedError
from mongo_client_cache._core.lifecycle import CacheLifecycleState
from mongo_client_cache._core.manager import CacheCore

if TYPE_CHECKING:
    from mongo_client_cache._core.keys import NamespaceId

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


def test_admission_after_close_raises_cache_closed_error(
    namespace: NamespaceId,
) -> None:
    core = CacheCore()
    core.close()
    with pytest.raises(CacheClosedError):
        core.begin_identity_admission(namespace, "doc-1")


def test_lookup_after_close_raises_cache_closed_error(namespace: NamespaceId) -> None:
    core = CacheCore()
    core.close()
    with pytest.raises(CacheClosedError):
        core.lookup_identity(namespace, "doc-1", "full")
