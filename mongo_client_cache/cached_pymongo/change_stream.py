from collections.abc import Mapping
from typing import Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from mongo_client_cache.logger import logger


class Watch:
    """
    https://github.com/mongodb/specifications/blob/master/source/change-streams/change-streams.rst
    https://www.mongodb.com/docs/manual/reference/change-events/#change-events
    """

    __slots__ = ("_target", "_resume_token", "_collections")

    def __call__(
        self, target: MongoClient, collections: list[str] | None = None
    ) -> None:
        self._target = target
        self._collections = collections
        self._resume_token: Mapping[str, Any] | None = None

        retry_count = 3
        while True:
            try:
                self._watch()
            except PyMongoError as error:
                # The ChangeStream encountered an unrecoverable error or the
                # resume attempt failed to recreate the cursor.
                if self._resume_token is None:
                    if retry_count == 0:
                        raise
                    retry_count -= 1
                    logger.error(
                        "There is no usable resume token because there was a "
                        + "failure during ChangeStream initialization. "
                        + f"Target: {target}, {error!r}"
                    )

    def _watch(self) -> None:
        pipeline = [
            {
                "$match": {
                    # "ns.coll": {"$in": ["example", "foobar"]},
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
        ]
        if self._collections:
            pipeline[0]["$match"]["$ns.coll"] = {"$in": self._collections}
        with self._target.watch(
            pipeline, full_document="updateLookup", resume_after=self._resume_token
        ) as stream:
            for change in stream:
                logger.debug(f"{change = }")

                # Use the interrupted ChangeStream's resume token to create
                # a new ChangeStream. The new stream will continue from the
                # last seen insert change without missing any events.
                self._resume_token = stream.resume_token
