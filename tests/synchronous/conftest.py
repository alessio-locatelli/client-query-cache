import logging
import os
from collections.abc import Callable, Iterator

import pytest

from mongo_client_cache.cache.misc import CollectionConfig
from mongo_client_cache.synchronous.collection import CachedCollection
from mongo_client_cache.synchronous.database import CachedDatabase
from mongo_client_cache.synchronous.mongo_client import CachedMongoClient

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def cached_mongo_client(
    persistent_collection_name: str, nonpersistent_collection_name: str
) -> Iterator[CachedMongoClient]:
    client = CachedMongoClient(
        "mongodb+srv://"
        + f"{os.environ['REPLICA_MONGO_NAME']}:{os.environ['REPLICA_MONGO_PASSWORD']}"
        + f"@{os.environ['REPLICA_MONGO_HOST']}/?retryWrites=true&w=majority",
        cache_config={
            "db_one": [
                CollectionConfig(
                    collection_name=persistent_collection_name,
                    watch_change_stream=False,
                ),
                CollectionConfig(
                    collection_name=nonpersistent_collection_name,
                    watch_change_stream=True,
                ),
            ],
            "db_two": [
                CollectionConfig(
                    collection_name=persistent_collection_name,
                )
            ],
        },
    )
    logger.info(f"{client = }, {client.nodes = }, {client.topology_description = }")
    yield client
    client.close()


@pytest.fixture
def mongo_database(mongo_client: CachedMongoClient) -> Callable[[str], CachedDatabase]:
    def _mongo_database(database_name: str) -> CachedDatabase:
        db = mongo_client[database_name]
        db.command("ping")
        logger.debug(f"Connected to {db}.")
        assert isinstance(db, CachedDatabase)
        return db

    return _mongo_database


@pytest.fixture
def create_cached_mongo_collection(
    mongo_client: CachedMongoClient,
) -> Callable[[str, str], CachedCollection]:
    def _create_cached_mongo_collection(
        database_name: str, collection_name: str
    ) -> CachedCollection:
        collection = mongo_client[database_name][collection_name]
        assert isinstance(collection, CachedCollection)
        return collection

    return _create_cached_mongo_collection
