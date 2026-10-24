from operator import itemgetter
from typing import TYPE_CHECKING

import pytest
from bson.codec_options import CodecOptions
from pymongo import MongoClient, ReadPreference
from pymongo.synchronous.database import Database

from client_query_cache._core.collection_metadata import CollectionProbeResult
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.lifecycle import CacheLifecycleState
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._core.snapshots import BypassReason
from client_query_cache._types import BsonDict
from client_query_cache.synchronous import (
    CacheManager,
    CacheSnapshot,
    StreamCostSnapshot,
    StreamHealthSnapshot,
    StreamHealthStatus,
)
from client_query_cache.synchronous.collection import CachedCollection
from client_query_cache.synchronous.database import CachedDatabase

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from pymongo.synchronous.collection import Collection

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> Iterator[MongoClient[BsonDict]]:
    with MongoClient[BsonDict]("mongodb://localhost:27017", connect=False) as instance:
        yield instance


def test_manager_does_not_subclass_or_replace_the_caller_client(
    client: MongoClient[BsonDict],
) -> None:
    assert not issubclass(CacheManager, MongoClient)
    assert CacheManager(client).client is client


def test_manager_builds_a_database_facade_around_the_caller_client(
    client: MongoClient[BsonDict],
) -> None:
    database = CacheManager(client)["example"]

    assert isinstance(database, CachedDatabase)
    assert not issubclass(CachedDatabase, Database)
    assert isinstance(database.raw, Database)
    assert database.name == "example"
    assert database.raw.client is client


def test_manager_used_as_a_context_manager_closes_its_own_cache(
    client: MongoClient[BsonDict],
) -> None:
    with CacheManager(client) as manager:
        core = manager.cache_core

    assert core.snapshot().lifecycle == CacheLifecycleState.CLOSED.value


def test_manager_close_does_not_close_the_caller_owned_client(
    client: MongoClient[BsonDict],
) -> None:
    CacheManager(client).close()

    assert client._closed is False


def test_unique_keys_for_rejects_a_probe_racing_a_concurrent_index_change(
    client: MongoClient[BsonDict],
) -> None:
    manager = CacheManager(client)
    namespace = NamespaceId("example", "widgets")

    def racing_list_indexes() -> list[BsonDict]:
        manager.cache_core.record_index_change(namespace)
        return [{"key": {"email": 1}, "name": "email_1", "unique": True}]

    assert manager._unique_keys_for(namespace, racing_list_indexes) == ()


def test_namespace_capacity_bypasses_collection_metadata_probe(
    client: MongoClient[BsonDict], monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = CacheManager(client, cache_config=CacheCoreConfig(max_namespaces=1))
    tracked = NamespaceId("example", "tracked")
    overflow = NamespaceId("example", "overflow")
    manager.cache_core.try_current_epoch(tracked)
    monkeypatch.setattr(
        type(manager._coordinator),
        "activate_database",
        lambda _self, _database: object(),
    )

    reason = manager._cache_ineligibility_reason(
        overflow, lambda: pytest.fail("capacity overflow must not probe metadata")
    )

    assert reason is BypassReason.NAMESPACE_CAPACITY
    assert manager._unique_keys_for(overflow) is None
    assert not manager.cache_core.has_namespace(overflow)
    manager.close()


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param(BypassReason.VIEW_COLLECTION, id="view"),
        pytest.param(BypassReason.TIME_SERIES_COLLECTION, id="time-series"),
    ],
)
def test_ineligibility_probe_cannot_cache_metadata_for_a_recreated_namespace(
    client: MongoClient[BsonDict],
    monkeypatch: pytest.MonkeyPatch,
    reason: BypassReason,
) -> None:
    with CacheManager(client) as manager:
        namespace = NamespaceId("example", "widgets")
        monkeypatch.setattr(
            type(manager._coordinator),
            "activate_database",
            lambda _self, _database: object(),
        )

        def recreate_during_probe() -> CollectionProbeResult:
            manager.cache_core.drop_namespace(namespace)
            assert manager.cache_core.try_current_epoch(namespace) is not None
            return CollectionProbeResult(reason, None)

        assert (
            manager._cache_ineligibility_reason(namespace, recreate_during_probe)
            is reason
        )
        assert manager.cache_core.has_namespace(namespace)
        assert manager._metadata.get(namespace) is None
        assert (
            manager._cache_ineligibility_reason(
                namespace, lambda: CollectionProbeResult(None, None)
            )
            is None
        )


@pytest.mark.parametrize(
    ("probe_result", "expected_reason"),
    [
        pytest.param(
            CollectionProbeResult(BypassReason.MISSING_COLLECTION, None),
            BypassReason.MISSING_COLLECTION,
            id="missing",
        ),
        pytest.param(
            CollectionProbeResult(BypassReason.VIEW_COLLECTION, None),
            BypassReason.VIEW_COLLECTION,
            id="view",
        ),
        pytest.param(
            CollectionProbeResult(BypassReason.TIME_SERIES_COLLECTION, None),
            BypassReason.TIME_SERIES_COLLECTION,
            id="time-series",
        ),
        pytest.param(
            CollectionProbeResult(BypassReason.METADATA_UNAVAILABLE, None),
            BypassReason.METADATA_UNAVAILABLE,
            id="unsupported-type",
        ),
        pytest.param(None, BypassReason.METADATA_UNAVAILABLE, id="probe-failed"),
    ],
)
def test_ineligible_collection_does_not_consume_namespace_capacity(
    client: MongoClient[BsonDict],
    monkeypatch: pytest.MonkeyPatch,
    probe_result: CollectionProbeResult | None,
    expected_reason: BypassReason,
) -> None:
    manager = CacheManager(client, cache_config=CacheCoreConfig(max_namespaces=1))
    monkeypatch.setattr(
        type(manager._coordinator),
        "activate_database",
        lambda _self, _database: object(),
    )
    unavailable = NamespaceId("example", "unavailable")
    available = NamespaceId("example", "available")

    reason = manager._cache_ineligibility_reason(unavailable, lambda: probe_result)
    if probe_result is not None and expected_reason in {
        BypassReason.METADATA_UNAVAILABLE,
        BypassReason.VIEW_COLLECTION,
        BypassReason.TIME_SERIES_COLLECTION,
    }:
        repeated_reason = manager._cache_ineligibility_reason(
            unavailable,
            lambda: pytest.fail("ineligible collection metadata should be cached"),
        )
        assert repeated_reason is expected_reason
    available_reason = manager._cache_ineligibility_reason(
        available, lambda: CollectionProbeResult(None, None)
    )

    assert reason is expected_reason
    assert not manager.cache_core.has_namespace(unavailable)
    assert available_reason is None
    assert manager.cache_core.has_namespace(available)
    manager.close()


@pytest.mark.parametrize(
    "get_raw_collection",
    [
        pytest.param(itemgetter("items"), id="plain"),
        pytest.param(
            lambda database: database["items"].with_options(
                read_preference=ReadPreference.SECONDARY
            ),
            id="with_options",
        ),
        pytest.param(
            lambda database: database.get_collection(
                "items", codec_options=CodecOptions(tz_aware=True)
            ),
            id="get_collection",
        ),
    ],
)
def test_cached_view_retains_the_exact_supplied_collection(
    client: MongoClient[BsonDict],
    get_raw_collection: Callable[[Database[BsonDict]], Collection[BsonDict]],
) -> None:
    manager = CacheManager(client)
    raw_collection = get_raw_collection(client["example"])

    collection = manager.get_cached_collection(raw_collection)

    assert isinstance(collection, CachedCollection)
    assert collection.raw is raw_collection
    assert collection.database.raw is raw_collection.database
    assert collection.database.manager is manager


def test_cached_rejects_a_collection_owned_by_another_client(
    client: MongoClient[BsonDict],
) -> None:
    manager = CacheManager(client)
    foreign_client = MongoClient[BsonDict]("mongodb://localhost:27017", connect=False)

    with pytest.raises(ValueError, match="different client"):
        manager.get_cached_collection(foreign_client["example"]["items"])


def test_repeated_cached_views_share_the_manager_and_raw_collection(
    client: MongoClient[BsonDict],
) -> None:
    manager = CacheManager(client)
    raw_collection = client["example"]["items"]

    first = manager.get_cached_collection(raw_collection)
    second = manager.get_cached_collection(raw_collection)

    assert first.raw is second.raw is raw_collection
    assert first.database.manager is second.database.manager is manager


@pytest.mark.parametrize("requested", ["", "never-activated"], ids=["empty", "unknown"])
def test_stream_health_echoes_the_requested_name_without_validation(
    client: MongoClient[BsonDict], requested: str
) -> None:
    manager = CacheManager(client)
    health = manager.stream_health_snapshot(requested)
    assert health.requested_database_name == requested
    assert health.status is StreamHealthStatus.NOT_STARTED
    manager.close()
    health = manager.stream_health_snapshot(requested)
    assert health.requested_database_name == requested
    assert health.status is StreamHealthStatus.CLOSED


def test_manager_inspection_delegates_without_activation(
    client: MongoClient[BsonDict],
) -> None:
    manager = CacheManager(client)
    manager.cache_core.record_bypass()
    manager.cache_core.record_stream_poll("example")
    assert isinstance(manager.snapshot(), CacheSnapshot)
    assert isinstance(manager.stream_cost_snapshot("example"), StreamCostSnapshot)
    assert isinstance(manager.stream_health_snapshot("example"), StreamHealthSnapshot)
    assert manager.snapshot() == manager.cache_core.snapshot()
    assert manager.stream_cost_snapshot(
        "example"
    ) == manager.cache_core.stream_cost_snapshot("example")
    assert manager.active_stream_cost_databases() == ["example"]
    assert (
        manager.stream_health_snapshot("example").status
        is StreamHealthStatus.NOT_STARTED
    )
    assert (
        manager.stream_health_snapshot("untouched").status
        is StreamHealthStatus.NOT_STARTED
    )
    manager.close()
    assert manager.snapshot() == manager.cache_core.snapshot()
    assert manager.snapshot().bypasses == 1
    assert manager.snapshot().lifecycle == "closed"
    assert (
        manager.stream_health_snapshot("untouched").status is StreamHealthStatus.CLOSED
    )
    assert manager.stream_cost_snapshot(
        "example"
    ) == manager.cache_core.stream_cost_snapshot("example")
    assert (
        manager.active_stream_cost_databases()
        == manager.cache_core.active_stream_cost_databases()
    )
