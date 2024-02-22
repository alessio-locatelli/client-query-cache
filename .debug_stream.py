import logging
import os

from pymongo.mongo_client import MongoClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

url = f"mongodb+srv://{os.environ["REPLICA_MONGO_NAME"]}:{os.environ["REPLICA_MONGO_PASSWORD"]}@{os.environ["REPLICA_MONGO_HOST"]}/?retryWrites=true&w=majority"
client: MongoClient = MongoClient(url)
logger.info(f"{client = }, {client.nodes = }, {client.topology_description = }")

# db = client.test_database

with client.watch(
    [
        {
            "$match": {
                "ns.coll": {"$in": ["example", "foobar"]},
                "operationType": {
                    "$in": [
                        "insert",
                        "update",
                        "replace",
                        "delete",
                        "drop",
                        "dropDatabase",
                        "rename",
                    ]
                },
            }
        },
        {
            "$project": {
                "operationType": True,
                "ns": True,
                "fullDocument": True,
                "documentKey": True,
            }
        },
    ],
    full_document="updateLookup",
) as stream:
    for change in stream:
        logger.info(change)
