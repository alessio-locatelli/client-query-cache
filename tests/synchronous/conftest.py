import logging
import os
from collections.abc import Iterator

import pytest

from mongo_client_cache.cache.misc import CollectionConfig
from mongo_client_cache.synchronous.mongo_client import CachedMongoClient

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def cached_mongo_client(
    persistent_collection_name: str,
    nonpersistent_collection_name: str,
    cached_database_name: str,
) -> Iterator[CachedMongoClient]:
    client = CachedMongoClient(
        "mongodb+srv://"
        + f"{os.environ['REPLICA_MONGO_NAME']}:{os.environ['REPLICA_MONGO_PASSWORD']}"
        + f"@{os.environ['REPLICA_MONGO_HOST']}/?retryWrites=true&w=majority",
        cache_config={
            cached_database_name: [
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
