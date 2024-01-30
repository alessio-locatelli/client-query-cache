import logging

from faker import Faker
import pymongo
from pymongo.database import Database
from pymongo.mongo_client import MongoClient
import pytest
from mongo_client_cache.database import CachedDatabase

from mongo_client_cache.mongo_client import CachedMongoClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
def database() -> Database:
    client = CachedMongoClient("localhost", 30001, directConnection=True)
    config = {
        "_id": "my-mongo-set",
        "members": [
            {"_id": 0, "host": "mongo1:27017"},
            {"_id": 1, "host": "mongo2:27017"},
            {"_id": 2, "host": "mongo3:27017"},
        ],
    }
    try:
        client.admin.command("replSetInitiate", config)
    except pymongo.errors.OperationFailure as error:
        if "AlreadyInitialized" not in str(error):
            raise

    logger.info(f"{client = }, {client.nodes = }, {client.topology_description = }")
    db = client.test_database
    db.command("ping")
    logger.info(f"Connected to {db}.")
    return db


def test_mongo_client(database: CachedDatabase, faker: Faker) -> None:
    post = faker.pydict()
    posts = database.posts
    post_id = posts.insert_one(post).inserted_id

    cached_post = posts.find_one({"_id": post_id})
    assert cached_post == post
