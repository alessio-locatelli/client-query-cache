from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore

if TYPE_CHECKING:
    from collections.abc import Callable

    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import CacheKey
    from client_query_cache._core.lru import WeightedLru


class _IntegerSubclass(int):
    __slots__ = ()


@pytest.fixture(
    params=[
        pytest.param(True, id="true"),
        pytest.param(False, id="false"),
        pytest.param(_IntegerSubclass(1), id="integer_subclass"),
        pytest.param(1.0, id="integral_float"),
        pytest.param(1.5, id="fractional_float"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive_infinity"),
        pytest.param(float("-inf"), id="negative_infinity"),
        pytest.param("1", id="string"),
        pytest.param(None, id="null"),
        pytest.param(object(), id="unrelated_object"),
    ]
)
def invalid_config_integer(request: pytest.FixtureRequest) -> object:
    return request.param


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
        put_result = original_conditional_put(self, key, entry)
        hook(key, entry)
        return put_result

    monkeypatch.setattr(lru_class, "conditional_put", patched_conditional_put)
