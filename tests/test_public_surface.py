import subprocess
import sys

import pytest

import client_query_cache
import client_query_cache.asynchronous
import client_query_cache.synchronous
from client_query_cache import CachedCollection, CachedDatabase, CacheManager
from client_query_cache.asynchronous import (
    CachedCollection as AsyncCachedCollection,
)
from client_query_cache.asynchronous import (
    CachedDatabase as AsyncCachedDatabase,
)
from client_query_cache.asynchronous import (
    CacheManager as AsyncCacheManager,
)

pytestmark = pytest.mark.unit

MANAGER_MEMBERS = {
    "client",
    "cache_core",
    "enable_telemetry",
    "get_cached_collection",
    "snapshot",
    "stream_health_snapshot",
    "stream_cost_snapshot",
    "active_stream_cost_databases",
    "close",
}
DATABASE_MEMBERS = {"manager", "name", "raw"}
COLLECTION_MEMBERS = {
    "database",
    "name",
    "raw",
    "find_one",
    "find",
    "aggregate",
    "count_documents",
    "estimated_document_count",
    "distinct",
}


def public_members(cls: type) -> set[str]:
    return {name for name in dir(cls) if not name.startswith("_")}


@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        pytest.param(CacheManager, MANAGER_MEMBERS, id="sync-manager"),
        pytest.param(AsyncCacheManager, MANAGER_MEMBERS, id="async-manager"),
        pytest.param(CachedDatabase, DATABASE_MEMBERS, id="sync-database"),
        pytest.param(AsyncCachedDatabase, DATABASE_MEMBERS, id="async-database"),
        pytest.param(CachedCollection, COLLECTION_MEMBERS, id="sync-collection"),
        pytest.param(AsyncCachedCollection, COLLECTION_MEMBERS, id="async-collection"),
    ],
)
def test_public_members_match_the_documented_surface(
    cls: type, expected: set[str]
) -> None:
    assert public_members(cls) == expected


@pytest.mark.parametrize(
    "manager_cls",
    [
        pytest.param(CacheManager, id="sync"),
        pytest.param(AsyncCacheManager, id="async"),
    ],
)
def test_manager_no_longer_offers_the_former_cached_accessor(
    manager_cls: type,
) -> None:
    assert not hasattr(manager_cls, "cached")


@pytest.mark.parametrize(
    "name",
    [
        "SharedBypassReason",
        "SharedBypassReasonCount",
        "SharedCacheStatistics",
        "SharedCapacityUsage",
        "SharedDatabaseHealth",
        "SharedOwnerSnapshot",
        "SharedStreamStatus",
    ],
)
def test_shared_diagnostic_types_are_exported_by_every_public_package(
    name: str,
) -> None:
    exported = getattr(client_query_cache, name)
    assert getattr(client_query_cache.synchronous, name) is exported
    assert getattr(client_query_cache.asynchronous, name) is exported
    assert name in client_query_cache.__all__


def test_cache_configuration_is_one_class_across_public_packages() -> None:
    exported = client_query_cache.CacheCoreConfig
    assert client_query_cache.synchronous.CacheCoreConfig is exported
    assert client_query_cache.asynchronous.CacheCoreConfig is exported
    assert "CacheCoreConfig" in client_query_cache.__all__


def test_owner_import_skips_worker_adapters() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys

import client_query_cache

assert client_query_cache.SharedCacheServer is not None
assert "SharedCacheManager" in dir(client_query_cache)
assert "SharedCachedCollection" in dir(client_query_cache)
assert "client_query_cache._shared.adapters" not in sys.modules
assert "client_query_cache.asynchronous" not in sys.modules
from client_query_cache import SharedCachedCollection, SharedCacheManager
from client_query_cache.synchronous import shared

assert SharedCachedCollection is shared.SharedCachedCollection
assert SharedCacheManager is shared.SharedCacheManager
""",
        ],
        check=True,
    )


def test_missing_root_export_raises_attribute_error() -> None:
    assert not hasattr(client_query_cache, "NonexistentExport")


def test_root_exports_are_discoverable() -> None:
    assert set(client_query_cache.__all__) <= set(dir(client_query_cache))
