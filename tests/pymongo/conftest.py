import logging
import os
from collections.abc import Callable

import pytest

from mongo_client_cache.cached_pymongo.collection import CachedCollection
from mongo_client_cache.cached_pymongo.database import CachedDatabase
from mongo_client_cache.cached_pymongo.mongo_client import CachedMongoClient
from mongo_client_cache.core.misc import CollectionConfig

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def mongo_client(
    persistent_collection_name: str,
    nonpersistent_collection_name: str,
    create_database_name: Callable[[str], str],
) -> CachedMongoClient:
    client = CachedMongoClient(
        f"mongodb+srv://{os.environ["REPLICA_MONGO_NAME"]}:{os.environ["REPLICA_MONGO_PASSWORD"]}@{os.environ["REPLICA_MONGO_HOST"]}/?retryWrites=true&w=majority",
        client_side_cache_config={
            create_database_name("one"): [
                CollectionConfig(
                    collection_name=persistent_collection_name,
                    watch_change_stream=False,
                ),
                CollectionConfig(
                    collection_name=nonpersistent_collection_name,
                    watch_change_stream=True,
                ),
            ],
            create_database_name("two"): [
                CollectionConfig(
                    collection_name=persistent_collection_name,
                    enable_client_side_cache=False,
                )
            ],
        },
    )
    logger.info(f"{client = }, {client.nodes = }, {client.topology_description = }")
    return client


@pytest.fixture()
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
