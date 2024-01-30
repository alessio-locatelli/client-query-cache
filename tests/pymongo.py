import logging

import pytest
import pymongo


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


def test_mongo_client() -> None:
    port = 30001
    connectTimeoutMS = 5000

    client = pymongo.MongoClient(
        "0.0.0.0", port, connectTimeoutMS=connectTimeoutMS, directConnection=True
    )
    config = {
        "_id": "my-mongo-set",
        "members": [
            {"_id": 0, "host": "mongo1:27017"},
            {"_id": 1, "host": "mongo2:27017"},
            {"_id": 2, "host": "mongo3:27017"},
        ],
    }
    client.admin.command("replSetInitiate", config)

    db = client.test_database
    db.command("ping")

    logger.info(f"Connected to {db}.")

    with db.watch() as stream:
        logger.info(f"Connected to {stream}.")
        for change in stream:
            print(change)
