from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mongo_client_cache._core.errors import CacheClosedError
from mongo_client_cache._core.lifecycle import CacheLifecycleState
from mongo_client_cache._core.manager import CacheCore

if TYPE_CHECKING:
    from mongo_client_cache._core.entries import CacheEntry
    from mongo_client_cache._core.keys import CacheKey, NamespaceId
    from mongo_client_cache._core.lru import WeightedLru

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


def test_an_admission_racing_close_does_not_survive_in_the_closed_snapshot(
    namespace: NamespaceId, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = CacheCore()
    capture = core.begin_identity_admission(namespace, "doc-1")

    lru_class = type(core._lru)
    original_conditional_put = lru_class.conditional_put
    triggered = False

    def racing_conditional_put(
        self: WeightedLru, key: CacheKey, entry: CacheEntry
    ) -> object:
        nonlocal triggered
        result = original_conditional_put(self, key, entry)
        if not triggered:
            triggered = True
            core.close()
        return result

    monkeypatch.setattr(lru_class, "conditional_put", racing_conditional_put)

    core.admit_identity(capture, "full", {"v": 1})

    snapshot = core.snapshot()
    assert snapshot.used_bytes == 0
    assert snapshot.entry_count == 0
