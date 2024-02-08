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


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "db" in metafunc.fixturenames:
        metafunc.parametrize("mongo_client", ["standalone", "replica"], indirect=True)


@pytest.fixture(scope="session")
def mongo_client(
    request: pytest.FixtureRequest, collection_name: str
) -> CachedMongoClient:
    if request.param == "standalone":
        url = f"mongodb://{os.environ['STANDALONE_MONGO_HOST']}:{os.environ['STANDALONE_MONGO_PORT']}/?retryWrites=true&w=majority"
    if request.param == "replica":
        url = (
            f"mongodb+srv://{os.environ['REPLICA_MONGO_NAME']}:{os.environ['REPLICA_MONGO_PASSWORD']}@{os.environ['REPLICA_MONGO_HOST']}/?retryWrites=true&w=majority",
        )
    else:
        raise ValueError("Invalid internal test config.")

    client = CachedMongoClient(
        url,
        cache_backend=MemoryBackend(
            config_per_collection=[
                CollectionConfig(
                    name=collection_name,
                    watch_change_stream=bool(request.param == "replica"),
                )
            ]
        ),
    )
    logger.info(f"{client = }, {client.nodes = }, {client.topology_description = }")
    return client


@pytest.fixture(scope="session")
def mongo_database(mongo_client: CachedMongoClient) -> CachedDatabase:
    db = mongo_client.test_database
    db.command("ping")
    logger.info(f"Connected to {db}.")
    assert isinstance(db, CachedDatabase)
    return db


@pytest.fixture
def mongo_collection(
    example_database: CachedDatabase, collection_name: str
) -> CachedCollection:
    collection = example_database[collection_name]
    assert isinstance(collection, CachedCollection)
    return collection
