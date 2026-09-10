from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mongo_client_cache._core.keys import NamespaceId
from mongo_client_cache._core.manager import CacheCore

if TYPE_CHECKING:
    from collections.abc import Callable

    from mongo_client_cache._core.entries import CacheEntry
    from mongo_client_cache._core.keys import CacheKey
    from mongo_client_cache._core.lru import WeightedLru


@pytest.fixture
def namespace() -> NamespaceId:
    return NamespaceId("test_db", "test_collection")


@pytest.fixture
def other_namespace() -> NamespaceId:
    return NamespaceId("test_db", "other_collection")


@pytest.fixture
def core() -> CacheCore:
    return CacheCore()


def patch_conditional_put_hook(
    monkeypatch: pytest.MonkeyPatch,
    core: CacheCore,
    hook: Callable[[CacheKey, CacheEntry], None],
    *,
    trigger_before_insert: bool = False,
) -> None:
    lru_class = type(core._lru)
    original_conditional_put = lru_class.conditional_put

    def patched_conditional_put(
        self: WeightedLru, key: CacheKey, entry: CacheEntry
    ) -> object:
        if trigger_before_insert:
            hook(key, entry)
            return original_conditional_put(self, key, entry)
        result = original_conditional_put(self, key, entry)
        hook(key, entry)
        return result

    monkeypatch.setattr(lru_class, "conditional_put", patched_conditional_put)
