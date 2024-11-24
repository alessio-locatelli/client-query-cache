import os

import pytest

from mongo_client_cache.cached_pymongo.mongo_client import CachedMongoClient
from mongo_client_cache.core.exceptions import ReservedAttributeError


def test_cached_mongo_client_without_cache_config() -> None:
    """`MongoClient` can be used without cache config."""
    client = CachedMongoClient(
        f"mongodb+srv://{os.environ['REPLICA_MONGO_NAME']}:{os.environ['REPLICA_MONGO_PASSWORD']}@{os.environ['REPLICA_MONGO_HOST']}/?retryWrites=true&w=majority",
    )

    # Access via attribute.
    database_1 = client.db_test1
    assert database_1.command("ping")["ok"] == 1

    # Access via `get()`.
    database_2 = client["db_test2"]
    assert database_2.command("ping")["ok"] == 1

    with pytest.raises(ReservedAttributeError, match="_client_side_databases"):
        _ = client["_client_side_databases"]

    with pytest.raises(ReservedAttributeError, match="_client_side_cache_config"):
        _ = client["_client_side_cache_config"]
