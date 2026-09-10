from __future__ import annotations

import pytest

from mongo_client_cache._core.keys import NamespaceId
from mongo_client_cache._core.manager import CacheCore


@pytest.fixture
def namespace() -> NamespaceId:
    return NamespaceId("test_db", "test_collection")


@pytest.fixture
def other_namespace() -> NamespaceId:
    return NamespaceId("test_db", "other_collection")


@pytest.fixture
def core() -> CacheCore:
    return CacheCore()
