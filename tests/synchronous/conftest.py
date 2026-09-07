import logging
import os
from collections.abc import Iterator
from typing import Any

import pytest
from pymongo import MongoClient
from pymongo.synchronous.collection import Collection

from mongo_client_cache import CollectionConfig
from mongo_client_cache.synchronous.collection import CachedCollection
from mongo_client_cache.synchronous.mongo_client import CachedMongoClient
from tests.conftest import CollectionName, DatabaseName, MongoDbUri

logger = logging.getLogger(__name__)

CI_CHANGE_STREAM_AWAIT_TIME_S = 30


@pytest.fixture(autouse=True)
def _generous_change_stream_wait_on_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        monkeypatch.setattr(
            CachedCollection,
            "_max_change_stream_await_time_s",
            CI_CHANGE_STREAM_AWAIT_TIME_S,
        )


@pytest.fixture
def raw_mongo_client(
    mongodb_uri: MongoDbUri,
) -> Iterator[MongoClient[dict[str, Any]]]:
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        yield client


@pytest.fixture
def raw_collection(
    raw_mongo_client: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> Collection:
    return raw_mongo_client[cached_database_name][nonpersistent_collection_name]


@pytest.fixture
def cached_mongo_client(
    mongodb_uri: MongoDbUri,
    persistent_collection_name: CollectionName,
    nonpersistent_collection_name: CollectionName,
    cached_database_name: DatabaseName,
) -> Iterator[CachedMongoClient]:
    client = CachedMongoClient(
        mongodb_uri,
        cache_config={
            cached_database_name: {
                persistent_collection_name: CollectionConfig(watch_change_stream=False),
                nonpersistent_collection_name: CollectionConfig(
                    watch_change_stream=True
                ),
            },
            DatabaseName(f"{cached_database_name}_two"): {
                persistent_collection_name: CollectionConfig()
            },
        },
    )
    logger.debug(
        f"[SETUP] {client = }, {client.nodes = }, {client.topology_description = }"  # noqa: G004
    )
    yield client
    logger.debug("[TEARDOWN] Closing %s.", client)
    client.close()
