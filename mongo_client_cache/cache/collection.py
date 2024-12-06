from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from threading import Thread

from bson import ObjectId
from pymongo.errors import PyMongoError
from pymongo.synchronous.collection import Collection

from mongo_client_cache._types import (
    BsonDict,
    BsonValue,
    ChangeStreamDocument,
    JsonDict,
)
from mongo_client_cache.cache.exceptions import UnexpectedChangeOperationTypeError
from mongo_client_cache.cache.misc import CommandCount
from mongo_client_cache.logger import logger


class _StopWatchingError(Exception): ...


class CollCache:
    __slots__ = (
        "_collection",
        "_resume_token",
        "client_side_refresh_time",
        "distinct",
        "distinct_per_collection",
        "document_count",
        "documents",
        "estimated_document_count",
        "query_to_ids_map",
        "stop_watching",
        "watch_change_stream",
    )

    def __init__(self, /, collection: Collection, *, watch_change_stream: bool) -> None:
        self._collection = collection
        self.query_to_ids_map: dict[str, BsonDict] = {}
        self.document_count: dict[str, int] = {}
        self.estimated_document_count: int | None = None
        self.distinct: dict[str, list[BsonValue]] = {}
        self.documents: dict[ObjectId, BsonDict] = {}
        self.client_side_refresh_time: datetime = datetime.now(UTC).replace(tzinfo=None)

        self.watch_change_stream = watch_change_stream
        if watch_change_stream:
            self.stop_watching = False
            Thread(target=self.watch, daemon=True).start()

    def watch(self) -> None:
        """
        https://github.com/mongodb/specifications/blob/master/source/change-streams/change-streams.rst
        https://www.mongodb.com/docs/manual/reference/change-events/#change-events
        """
        self._resume_token: dict[str, str] | None = None

        max_retries = 3
        for retry_attempt in count():
            try:
                self._watch()
            except PyMongoError as error:
                # The ChangeStream encountered an unrecoverable error or the
                # resume attempt failed to recreate the cursor.
                if self._resume_token is None:
                    if retry_attempt == max_retries:
                        raise
                    logger.error(
                        "There is no usable resume token because there was a "
                        + "failure during ChangeStream initialization. "
                        + f"Target: '{self._collection}', {retry_attempt=}, {error!r}."
                    )
                logger.error(repr(error))

    def _watch(self) -> None:
        pipeline: list[JsonDict] = [
            {
                "$match": {
                    "operationType": {
                        "$in": [
                            "insert",
                            "update",
                            "replace",
                            "delete",
                            "drop",
                            "rename",
                        ]
                    },
                }
            },
            {
                "$project": {
                    "operationType": True,
                    "documentKey": True,
                    "wallTime": True,
                }
            },
        ]
        logger.info(f'Watching Change Stream for "{self._collection.name}" collection.')
        with self._collection.watch(
            pipeline, resume_after=self._resume_token
        ) as stream:
            if self.stop_watching:
                logger.debug(
                    f"Stopping watching changes on {self._collection.name} collection."
                )
                raise _StopWatchingError
            for change in stream:
                if __debug__:
                    logger.debug(f"{change=}")
                self._process_change_stream(change)

                # Use the interrupted ChangeStream's resume token to create
                # a new ChangeStream. The new stream will continue from the
                # last seen insert change without missing any events.
                self._resume_token = stream.resume_token

    def _insert(self, change: ChangeStreamDocument) -> None:
        if (
            change["wallTime"] > self.client_side_refresh_time
            and self.estimated_document_count is not None
        ):
            self.estimated_document_count += 1
            self.document_count[str(CommandCount({}))] += 1
        elif __debug__:
            logger.debug(f"{change['wallTime']=} < {self.client_side_refresh_time=}")
        # Invalidate all cached queries.
        self.query_to_ids_map.clear()
        self.distinct.clear()

    def _update(self, change: ChangeStreamDocument) -> None:
        raise NotImplementedError

    def _replace(self, change: ChangeStreamDocument) -> None:
        raise NotImplementedError

    def _delete(self, change: ChangeStreamDocument) -> None:
        try:
            del self.documents[change["documentKey"]["_id"]]
        except KeyError:
            pass
        if self.estimated_document_count is not None:
            self.estimated_document_count -= 1
        self.document_count[str(CommandCount({}))] -= 1
        # Invalidate all cached queries.
        self.query_to_ids_map.clear()
        self.distinct.clear()

    def _drop(self, change: ChangeStreamDocument) -> None:
        self.query_to_ids_map.clear()
        self.document_count.clear()
        self.estimated_document_count = None
        self.distinct.clear()

    def _rename(self, change: ChangeStreamDocument) -> None:
        raise NotImplementedError

    def _process_change_stream(self, change: ChangeStreamDocument) -> None:
        operation_type = change["operationType"]
        if operation_type == "insert":
            self._insert(change)
        elif operation_type == "update":
            self._update(change)
        elif operation_type == "replace":
            self._replace(change)
        elif operation_type == "delete":
            self._delete(change)
        elif operation_type == "drop":
            self._drop(change)
        elif operation_type == "rename":
            self._rename(change)
        else:
            raise UnexpectedChangeOperationTypeError(change["operationType"])

    def clear(self) -> None:
        self.query_to_ids_map.clear()
        self.document_count.clear()
        self.estimated_document_count = None
        self.distinct.clear()
