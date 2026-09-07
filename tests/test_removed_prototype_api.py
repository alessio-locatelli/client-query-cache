import importlib

import pytest

import mongo_client_cache

pytestmark = pytest.mark.unit

REMOVED_MODULES = (
    "mongo_client_cache.synchronous.mongo_client",
    "mongo_client_cache.synchronous.cursor",
    "mongo_client_cache.cache",
    "mongo_client_cache._types",
    "mongo_client_cache._misc",
    "mongo_client_cache.logger",
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
    assert not hasattr(mongo_client_cache, name)
