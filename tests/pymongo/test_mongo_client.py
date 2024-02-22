import os

from mongo_client_cache.cached_pymongo.mongo_client import CachedMongoClient


def test_cached_mongo_client_without_cache_config() -> None:
    """`MongoClient` can be used without cache config."""
    client = CachedMongoClient(
        f"mongodb+srv://{os.environ["REPLICA_MONGO_NAME"]}:{os.environ["REPLICA_MONGO_PASSWORD"]}@{os.environ["REPLICA_MONGO_HOST"]}/?retryWrites=true&w=majority",
    )
    db = client.db_test
    assert db.command("ping")
