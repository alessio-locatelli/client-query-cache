from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pymongo
import pytest
from pymongo import MongoClient

from client_query_cache import CacheManager
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.keys import NamespaceId
from tests.barrier_helpers import (
    BARRIER_TIMEOUT_SECONDS,
    SPREAD_DOCUMENT_COUNT,
    spread_documents,
)
from tests.polling import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from faker import Faker
    from pymongo.synchronous.collection import Collection

    from client_query_cache import CachedCollection
    from tests.barrier_helpers import AggregateRecorder, Topology
    from tests.conftest import DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


@pytest.fixture
def client(
    topology: Topology, aggregate_recorder: AggregateRecorder
) -> Iterator[MongoClient[dict[str, Any]]]:
    with MongoClient[dict[str, Any]](
        topology.uri, w="majority", event_listeners=[aggregate_recorder]
    ) as mongo_client:
        yield mongo_client


@pytest.fixture
def manager(
    client: MongoClient[dict[str, Any]],
) -> Iterator[CacheManager[dict[str, Any]]]:
    with CacheManager(client) as cache_manager:
        yield cache_manager


@pytest.fixture
def items(
    client: MongoClient[dict[str, Any]],
    topology: Topology,
    cached_database_name: DatabaseName,
    faker: Faker,
) -> Iterator[Collection[dict[str, Any]]]:
    database = client[cached_database_name]
    collection = database.create_collection("items")
    if topology.sharded:
        client.admin.command("enableSharding", cached_database_name)
        client.admin.command(
            "shardCollection", collection.full_name, key={"_id": "hashed"}
        )
    collection.insert_many(
        spread_documents([faker.word() for _ in range(SPREAD_DOCUMENT_COUNT)])
    )
    yield collection
    client.drop_database(cached_database_name)


@pytest.fixture
def transaction_collections(
    mongodb_uri: MongoDbUri, cached_database_name: DatabaseName
) -> Iterator[tuple[Collection[dict[str, Any]], Collection[dict[str, Any]]]]:
    with MongoClient[dict[str, Any]](mongodb_uri, w="majority") as mongo_client:
        database = mongo_client[cached_database_name]
        collections = (
            database.create_collection("first"),
            database.create_collection("second"),
        )
        for collection in collections:
            collection.insert_one({"_id": 1, "value": 0})
        yield collections
        mongo_client.drop_database(cached_database_name)


def _warm(manager: CacheManager[Any], *reads: Callable[[], object]) -> None:
    def _every_read_hits() -> bool:
        hits_before = manager.cache_core.snapshot().hits
        for read in reads:
            read()
        return manager.cache_core.snapshot().hits - hits_before == len(reads)

    wait_until(_every_read_hits)


def _warm_items(
    manager: CacheManager[dict[str, Any]], items: Collection[dict[str, Any]]
) -> CachedCollection[dict[str, Any]]:
    cached = manager.cached(items)
    _warm(
        manager,
        lambda: cached.find_one({"_id": 1}),
        lambda: cached.find({"group": "spread"}),
    )
    return cached


def test_a_barrier_makes_cached_document_and_query_reads_observe_the_write(
    manager: CacheManager[dict[str, Any]],
    items: Collection[dict[str, Any]],
    client: MongoClient[dict[str, Any]],
) -> None:
    cached = _warm_items(manager, items)

    with client.start_session() as session:
        items.update_many({"group": "spread"}, {"$set": {"value": 1}}, session=session)
        boundary = manager.causal_boundary(session)
    manager.wait_for_invalidations(
        items.database.name, boundary, timeout=BARRIER_TIMEOUT_SECONDS
    )

    document = cached.find_one({"_id": 1})
    assert document is not None
    assert document["value"] == 1
    assert {row["value"] for row in cached.find({"group": "spread"})} == {1}


def test_a_barrier_completes_after_a_no_op_write_on_an_idle_database(
    manager: CacheManager[dict[str, Any]],
    items: Collection[dict[str, Any]],
    client: MongoClient[dict[str, Any]],
) -> None:
    _warm_items(manager, items)

    with client.start_session() as session:
        no_op_update = items.update_one(
            {"_id": "missing"}, {"$set": {"value": 1}}, session=session
        )
        boundary = manager.causal_boundary(session)
    manager.wait_for_invalidations(
        items.database.name, boundary, timeout=BARRIER_TIMEOUT_SECONDS
    )

    assert no_op_update.matched_count == 0


def test_a_read_captured_before_the_write_is_not_admitted_after_the_barrier(
    manager: CacheManager[dict[str, Any]],
    items: Collection[dict[str, Any]],
    client: MongoClient[dict[str, Any]],
) -> None:
    _warm_items(manager, items)
    namespace = NamespaceId(items.database.name, items.name)
    capture = manager.cache_core.begin_identity_admission(namespace, 2)
    stale_document = items.find_one({"_id": 2})

    with client.start_session() as session:
        items.update_one({"_id": 2}, {"$set": {"value": 2}}, session=session)
        boundary = manager.causal_boundary(session)
    manager.wait_for_invalidations(
        items.database.name, boundary, timeout=BARRIER_TIMEOUT_SECONDS
    )

    outcome = manager.cache_core.admit_identity(capture, "full", stale_document)
    assert outcome is AdmissionOutcome.DECLINED_STALE


def test_ordinary_cached_reads_issue_no_barrier_commands(
    manager: CacheManager[dict[str, Any]],
    items: Collection[dict[str, Any]],
    aggregate_recorder: AggregateRecorder,
) -> None:
    _warm_items(manager, items)

    assert not aggregate_recorder.barrier_aggregates()


def test_a_stream_activated_inside_a_driver_timeout_keeps_running(
    manager: CacheManager[dict[str, Any]],
    items: Collection[dict[str, Any]],
    client: MongoClient[dict[str, Any]],
) -> None:
    activation_timeout = 0.5
    with pymongo.timeout(activation_timeout):
        manager.cached(items).find_one({"_id": 3})
    time.sleep(activation_timeout * 3)

    with client.start_session() as session:
        items.update_one({"_id": 3}, {"$set": {"value": 3}}, session=session)
        boundary = manager.causal_boundary(session)
    manager.wait_for_invalidations(
        items.database.name, boundary, timeout=BARRIER_TIMEOUT_SECONDS
    )

    document = manager.cached(items).find_one({"_id": 3})
    assert document is not None
    assert document["value"] == 3


def test_a_barrier_covers_a_committed_transaction_across_collections(
    transaction_collections: tuple[
        Collection[dict[str, Any]], Collection[dict[str, Any]]
    ],
) -> None:
    client = transaction_collections[0].database.client
    with CacheManager(client) as manager:
        cached = [manager.cached(collection) for collection in transaction_collections]
        _warm(
            manager, *(lambda view=view: view.find_one({"_id": 1}) for view in cached)
        )

        with client.start_session() as session:
            session.with_transaction(
                lambda transaction_session: [
                    collection.update_one(
                        {"_id": 1}, {"$set": {"value": 1}}, session=transaction_session
                    )
                    for collection in transaction_collections
                ]
            )
            boundary = manager.causal_boundary(session)
        manager.wait_for_invalidations(
            transaction_collections[0].database.name,
            boundary,
            timeout=BARRIER_TIMEOUT_SECONDS,
        )

        assert [view.find_one({"_id": 1}) for view in cached] == [
            {"_id": 1, "value": 1},
            {"_id": 1, "value": 1},
        ]
