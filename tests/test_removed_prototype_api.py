import importlib

import pytest

import client_query_cache

pytestmark = pytest.mark.unit

REMOVED_MODULES = (
    "client_query_cache.synchronous.mongo_client",
    "client_query_cache.synchronous.cursor",
    "client_query_cache.cache",
    "client_query_cache._types",
    "client_query_cache._misc",
    "client_query_cache.logger",
)

REMOVED_TOP_LEVEL_NAMES = (
    "CachedMongoClient",
    "ClientSideCacheConfig",
    "CollectionConfig",
)


@pytest.mark.parametrize("module_name", REMOVED_MODULES)
def test_prototype_module_no_longer_importable(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


@pytest.mark.parametrize("name", REMOVED_TOP_LEVEL_NAMES)
def test_prototype_top_level_export_removed(name: str) -> None:
    assert not hasattr(client_query_cache, name)
