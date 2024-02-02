import logging
import os

import pytest

from mongo_client_cache.backends.base import CollectionConfig
from mongo_client_cache.backends.memory import MemoryBackend
from mongo_client_cache.pymongo.collection import CachedCollection
from mongo_client_cache.pymongo.database import CachedDatabase
from mongo_client_cache.pymongo.mongo_client import CachedMongoClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
def collection_name() -> str:
    return "example"


@pytest.fixture
def example_database(collection_name: str) -> CachedDatabase:
    client = CachedMongoClient(
        f"mongodb+srv://{os.environ['MONGO_NAME']}:{os.environ['MONGO_PASSWORD']}@{os.environ['MONGO_HOST']}/?retryWrites=true&w=majority",
        cache_backend=MemoryBackend(
            config_per_collection=[
                CollectionConfig(name=collection_name, watch_change_stream=False)
            ]
        ),
    )
    logger.info(f"{client = }, {client.nodes = }, {client.topology_description = }")
    db = client.test_database
    db.command("ping")
    logger.info(f"Connected to {db}.")
    return db


@pytest.fixture
def example_collection(
    example_database: CachedDatabase, collection_name: str
) -> CachedCollection:
    return example_database[collection_name]
