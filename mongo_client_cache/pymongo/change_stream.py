from pymongo.errors import PyMongoError
from mongo_client_cache.logger import logger


class WatchCollection:
    """
    https://github.com/mongodb/specifications/blob/master/source/change-streams/change-streams.rst
    """

    __slots__ = ("_collection", "_resume_token", "_watch")

    def __call__(self, collection) -> None:
        self._collection = collection
        self._resume_token = None

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
                        + f"Collection: {collection.name}, {error!r}"
                    )

    def _watch(self) -> None:
        pipeline = [{"$match": {"operationType": "insert"}}]
        with self._collection.watch(
            pipeline, resume_after=self._resume_token
        ) as stream:
            for insert_change in stream:
                print(insert_change)

                # Use the interrupted ChangeStream's resume token to create
                # a new ChangeStream. The new stream will continue from the
                # last seen insert change without missing any events.
                self._resume_token = stream.resume_token
