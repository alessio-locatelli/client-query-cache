import logging
import os
from collections.abc import Iterator

import pytest

from mongo_client_cache import CollectionConfig
from mongo_client_cache.synchronous.mongo_client import CachedMongoClient

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def cached_mongo_client(
    persistent_collection_name: str,
    nonpersistent_collection_name: str,
    cached_database_name: str,
) -> Iterator[CachedMongoClient]:
    client = CachedMongoClient(
        os.getenv("MONGODB_HOST", "localhost:27017"),
        cache_config={
            cached_database_name: {
                persistent_collection_name: CollectionConfig(watch_change_stream=False),
                nonpersistent_collection_name: CollectionConfig(
                    watch_change_stream=True
                ),
            },
            "db_two": {persistent_collection_name: CollectionConfig()},
        },
    )
    logger.info(f"{client = }, {client.nodes = }, {client.topology_description = }")
    yield client
    client.close()
