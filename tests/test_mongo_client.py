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
    client = MongoClient(
        "mongodb+srv://localhost:27017/",
        replicaset="myReplicaSet",
        # directConnection=True,
        # ssl=True,
        # tlsAllowInvalidCertificates=True,
    )
    # client = MongoClient(
    # "mongodb://localhost:27017,localhost:27018,localhost:27019/?replicaSet=myReplicaSet"
    # "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=myReplicaSet"
    # "mongodb://mongo1,mongo2,mongo3/?replicaSet=myReplicaSet",
    # )
    config = {
        "_id": "myReplicaSet",
        "members": [
            {"_id": 0, "host": "mongo1:27017", "priority": 1},
            {"_id": 1, "host": "mongo2:27017", "priority": 0.5},
            {"_id": 2, "host": "mongo3:27017", "priority": 0.5},
        ],
    }
    try:
        # ...
        client.admin.command("replSetInitiate", config)
    except pymongo.errors.OperationFailure as error:
        if "AlreadyInitialized" not in str(error):
            raise
        logger.info(repr(error))

    logger.info(f"{client = }, {client.nodes = }, {client.topology_description = }")
    db = client.test_database
    # db.command("ping")
    logger.info(f"Connected to {db}.")
    return db


def test_mongo_client(database: CachedDatabase, faker: Faker) -> None:
    post = faker.pydict()
    posts = database.posts
    post_id = posts.insert_one(post).inserted_id

    cached_post = posts.find_one({"_id": post_id})
    assert cached_post == post


async def test_motor() -> None:
    import motor.motor_asyncio

    client = motor.motor_asyncio.AsyncIOMotorClient(
        # "mongodb://mongo1,mongo2,mongo3/?replicaSet=myReplicaSet",
        "mongodb://mongo1,mongo2,mongo3/?replicaSet=myReplicaSet"
    )
    db = client.test
    assert await db.test.find_one({})
    document = {"key": "value"}
    result = await db.test.insert_one(document)
    assert result
